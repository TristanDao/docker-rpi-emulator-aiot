import asyncio
import collections
import json
import logging
import signal
from datetime import datetime, timezone

from aiohttp import web

from app.annotator import annotate_frame, encode_jpeg
from app.camera import CameraStream
from app.config import (
    DEVICE_ID, DEVICE_LOCATION, EDGE_API_PORT, PROCESS_EVERY_N,
    ENROLL_SAMPLES, ENROLL_TIMEOUT, OFFLINE_RETRY_INTERVAL, SERVER_URL,
)
from app.detector import detect_and_encode
from app.enroller import EnrollmentSession
from app.recognizer import FaceRecognizer
from app import api_client
from app.offline_queue import OfflineQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("edge")

recognizer = FaceRecognizer()
offline_queue = OfflineQueue()
_running = True
_enrollment_queue: asyncio.Queue = asyncio.Queue()

_latest_frame: bytes = b""
_user_names: dict[int, str] = {}
_current_mode: str = "trace"  # "trace" = display only, "checkin" = send attendance
_recent_events: collections.deque = collections.deque(maxlen=50)


def _signal_handler(sig, frame):
    global _running
    logger.info("Shutdown signal received")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def load_embeddings_from_server():
    logger.info("Loading embeddings from server: %s", SERVER_URL)
    for attempt in range(10):
        items = await api_client.fetch_embeddings()
        if items:
            encodings = [it["encoding"] for it in items]
            labels = [{"user_id": it["user_id"]} for it in items]
            recognizer.load_embeddings(encodings, labels)
            await _load_user_names(labels)
            return
        logger.warning("No embeddings yet, retry %d/10 in 5s...", attempt + 1)
        await asyncio.sleep(5)
    logger.warning("Starting with empty embedding list")


async def _load_user_names(labels: list[dict]):
    user_ids = set(l["user_id"] for l in labels)
    for uid in user_ids:
        if uid not in _user_names:
            user = await api_client.fetch_user(uid)
            if user:
                _user_names[uid] = user["full_name"]


async def retry_offline_events():
    while _running:
        await asyncio.sleep(OFFLINE_RETRY_INTERVAL)
        events = offline_queue.pop_batch()
        if not events:
            continue
        logger.info("Retrying %d offline events...", len(events))
        for event in events:
            payload = event["payload"]
            if event["event_type"] == "attendance":
                result = await api_client.send_attendance(**payload)
            else:
                result = await api_client.send_unknown(**payload)

            if result is not None:
                offline_queue.mark_done(event["id"])
                logger.info("Offline event %d sent successfully", event["id"])
            else:
                offline_queue.increment_retry(event["id"])


async def handle_enrollment(user_id: int, samples: int, timeout: int) -> dict:
    """Run enrollment session: capture faces and send embeddings to server."""
    session = EnrollmentSession(target_samples=samples, timeout=timeout)
    logger.info("Enrollment started for user %d (%d samples, %ds timeout)",
                user_id, samples, timeout)

    success = session.capture()
    collected = session.count

    if collected == 0:
        return {"error": "No face samples captured", "collected": 0}

    if not success:
        logger.warning("Only captured %d/%d samples", collected, samples)

    result = await api_client.send_enrollment(user_id, session.samples, DEVICE_ID)
    if result is None:
        return {"error": "Failed to send enrollment to server", "collected": collected}

    await load_embeddings_from_server()
    return result


def _get_overlay_info() -> dict:
    enrolling = not _enrollment_queue.empty()
    if enrolling:
        mode = "ENROLLING"
    elif _current_mode == "checkin":
        mode = "CHECK-IN"
    else:
        mode = "TRACE"
    return {
        "device_id": DEVICE_ID,
        "location": DEVICE_LOCATION,
        "mode": mode,
    }


