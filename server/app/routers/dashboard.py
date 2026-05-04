import os
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Face Attendance Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f0f14;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh;
  }
  header {
    background: #13131f;
    border-bottom: 1px solid #2d2d44;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 {
    font-size: 1.4rem;
    font-weight: 700;
    color: #e2e8f0;
    letter-spacing: 0.02em;
  }
  header h1 span { color: #3b82f6; }
  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  #clock {
    font-size: 0.85rem;
    color: #94a3b8;
    font-family: monospace;
  }
  #refresh-badge {
    font-size: 0.75rem;
    color: #4ade80;
    background: rgba(74, 222, 128, 0.1);
    border: 1px solid rgba(74, 222, 128, 0.2);
    border-radius: 999px;
    padding: 2px 10px;
  }
  .main { padding: 24px; max-width: 1400px; margin: 0 auto; }
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    border-bottom: 1px solid #2d2d44;
  }
  .tab-btn {
    padding: 10px 20px;
    background: transparent;
    border: none;
    color: #64748b;
    font-size: 0.9rem;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
    font-family: inherit;
  }
  .tab-btn:hover { color: #e2e8f0; }
  .tab-btn.active {
    color: #3b82f6;
    border-bottom-color: #3b82f6;
  }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .toolbar label { font-size: 0.85rem; color: #94a3b8; }
  input[type="date"] {
    background: #1e1e30;
    border: 1px solid #2d2d44;
    color: #e2e8f0;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    font-family: inherit;
    cursor: pointer;
  }
  input[type="date"]:focus { outline: 1px solid #3b82f6; }
  .btn {
    padding: 6px 14px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-size: 0.85rem;
    font-family: inherit;
    transition: opacity 0.15s;
  }
  .btn:hover { opacity: 0.85; }
  .btn-primary { background: #3b82f6; color: #fff; }
  .btn-danger { background: #f87171; color: #fff; }
  .stat-row {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .stat-card {
    background: #13131f;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    padding: 12px 20px;
    min-width: 140px;
  }
  .stat-card .label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .stat-card .value { font-size: 1.5rem; font-weight: 700; color: #e2e8f0; }
  .stat-card .value.green { color: #4ade80; }
  .stat-card .value.blue { color: #3b82f6; }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  thead th {
    background: #13131f;
    padding: 10px 12px;
    text-align: left;
    color: #64748b;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #2d2d44;
    white-space: nowrap;
  }
  tbody tr {
    border-bottom: 1px solid #1e1e30;
    cursor: pointer;
    transition: background 0.15s;
  }
  tbody tr:hover { background: #1e1e30; }
  td {
    padding: 10px 12px;
    color: #e2e8f0;
    vertical-align: middle;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.03em;
  }
  .badge-green { background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); }
  .badge-blue { background: rgba(59, 130, 246, 0.15); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.3); }
  .badge-gray { background: rgba(100, 116, 139, 0.15); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }
  .thumb {
    width: 36px;
    height: 36px;
    object-fit: cover;
    border-radius: 4px;
    border: 1px solid #2d2d44;
    cursor: zoom-in;
  }
  .no-photo {
    font-size: 0.75rem;
    color: #64748b;
    font-style: italic;
  }
  .table-wrap {
    background: #13131f;
    border: 1px solid #2d2d44;
    border-radius: 10px;
    overflow: hidden;
    overflow-x: auto;
  }
  .empty-msg {
    text-align: center;
    padding: 40px;
    color: #64748b;
    font-size: 0.9rem;
  }
  /* Modal */
  .modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: #13131f;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 24px;
    max-width: 700px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
  }
  .modal-header h2 { font-size: 1.1rem; color: #e2e8f0; }
  .modal-close {
    background: none;
    border: none;
    color: #64748b;
    font-size: 1.4rem;
    cursor: pointer;
    line-height: 1;
    padding: 4px;
  }
  .modal-close:hover { color: #e2e8f0; }
  .modal-photos {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 20px;
  }
  .photo-card {
    background: #0f0f14;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    overflow: hidden;
  }
  .photo-card-label {
    padding: 8px 12px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
    border-bottom: 1px solid #2d2d44;
  }
  .photo-card img {
    width: 100%;
    display: block;
    max-height: 250px;
    object-fit: cover;
  }
  .photo-card .no-photo-placeholder {
    height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #64748b;
    font-size: 0.85rem;
    font-style: italic;
  }
  .modal-details {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .detail-item .detail-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
    margin-bottom: 2px;
  }
  .detail-item .detail-value {
    font-size: 0.9rem;
    color: #e2e8f0;
  }
  .separator { height: 1px; background: #2d2d44; margin: 16px 0; }
  #loading { text-align: center; padding: 40px; color: #64748b; }
  .confidence-bar-wrap { display: flex; align-items: center; gap: 8px; }
  .confidence-bar {
    height: 6px;
    border-radius: 3px;
    background: #2d2d44;
    flex: 1;
    max-width: 60px;
    overflow: hidden;
  }
  .confidence-bar-fill { height: 100%; border-radius: 3px; background: #4ade80; }
</style>
</head>
<body>

<header>
  <h1>&#128247; Face Attendance <span>Dashboard</span></h1>
  <div class="header-right">
    <span id="clock"></span>
    <span id="refresh-badge">&#8635; Auto-refresh 10s</span>
  </div>
</header>

<div class="main">
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('attendance', this)">&#128197; Attendance</button>
    <button class="tab-btn" onclick="switchTab('users', this)">&#128101; Users</button>
  </div>

  <!-- Attendance Tab -->
  <div id="tab-attendance" class="tab-panel active">
    <div class="toolbar">
      <label for="date-picker">Date:</label>
      <input type="date" id="date-picker" />
      <button class="btn btn-primary" onclick="loadAttendance()">Refresh</button>
    </div>
    <div class="stat-row" id="stats-row"></div>
    <div class="table-wrap">
      <div id="attendance-content"><div class="empty-msg">Loading...</div></div>
    </div>
  </div>

  <!-- Users Tab -->
  <div id="tab-users" class="tab-panel">
    <div class="toolbar">
      <button class="btn btn-primary" onclick="loadUsers()">&#8635; Refresh</button>
    </div>
    <div class="table-wrap">
      <div id="users-content"><div class="empty-msg">Loading...</div></div>
    </div>
  </div>
</div>

<!-- Attendance Detail Modal -->
<div class="modal-overlay" id="modal-overlay" onclick="closeModalOnBg(event)">
  <div class="modal" id="modal">
    <div class="modal-header">
      <h2 id="modal-title">Attendance Detail</h2>
      <button class="modal-close" onclick="closeModal()">&times;</button>
    </div>
    <div id="modal-body"></div>
  </div>
</div>

<script>
  // ---- Clock ----
  function updateClock() {
    const now = new Date();
    document.getElementById('clock').textContent = now.toLocaleString();
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ---- Tab switching ----
  function switchTab(name, btn) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
    if (name === 'users') loadUsers();
  }

  // ---- Date picker default to today ----
  (function() {
    const dp = document.getElementById('date-picker');
    const today = new Date();
    const y = today.getFullYear();
    const m = String(today.getMonth() + 1).padStart(2, '0');
    const d = String(today.getDate()).padStart(2, '0');
    dp.value = y + '-' + m + '-' + d;
  })();

  // ---- Attendance ----
  let _attendanceData = [];

  async function loadAttendance() {
    const date = document.getElementById('date-picker').value;
    const url = '/api/dashboard/attendance' + (date ? '?date=' + date : '');
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      _attendanceData = await resp.json();
      renderAttendance(_attendanceData);
    } catch(e) {
      document.getElementById('attendance-content').innerHTML =
        '<div class="empty-msg">Error loading data: ' + e.message + '</div>';
    }
  }

  function formatTime(iso) {
    if (!iso) return '&#8212;';
    return new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  }

  function formatDuration(s) {
    if (s == null) return '&#8212;';
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return h + 'h ' + m + 'm ' + sec + 's';
    if (m > 0) return m + 'm ' + sec + 's';
    return sec + 's';
  }

  function renderAttendance(rows) {
    // Stats
    const total = rows.length;
    const checkins = rows.filter(r => r.check_in).length;
    const checkouts = rows.filter(r => r.check_out).length;
    document.getElementById('stats-row').innerHTML =
      '<div class="stat-card"><div class="label">Total Records</div><div class="value">' + total + '</div></div>' +
      '<div class="stat-card"><div class="label">Check-ins</div><div class="value green">' + checkins + '</div></div>' +
      '<div class="stat-card"><div class="label">Check-outs</div><div class="value blue">' + checkouts + '</div></div>';

    if (rows.length === 0) {
      document.getElementById('attendance-content').innerHTML =
        '<div class="empty-msg">No attendance records for this date.</div>';
      return;
    }

    let html = '<table><thead><tr>' +
      '<th>#</th><th>Time</th><th>User</th><th>Action</th>' +
      '<th>Confidence</th><th>Duration</th><th>Device</th><th>Photo</th>' +
      '</tr></thead><tbody>';

    rows.forEach((r, i) => {
      let action = '';
      if (r.check_in && !r.check_out) {
        action = '<span class="badge badge-green">CHECK IN</span>';
      } else if (r.check_out) {
        action = '<span class="badge badge-blue">CHECK OUT</span>';
      } else {
        action = '<span class="badge badge-gray">IGNORED</span>';
      }

      const conf = r.match_distance != null ? Math.max(0, Math.round((1 - r.match_distance) * 100)) : null;
      const confHtml = conf != null ?
        '<div class="confidence-bar-wrap"><span>' + conf + '%</span>' +
        '<div class="confidence-bar"><div class="confidence-bar-fill" style="width:' + conf + '%"></div></div></div>' :
        '&#8212;';

      const photo = r.check_in_image ?
        '<img class="thumb" src="/api/snapshots/' + r.check_in_image + '" alt="snapshot">' :
        '<span class="no-photo">No photo</span>';

      const time = formatTime(r.check_in || null);

      html += '<tr onclick="openModal(' + i + ')">' +
        '<td>' + (i + 1) + '</td>' +
        '<td style="font-family:monospace;white-space:nowrap">' + time + '</td>' +
        '<td><strong>' + escHtml(r.full_name) + '</strong><br><span style="color:#64748b;font-size:0.75rem">' + escHtml(r.student_id) + '</span></td>' +
        '<td>' + action + '</td>' +
        '<td>' + confHtml + '</td>' +
        '<td style="white-space:nowrap">' + formatDuration(r.duration) + '</td>' +
        '<td style="color:#94a3b8;font-size:0.8rem">' + escHtml(r.device_id || '') + '</td>' +
        '<td>' + photo + '</td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    document.getElementById('attendance-content').innerHTML = html;
  }

  function openModal(idx) {
    const r = _attendanceData[idx];
    if (!r) return;

    document.getElementById('modal-title').textContent = 'Attendance: ' + r.full_name;

    const checkInPhotoHtml = r.check_in_image
      ? '<img src="/api/snapshots/' + r.check_in_image + '" alt="Check-in photo">'
      : '<div class="no-photo-placeholder">No photo</div>';

    const checkOutPhotoHtml = r.check_out_image
      ? '<img src="/api/snapshots/' + r.check_out_image + '" alt="Check-out photo">'
      : '<div class="no-photo-placeholder">No photo</div>';

    const conf = r.match_distance != null ? Math.max(0, Math.round((1 - r.match_distance) * 100)) + '%' : '&#8212;';

    document.getElementById('modal-body').innerHTML =
      '<div class="modal-photos">' +
        '<div class="photo-card">' +
          '<div class="photo-card-label">&#10003; Check-in Photo</div>' +
          checkInPhotoHtml +
        '</div>' +
        '<div class="photo-card">' +
          '<div class="photo-card-label">&#10003; Check-out Photo</div>' +
          checkOutPhotoHtml +
        '</div>' +
      '</div>' +
      '<div class="separator"></div>' +
      '<div class="modal-details">' +
        detail('User', escHtml(r.full_name)) +
        detail('Student ID', escHtml(r.student_id)) +
        detail('Date', r.date) +
        detail('Shift', 'Shift ' + r.shift) +
        detail('Check-in', r.check_in ? new Date(r.check_in).toLocaleString() : '&#8212;') +
        detail('Check-out', r.check_out ? new Date(r.check_out).toLocaleString() : '&#8212;') +
        detail('Duration', formatDuration(r.duration)) +
        detail('Confidence', conf) +
        detail('Device', escHtml(r.device_id || '')) +
        detail('Status', escHtml(r.status || '')) +
      '</div>';

    document.getElementById('modal-overlay').classList.add('open');
  }

  function detail(label, value) {
    return '<div class="detail-item"><div class="detail-label">' + label + '</div><div class="detail-value">' + value + '</div></div>';
  }

  function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
  }

  function closeModalOnBg(e) {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeModal();
  });

  // ---- Users ----
  async function loadUsers() {
    try {
      const resp = await fetch('/api/users');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const users = await resp.json();
      renderUsers(users);
    } catch(e) {
      document.getElementById('users-content').innerHTML =
        '<div class="empty-msg">Error loading users: ' + e.message + '</div>';
    }
  }

  function renderUsers(users) {
    if (users.length === 0) {
      document.getElementById('users-content').innerHTML =
        '<div class="empty-msg">No users found.</div>';
      return;
    }

    let html = '<table><thead><tr>' +
      '<th>ID</th><th>Student ID</th><th>Full Name</th>' +
      '<th>Email</th><th>Class</th><th>Role</th><th>Actions</th>' +
      '</tr></thead><tbody>';

    users.forEach(u => {
      html += '<tr>' +
        '<td>' + u.id + '</td>' +
        '<td style="font-family:monospace">' + escHtml(u.student_id) + '</td>' +
        '<td><strong>' + escHtml(u.full_name) + '</strong></td>' +
        '<td style="color:#94a3b8">' + escHtml(u.email || '&#8212;') + '</td>' +
        '<td>' + escHtml(u.class_name || '&#8212;') + '</td>' +
        '<td><span class="badge badge-blue">' + escHtml(u.role) + '</span></td>' +
        '<td><button class="btn btn-danger" onclick="deleteUser(' + u.id + ', \'' + escAttr(u.full_name) + '\', event)">Delete</button></td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    document.getElementById('users-content').innerHTML = html;
  }

  async function deleteUser(userId, name, event) {
    event.stopPropagation();
    if (!confirm('Delete user "' + name + '" (ID ' + userId + ')? This will also remove all their attendance records and face embeddings.')) return;
    try {
      const resp = await fetch('/api/users/' + userId, { method: 'DELETE' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      loadUsers();
    } catch(e) {
      alert('Failed to delete user: ' + e.message);
    }
  }

  // ---- Helpers ----
  function escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escAttr(s) {
    if (s == null) return '';
    return String(s).replace(/'/g, "\\'");
  }

  // ---- Auto-refresh ----
  loadAttendance();
  setInterval(function() {
    const activeTab = document.querySelector('.tab-panel.active');
    if (activeTab && activeTab.id === 'tab-attendance') {
      loadAttendance();
    }
  }, 10000);
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page():
    return HTMLResponse(content=_DASHBOARD_HTML)


@router.get("/api/dashboard/attendance")
async def dashboard_attendance(
    date_str: Optional[str] = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
):
    from app.models import Attendance, User

    query = (
        select(Attendance, User.full_name, User.student_id)
        .join(User, Attendance.user_id == User.id)
    )
    if date_str:
        d = date_type.fromisoformat(date_str)
        query = query.where(Attendance.date == d)
    query = query.order_by(Attendance.id.desc())
    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "id": att.id,
            "user_id": att.user_id,
            "full_name": full_name,
            "student_id": student_id,
            "date": str(att.date),
            "check_in": att.check_in.isoformat() if att.check_in else None,
            "check_out": att.check_out.isoformat() if att.check_out else None,
            "duration": att.duration,
            "shift": att.shift,
            "status": att.status,
            "device_id": att.device_id,
            "match_distance": att.match_distance,
            "check_in_image": att.check_in_image,
            "check_out_image": att.check_out_image,
        }
        for att, full_name, student_id in rows
    ]


@router.get("/api/snapshots/{filename}")
async def get_snapshot(filename: str):
    filepath = os.path.join("/app/attendance_snapshots", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(filepath, media_type="image/jpeg")