async def recognition_loop():
    global _latest_frame

    camera = None
    for attempt in range(30):
        try:
            cam = CameraStream()
            cam.start()
            camera = cam
            break
        except RuntimeError:
            logger.warning(
                "Camera source not ready (attempt %d/30), retrying in 5s... "
                "If using MJPEG stream make sure camera_bridge.py is running on the host.",
                attempt + 1,
            )
            await asyncio.sleep(5)

    if camera is None:
        fallback = "/app/test_videos/classroom_demo.mp4"
        logger.warning(
            "Primary camera source unavailable after all retries. "
            "Falling back to demo video: %s", fallback,
        )
        try:
            camera = CameraStream(source=fallback)
            camera.start()
        except RuntimeError:
            logger.error("Fallback video also unavailable. Stopping recognition loop.")
            return

    frame_count = 0
    last_face_results: list[tuple[tuple, dict | None]] = []
    logger.info("Recognition loop started (process every %d frames)", PROCESS_EVERY_N)

    while _running and camera.is_running():
        try:
            enroll_req = _enrollment_queue.get_nowait()
        except asyncio.QueueEmpty:
            enroll_req = None

        if enroll_req is not None:
            logger.info("Pausing recognition for enrollment...")
            camera.stop()
            try:
                result = await handle_enrollment(
                    enroll_req["user_id"],
                    enroll_req["samples"],
                    enroll_req["timeout"],
                )
                enroll_req["future"].set_result(result)
            except Exception as e:
                logger.exception("Enrollment failed")
                enroll_req["future"].set_result({"error": str(e)})

            logger.info("Resuming recognition...")
            camera = CameraStream()
            try:
                camera.start()
            except RuntimeError:
                logger.error("Cannot restart camera after enrollment")
                return
            frame_count = 0
            last_face_results = []
            continue

        frame = camera.read()
        if frame is None:
            continue

        frame_count += 1

        if frame_count % PROCESS_EVERY_N != 0:
            annotated = annotate_frame(frame, last_face_results, _user_names, _get_overlay_info())
            _latest_frame = encode_jpeg(annotated)
            continue

        faces = detect_and_encode(frame)

        current_results: list[tuple[tuple, dict | None]] = []

        for face_loc, encoding in faces:
            now = datetime.now(timezone.utc)
            match = recognizer.recognize(encoding)
            current_results.append((face_loc, match))

            if match:
                user_id = match["user_id"]

                if _current_mode == "checkin":
                    if recognizer.is_cooldown_active(user_id):
                        continue

                    logger.info(
                        "CHECK-IN MATCH: user_id=%d confidence=%.3f distance=%.3f",
                        user_id, match["confidence"], match["distance"],
                    )

                    payload = {
                        "user_id": user_id,
                        "timestamp": now.isoformat(),
                        "confidence": match["confidence"],
                        "match_distance": match["distance"],
                        "device_id": DEVICE_ID,
                        "location": DEVICE_LOCATION,
                    }
                    result = await api_client.send_attendance(**payload)
                    if result is None:
                        offline_queue.push("attendance", payload)
                    elif result.get("action") in ("CHECK_IN", "CHECK_OUT"):
                        name = _user_names.get(user_id, f"User #{user_id}")
                        _recent_events.append({
                            "action": result["action"],
                            "user": name,
                            "message": result.get("message", ""),
                            "time": now.strftime("%H:%M:%S"),
                        })
                else:
                    logger.debug(
                        "TRACE: user_id=%d confidence=%.3f (not sending)",
                        user_id, match["confidence"],
                    )
            else:
                if _current_mode == "checkin":
                    logger.info("UNKNOWN face detected")
                    payload = {
                        "timestamp": now.isoformat(),
                        "device_id": DEVICE_ID,
                        "location": DEVICE_LOCATION,
                    }
                    result = await api_client.send_unknown(**payload)
                    if result is None:
                        offline_queue.push("unknown", payload)

        last_face_results = current_results

        annotated = annotate_frame(frame, current_results, _user_names, _get_overlay_info())
        _latest_frame = encode_jpeg(annotated)

        await asyncio.sleep(0.01)

    camera.stop()
    logger.info("Recognition loop stopped")


# ── Edge HTTP API ──

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi Face Attendance</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0f0f14;color:#e2e8f0;min-height:100vh}

  /* Header */
  .header{padding:12px 24px;background:#1a1a2e;border-bottom:1px solid #2d2d44;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .header h1{font-size:16px;font-weight:700;letter-spacing:.5px;color:#fff}
  .pills{display:flex;gap:10px;flex-wrap:wrap}
  .pill{background:#23233a;border:1px solid #33334d;border-radius:20px;padding:4px 12px;font-size:12px;color:#94a3b8}
  .pill span{color:#4ade80;font-weight:700}
  .pill.mode-enrolling span{color:#fbbf24}
  .pill.mode-trace span{color:#60a5fa}

  /* Mode toggle */
  .mode-btn{padding:6px 16px;border:2px solid #3d3d5c;border-radius:20px;font-size:12px;font-weight:700;cursor:pointer;transition:all .25s;background:#23233a;color:#94a3b8}
  .mode-btn:hover{border-color:#4ade80;color:#e2e8f0}
  .mode-btn.active-checkin{background:#052e16;border-color:#4ade80;color:#4ade80}
  .mode-btn.active-trace{background:#1e1b4b;border-color:#60a5fa;color:#60a5fa}

  /* Layout */
  .layout{display:grid;grid-template-columns:1fr 380px;gap:0;height:calc(100vh - 53px)}
  @media(max-width:900px){.layout{grid-template-columns:1fr;height:auto}}

  /* Video */
  .video-panel{background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
  .video-panel img{width:100%;height:100%;object-fit:contain;display:block}

  /* Side panel */
  .side{background:#13131f;border-left:1px solid #2d2d44;display:flex;flex-direction:column;overflow:hidden}

  /* Tabs */
  .tabs{display:flex;border-bottom:1px solid #2d2d44}
  .tab{flex:1;padding:12px 8px;font-size:13px;font-weight:600;text-align:center;cursor:pointer;color:#64748b;border-bottom:2px solid transparent;transition:all .2s}
  .tab.active{color:#4ade80;border-bottom-color:#4ade80;background:#1a1a2e}
  .tab:hover:not(.active){color:#94a3b8;background:#1a1a2e40}

  /* Tab content */
  .tab-content{display:none;flex-direction:column;gap:14px;padding:18px;overflow-y:auto;flex:1}
  .tab-content.active{display:flex}

  /* Form */
  .field{display:flex;flex-direction:column;gap:5px}
  .field label{font-size:11px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.6px}
  .field input,.field select{padding:8px 12px;background:#1e1e30;border:1px solid #3d3d5c;border-radius:6px;color:#e2e8f0;font-size:14px;outline:none;transition:border-color .2s}
  .field input:focus,.field select:focus{border-color:#4ade80}
  .field input::placeholder{color:#475569}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}

  /* Buttons */
  .btn{padding:10px 20px;border:none;border-radius:6px;font-size:14px;font-weight:700;cursor:pointer;transition:all .2s;width:100%}
  .btn-green{background:#4ade80;color:#0f0f14}
  .btn-green:hover:not(:disabled){background:#22c55e}
  .btn-blue{background:#3b82f6;color:#fff}
  .btn-blue:hover:not(:disabled){background:#2563eb}
  .btn:disabled{background:#2d2d44;color:#475569;cursor:not-allowed}

  /* Result */
  .result{padding:10px 12px;border-radius:6px;font-size:13px;min-height:0;line-height:1.5}
  .result.ok{background:#052e16;border:1px solid #166534;color:#4ade80}
  .result.err{background:#2d1111;border:1px solid #7f1d1d;color:#f87171}
  .result.info{background:#1e1b4b;border:1px solid #3730a3;color:#a5b4fc}
  .result.warn{background:#2d1f00;border:1px solid #92400e;color:#fbbf24}

  /* User list */
  .user-list{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto}
  .user-item{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#1e1e30;border:1px solid #2d2d44;border-radius:6px;cursor:pointer;transition:border-color .2s}
  .user-item:hover{border-color:#4ade80}
  .user-item.selected{border-color:#4ade80;background:#052e16}
  .user-name{font-size:13px;font-weight:600}
  .user-meta{font-size:11px;color:#64748b}
  .badge{font-size:10px;padding:2px 7px;border-radius:10px;font-weight:700}
  .badge-student{background:#1e3a5f;color:#60a5fa}
  .badge-teacher{background:#3b1f5e;color:#c084fc}
  .empty-msg{font-size:13px;color:#475569;text-align:center;padding:20px}

  /* Divider */
  .divider{border:none;border-top:1px solid #2d2d44}

  /* Samples hint */
  .hint{font-size:11px;color:#475569;margin-top:2px}

  /* Progress bar */
  .progress-wrap{background:#1e1e30;border-radius:4px;overflow:hidden;height:6px;margin-top:4px}
  .progress-bar{height:6px;background:#4ade80;width:0%;transition:width .3s}

  /* Toast notifications */
  .toast-container{position:fixed;top:60px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none}
  .toast{pointer-events:auto;padding:12px 18px;border-radius:8px;font-size:13px;font-weight:600;color:#fff;box-shadow:0 4px 20px rgba(0,0,0,.4);animation:toastIn .35s ease,toastOut .4s ease 3.6s forwards;max-width:340px}
  .toast-checkin{background:linear-gradient(135deg,#059669,#047857);border-left:4px solid #4ade80}
  .toast-checkout{background:linear-gradient(135deg,#2563eb,#1d4ed8);border-left:4px solid #60a5fa}
  .toast .t-action{font-size:11px;text-transform:uppercase;letter-spacing:.8px;opacity:.85}
  .toast .t-name{font-size:15px;margin-top:2px}
  .toast .t-time{font-size:11px;opacity:.65;margin-top:2px}
  @keyframes toastIn{from{opacity:0;transform:translateX(60px)}to{opacity:1;transform:translateX(0)}}
  @keyframes toastOut{from{opacity:1}to{opacity:0;transform:translateY(-10px)}}
</style>
</head>
<body>
<div class="toast-container" id="toasts"></div>
<div class="header">
  <h1>&#128247; Pi Face Attendance</h1>
  <div class="pills">
    <div class="pill">Device: <span id="s-device">—</span></div>
    <div class="pill" id="pill-mode">Mode: <span id="s-mode">—</span></div>
    <div class="pill">Known users: <span id="s-users">—</span></div>
    <button class="mode-btn" id="btn-mode" onclick="toggleMode()">&#9654; Switch to CHECK-IN</button>
  </div>
</div>

<div class="layout">
  <div class="video-panel">
    <img src="/video_feed" alt="Live camera feed">
  </div>

  <div class="side">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('register')">&#10010; New User</div>
      <div class="tab" onclick="switchTab('enroll')">&#128100; Existing User</div>
    </div>

    <!-- Tab: Register new user + enroll -->
    <div id="tab-register" class="tab-content active">
      <div class="field">
        <label>Full Name *</label>
        <input id="r-name" type="text" placeholder="Nguyen Van A">
      </div>
      <div class="row2">
        <div class="field">
          <label>Student / Staff ID *</label>
          <input id="r-sid" type="text" placeholder="SV001">
        </div>
        <div class="field">
          <label>Role</label>
          <select id="r-role">
            <option value="student">Student</option>
            <option value="teacher">Teacher</option>
          </select>
        </div>
      </div>
      <div class="row2">
        <div class="field">
          <label>Email</label>
          <input id="r-email" type="email" placeholder="(optional)">
        </div>
        <div class="field">
          <label>Class</label>
          <input id="r-class" type="text" placeholder="(optional)">
        </div>
      </div>
      <hr class="divider">
      <div class="field">
        <label>Face Samples</label>
        <input id="r-samples" type="number" value="15" min="5" max="40">
        <span class="hint">Recommended: 15. More = better accuracy.</span>
        <div class="progress-wrap" id="r-prog-wrap" style="display:none">
          <div class="progress-bar" id="r-prog"></div>
        </div>
      </div>
      <button class="btn btn-green" id="btn-register" onclick="doRegister()">
        &#128248; Register &amp; Scan Face
      </button>
      <div id="r-result"></div>
    </div>

    <!-- Tab: Enroll existing user -->
    <div id="tab-enroll" class="tab-content">
      <div class="field">
        <label>Select User</label>
        <div class="user-list" id="user-list">
          <div class="empty-msg">Loading users…</div>
        </div>
      </div>
      <div class="field" style="display:none" id="sel-info">
        <label>Selected</label>
        <input id="e-selected-name" type="text" readonly style="color:#4ade80;cursor:default">
      </div>
      <hr class="divider">
      <div class="field">
        <label>Face Samples</label>
        <input id="e-samples" type="number" value="15" min="5" max="40">
        <div class="progress-wrap" id="e-prog-wrap" style="display:none">
          <div class="progress-bar" id="e-prog"></div>
        </div>
      </div>
      <button class="btn btn-blue" id="btn-enroll" onclick="doEnroll()">
        &#128248; Start Face Enrollment
      </button>
      <div id="e-result"></div>
    </div>
  </div>
</div>

<script>
let _selectedUserId = null;

// ── Toast notifications ──
function showToast(ev) {
  const ct = document.getElementById('toasts');
  const el = document.createElement('div');
  const isIn = ev.action === 'CHECK_IN';
  el.className = 'toast ' + (isIn ? 'toast-checkin' : 'toast-checkout');
  const icon = isIn ? '&#10004;' : '&#128682;';
  const label = isIn ? 'Check-in' : 'Check-out';
  const detail = ev.message ? ' &mdash; ' + ev.message : '';
  el.innerHTML = '<div class="t-action">' + icon + ' ' + label + '</div>'
    + '<div class="t-name">' + ev.user + '</div>'
    + '<div class="t-time">' + ev.time + detail + '</div>';
  ct.appendChild(el);
  setTimeout(function(){ el.remove(); }, 4200);
}

async function pollEvents() {
  try {
    const evts = await (await fetch('/events')).json();
    evts.forEach(showToast);
  } catch {}
}
setInterval(pollEvents, 2000);

// ── Tabs ──
function switchTab(t) {
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active', ['register','enroll'][i]===t));
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  if (t==='enroll') loadUsers();
}

// ── Mode toggle ──
async function toggleMode() {
  try {
    const d = await (await fetch('/mode', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})).json();
    updateModeUI(d.mode);
  } catch {}
}

function updateModeUI(mode) {
  const btn = document.getElementById('btn-mode');
  const pill = document.getElementById('pill-mode');
  const modeSpan = document.getElementById('s-mode');

  pill.classList.remove('mode-enrolling','mode-trace');
  btn.classList.remove('active-checkin','active-trace');

  if (mode === 'enrolling') {
    modeSpan.textContent = 'ENROLLING';
    pill.classList.add('mode-enrolling');
    btn.disabled = true;
    btn.textContent = '\u23F3 Enrolling...';
  } else if (mode === 'checkin') {
    modeSpan.textContent = 'CHECK-IN';
    btn.disabled = false;
    btn.classList.add('active-checkin');
    btn.textContent = '\u2714 CHECK-IN active — switch to TRACE';
  } else {
    modeSpan.textContent = 'TRACE';
    pill.classList.add('mode-trace');
    btn.disabled = false;
    btn.classList.add('active-trace');
    btn.textContent = '\u25B6 TRACE only — switch to CHECK-IN';
  }
}

// ── Status poll ──
async function pollStatus() {
  try {
    const d = await (await fetch('/status')).json();
    document.getElementById('s-device').textContent = d.device_id;
    document.getElementById('s-users').textContent = d.known_users;
    updateModeUI(d.mode);
  } catch {}
}
setInterval(pollStatus, 2000); pollStatus();

// ── Load user list ──
async function loadUsers() {
  const list = document.getElementById('user-list');
  list.innerHTML = '<div class="empty-msg">Loading…</div>';
  try {
    const users = await (await fetch('/users')).json();
    if (!users.length) { list.innerHTML = '<div class="empty-msg">No users found</div>'; return; }
    list.innerHTML = '';
    users.forEach(u => {
      const el = document.createElement('div');
      el.className = 'user-item';
      el.dataset.id = u.id;
      el.innerHTML = `<div><div class="user-name">${u.full_name}</div><div class="user-meta">${u.student_id}${u.class_name?' · '+u.class_name:''}</div></div><span class="badge badge-${u.role}">${u.role}</span>`;
      el.onclick = () => selectUser(u.id, u.full_name, el);
      list.appendChild(el);
    });
  } catch { list.innerHTML = '<div class="empty-msg">Failed to load users</div>'; }
}

function selectUser(id, name, el) {
  _selectedUserId = id;
  document.querySelectorAll('.user-item').forEach(e=>e.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('e-selected-name').value = name + ' (ID: ' + id + ')';
  document.getElementById('sel-info').style.display = 'flex';
}

// ── Enrollment progress animation ──
function startProgress(wrapId, barId, samples) {
  document.getElementById(wrapId).style.display = 'block';
  const bar = document.getElementById(barId);
  bar.style.width = '0%';
  let pct = 0;
  const step = 100 / (samples * 1.5);
  return setInterval(() => {
    pct = Math.min(pct + step, 92);
    bar.style.width = pct + '%';
  }, 500);
}
function finishProgress(wrapId, barId, timer) {
  clearInterval(timer);
  document.getElementById(barId).style.width = '100%';
  setTimeout(() => { document.getElementById(wrapId).style.display = 'none'; }, 1000);
}

// ── Register new user ──
async function doRegister() {
  const name    = document.getElementById('r-name').value.trim();
  const sid     = document.getElementById('r-sid').value.trim();
  const role    = document.getElementById('r-role').value;
  const email   = document.getElementById('r-email').value.trim();
  const cls     = document.getElementById('r-class').value.trim();
  const samples = parseInt(document.getElementById('r-samples').value) || 15;
  const res     = document.getElementById('r-result');
  const btn     = document.getElementById('btn-register');

  if (!name || !sid) {
    res.className='result err'; res.textContent='Full name and Student ID are required.'; return;
  }
  btn.disabled = true;
  res.className='result info'; res.textContent='Creating account…';
  const timer = startProgress('r-prog-wrap','r-prog', samples);

  try {
    const r = await fetch('/register', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({full_name:name, student_id:sid, role, email:email||null, class_name:cls||null, samples})
    });
    const d = await r.json();
    finishProgress('r-prog-wrap','r-prog', timer);
    if (d.error) {
      res.className='result err'; res.textContent=d.error;
    } else {
      const u = d.user; const e = d.enrollment;
      res.className='result ok';
      res.innerHTML = `&#10003; <strong>${u.full_name}</strong> registered (ID: ${u.id})<br>Face: ${e.success_count}/${e.total} samples saved`;
      // clear form
      ['r-name','r-sid','r-email','r-class'].forEach(id=>document.getElementById(id).value='');
    }
  } catch(err) {
    finishProgress('r-prog-wrap','r-prog', timer);
    res.className='result err'; res.textContent='Network error: ' + err.message;
  }
  btn.disabled = false;
}

// ── Enroll existing user ──
async function doEnroll() {
  const res     = document.getElementById('e-result');
  const btn     = document.getElementById('btn-enroll');
  const samples = parseInt(document.getElementById('e-samples').value) || 15;

  if (!_selectedUserId) {
    res.className='result warn'; res.textContent='Please select a user from the list first.'; return;
  }
  btn.disabled = true;
  res.className='result info'; res.textContent='Enrolling… stand in front of camera';
  const timer = startProgress('e-prog-wrap','e-prog', samples);

  try {
    const r = await fetch('/enroll', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({user_id: _selectedUserId, samples})
    });
    const d = await r.json();
    finishProgress('e-prog-wrap','e-prog', timer);
    if (d.error) {
      res.className='result err'; res.textContent=d.error;
    } else {
      res.className='result ok';
      res.innerHTML = `&#10003; Done! ${d.success_count}/${d.total} samples saved`;
    }
  } catch(err) {
    finishProgress('e-prog-wrap','e-prog', timer);
    res.className='result err'; res.textContent='Network error: ' + err.message;
  }
  btn.disabled = false;
}
</script>
</body>
</html>"""


async def api_index(request: web.Request) -> web.Response:
    return web.Response(text=_INDEX_HTML, content_type="text/html")


async def api_video_feed(request: web.Request) -> web.StreamResponse:
    boundary = "frame"
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "close",
        },
    )
    await response.prepare(request)

    while True:
        if _latest_frame:
            try:
                await response.write(
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(_latest_frame)).encode() + b"\r\n"
                    b"\r\n" + _latest_frame + b"\r\n"
                )
            except (ConnectionResetError, ConnectionAbortedError):
                break
        await asyncio.sleep(0.05)

    return response


async def api_enroll(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    user_id = body.get("user_id")
    if not user_id or not isinstance(user_id, int):
        return web.json_response({"error": "user_id (int) is required"}, status=400)

    user = await api_client.fetch_user(user_id)
    if user is None:
        return web.json_response({"error": f"User {user_id} not found"}, status=404)

    if not _enrollment_queue.empty():
        return web.json_response(
            {"error": "Another enrollment is already in progress"}, status=409,
        )

    samples = body.get("samples", ENROLL_SAMPLES)
    timeout = body.get("timeout", ENROLL_TIMEOUT)

    future = asyncio.get_event_loop().create_future()
    await _enrollment_queue.put({
        "user_id": user_id,
        "samples": samples,
        "timeout": timeout,
        "future": future,
    })

    logger.info("Enrollment queued for user %d (%s)", user_id, user["full_name"])
    result = await future

    if "error" in result:
        return web.json_response(result, status=500)
    return web.json_response(result)


async def api_register(request: web.Request) -> web.Response:
    """Create a new user on the server then immediately enroll their face."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    student_id = body.get("student_id", "").strip()
    full_name = body.get("full_name", "").strip()
    if not student_id or not full_name:
        return web.json_response(
            {"error": "student_id and full_name are required"}, status=400,
        )

    if not _enrollment_queue.empty():
        return web.json_response(
            {"error": "Another enrollment is already in progress"}, status=409,
        )

    user = await api_client.create_user(
        student_id=student_id,
        full_name=full_name,
        email=body.get("email") or None,
        class_name=body.get("class_name") or None,
        role=body.get("role", "student"),
    )
    if user is None:
        return web.json_response({"error": "Cannot reach server"}, status=503)
    if "__error__" in user:
        return web.json_response({"error": user["__error__"]}, status=409)

    user_id = user["id"]
    samples = body.get("samples", ENROLL_SAMPLES)
    timeout = body.get("timeout", ENROLL_TIMEOUT)

    future = asyncio.get_event_loop().create_future()
    await _enrollment_queue.put({
        "user_id": user_id,
        "samples": samples,
        "timeout": timeout,
        "future": future,
    })

    logger.info("Registered + queued enrollment for user %d (%s)", user_id, full_name)
    result = await future

    if "error" in result:
        return web.json_response({"user": user, "enrollment": result}, status=500)
    return web.json_response({"user": user, "enrollment": result})


async def api_users(request: web.Request) -> web.Response:
    """Proxy the server's user list to the edge UI."""
    users = await api_client.list_users()
    return web.json_response(users)


async def api_toggle_mode(request: web.Request) -> web.Response:
    global _current_mode
    try:
        body = await request.json()
        mode = body.get("mode")
    except Exception:
        mode = None

    if mode and mode in ("trace", "checkin"):
        _current_mode = mode
    else:
        _current_mode = "checkin" if _current_mode == "trace" else "trace"

    logger.info("Mode switched to: %s", _current_mode)
    return web.json_response({"mode": _current_mode})


async def api_status(request: web.Request) -> web.Response:
    enrolling = not _enrollment_queue.empty()
    if enrolling:
        mode = "enrolling"
    else:
        mode = _current_mode
    return web.json_response({
        "mode": mode,
        "device_id": DEVICE_ID,
        "location": DEVICE_LOCATION,
        "known_users": len(set(
            l["user_id"] for l in recognizer._known_labels
        )) if recognizer._known_labels else 0,
    })


async def api_events(request: web.Request) -> web.Response:
    events = list(_recent_events)
    _recent_events.clear()
    return web.json_response(events)


async def start_edge_api():
    app = web.Application()
    app.router.add_get("/", api_index)
    app.router.add_get("/video_feed", api_video_feed)
    app.router.add_post("/enroll", api_enroll)
    app.router.add_post("/register", api_register)
    app.router.add_post("/mode", api_toggle_mode)
    app.router.add_get("/users", api_users)
    app.router.add_get("/events", api_events)
    app.router.add_get("/status", api_status)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", EDGE_API_PORT)
    await site.start()
    logger.info("Edge API server started on port %d (live view: http://localhost:%d)",
                EDGE_API_PORT, EDGE_API_PORT)


async def main():
    logger.info("=== Face Attendance Edge (Pi Emulator) ===")
    logger.info("Device: %s | Location: %s", DEVICE_ID, DEVICE_LOCATION)

    await load_embeddings_from_server()
    await start_edge_api()

    retry_task = asyncio.create_task(retry_offline_events())

    await recognition_loop()

    retry_task.cancel()
    try:
        await retry_task
    except asyncio.CancelledError:
        pass

    logger.info("Edge shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
