# Face Attendance System — AIoT

A face recognition-based attendance system using Docker containers to emulate a Raspberry Pi edge device communicating with a FastAPI backend server.

## Architecture

```
┌──────────────────────────────┐
│  Edge Container (Pi Emu)     │
│  Camera → HOG Detect         │
│  → 128D Embedding            │
│  → Euclidean Match           │
│  → POST result to Server     │
│  [Offline Queue if no net]   │
└─────────────┬────────────────┘
              │ HTTP POST (JSON)
              ▼
┌──────────────────────────────┐
│  Server Container (FastAPI)  │
│  JWT Auth → Check-in/out     │
│  → PostgreSQL                │
└─────────────┬────────────────┘
              ▼
┌──────────────────────────────┐
│  PostgreSQL 16               │
└──────────────────────────────┘
```

## Prerequisites

### Option A — Run with Docker (recommended, uses demo video by default)

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.9+ (for tool scripts on host)

### Option B — Run edge locally with USB webcam (no Docker for edge)

Install dependencies in a dedicated conda/virtualenv environment:

```bash
# Create conda env (Python 3.11 recommended)
conda create -n edge python=3.11 -y
conda activate edge

# Install dlib (must use conda, pip build requires Visual C++ on Windows)
conda install -c conda-forge dlib -y

# Install remaining packages
pip install "setuptools<81"   # pkg_resources required by face_recognition_models
pip install face_recognition
pip install git+https://github.com/ageitgey/face_recognition_models
pip install aiohttp httpx opencv-python numpy python-jose[cryptography]

# Create local data folder
mkdir edge/data
```

> **Windows note**: `dlib` cannot be built by `pip` on Windows without Visual C++ Build Tools.
> Always install it via `conda install -c conda-forge dlib`.

> **setuptools note**: `setuptools >= 81` removed `pkg_resources`.
> Pin to `<81` so `face_recognition_models` can import correctly.

Run edge locally (server still runs in Docker):

```powershell
docker compose up -d postgres server

$env:SERVER_URL       = "http://localhost:8000"
$env:CAMERA_SOURCE    = "0"
$env:CAMERA_BACKEND   = "DSHOW"    # Windows only — fixes MSMF driver issues
$env:OFFLINE_QUEUE_DB = "data/offline_queue.db"
cd edge
python -m app.main
```

Open **http://localhost:8001** for the live camera view.

### Option C — Run edge in Docker WITH a real USB webcam (Camera Bridge)

Docker containers cannot access Windows USB cameras directly. The **Camera Bridge** solves this by running a lightweight MJPEG HTTP server on the host that captures the webcam and streams it at `http://<LAN-IP>:8888/stream.mjpg`. The Docker edge container reads this stream as its camera source.

```
┌───────────────────┐  MJPEG HTTP   ┌───────────────────────┐
│  USB Webcam (Host)│ ────────────► │  Edge Container       │
│  camera_bridge.py │  :8888        │  CAMERA_SOURCE=http://│
│  (conda env edge) │               │  <LAN-IP>:8888/...    │
└───────────────────┘               └───────────────────────┘
```

#### Camera Bridge endpoints

| Path | Description |
|------|-------------|
| `/stream.mjpg` | Live MJPEG video stream |
| `/health` | Health check (JSON: status, frame count, uptime) |

#### Setup (one-time)

Yêu cầu conda env `edge` đã được cài (xem Option B ở trên).

**Step 1** — Register camera bridge as Windows startup task (chạy 1 lần, cần Admin):

```powershell
.\setup_camera_autostart.ps1
```

Script này sẽ:
- Tìm Python trong conda env `edge`
- Tạo Scheduled Task `FaceAttendance-CameraBridge` chạy khi đăng nhập Windows
- Tự động start bridge ngay sau khi đăng ký
- Bridge auto-detect webcam (index -1), serve MJPEG trên port 8888

Gỡ bỏ nếu không cần:

```powershell
.\setup_camera_autostart.ps1 -Uninstall
```

**Step 2** — Verify bridge is running:

```powershell
# Health check
curl http://localhost:8888/health

# View stream in browser
# http://localhost:8888/stream.mjpg
```

#### Start hệ thống (hàng ngày)

Sau khi camera bridge đã được setup, chỉ cần chạy:

```powershell
.\start.ps1
```

Script `start.ps1` thực hiện 3 bước tự động:

| Step | Action | Detail |
|------|--------|--------|
| **1/3** | Docker Desktop check | Nếu chưa chạy → tự khởi động, đợi 30s |
| **2/3** | Camera Bridge check | Gọi `http://localhost:8888/health`. Nếu không phản hồi → start bridge bằng conda env `edge`, đợi 6s. Nếu bridge vẫn fail → cảnh báo kiểm tra webcam |
| **3/3** | Docker services | Chạy `docker compose up -d`, đợi edge log "Recognition loop started" (timeout 90s) |

Sau khi hoàn tất, script tự động:
- Cập nhật `CAMERA_SOURCE` trong `.env` với LAN IP hiện tại (để edge container truy cập bridge qua mạng)
- Mở browser tại `http://localhost:8001` (Live View)

#### Manual start (không dùng start.ps1)

```powershell
# 1. Start camera bridge (nếu chưa chạy)
conda activate edge
python camera_bridge.py --index -1 --port 8888

# 2. Update .env: CAMERA_SOURCE=http://<YOUR-LAN-IP>:8888/stream.mjpg

# 3. Start Docker stack
docker compose up -d
```

---

## Quick Start (demo video, không cần webcam)

```bash
# 1. Start database and server
docker compose up -d postgres server

# 2. Install tool dependencies (on host machine)
pip install -r tools/requirements.txt

# 3. Download a small LFW subset for Quick Start demo only (≠ canonical benchmark below: 1680 people / 9164 images)
python tools/download_lfw_sklearn.py --output ./dataset/lfw_subset --min-images 10 --max-people 15

# 4. Seed test users into the database
python tools/seed_users.py --dataset ./dataset/lfw_subset --server http://localhost:8000

# 5. Batch enroll faces (uploads images to server for embedding extraction)
python tools/batch_enroll.py --dataset ./dataset/lfw_subset --server http://localhost:8000

# 6. (Optional) Evaluate recognition accuracy
docker compose run --rm \
  -v ./dataset:/app/dataset \
  -v ./tools:/app/tools \
  --entrypoint "python /app/tools/evaluate_accuracy.py --dataset /app/dataset/lfw_subset" \
  edge

# 7. Create a test video from dataset images
python tools/create_test_video.py --dataset ./dataset/lfw_subset --output ./test_videos/classroom_demo.mp4

# 8. Start edge emulator (processes the test video)
docker compose up edge

# 9. Query attendance records
curl "http://localhost:8000/api/attendance?date=$(date +%Y-%m-%d)"
```

## Verified Results (`tools/evaluate_accuracy.py`)

**Canonical LFW benchmark scale:** **1,680 identities** and **9,164 image files** in folders that satisfy **`--min-images-per-person 2`** (raw export **`./dataset/lfw_full_raw`** via `download_lfw_sklearn.py --mode raw`; **4,069** single-image identity folders in the full tree are excluded). After an **80%/20%** per-identity train/test split: **6,562** enroll paths, **2,602** probe paths; **2,466** probe runs count toward metrics (successful single-face HOG extractions). **`seed=42`**. Edge default **`DISTANCE_THRESHOLD` = 0.5** (primary row in the table below).

| Stat | Value |
|------|-------|
| Qualifying identities | 1680 |
| Total image files in qualifying folders | 9164 |
| Image paths used for enroll (train split) | 6562 |
| Image paths held out as probes (test split) | 2602 |
| Identities in probe split | 1680 (same as qualifying; each has ≥1 probe path) |
| Probe files with a successful embedding | 2466 |
| Probe files skipped (no embedding) | 136 |

**Total tests** in the script output is **2466**, not 2602: it counts **one row per successful probe embedding** (readable image + exactly one HOG face). The remaining probe files do not produce an embedding (read failure, zero faces, or multiple faces), so they do not enter TP/FP/FN.

| Threshold | Total tests | Accuracy | Precision | Recall | F1 | TP | FP | FN |
|-----------|-------------|----------|-----------|--------|----|----|----|-----|
| **0.4** | 2466 | 60.8% | 99.7% | 60.9% | 75.6% | 1500 | 4 | 962 |
| **0.5** | 2466 | 90.2% | 98.1% | 91.8% | 94.8% | 2224 | 44 | 198 |
| **0.6** | 2466 | 93.6% | 93.6% | ~100%* | 96.7% | 2307 | 158 | 1 |

\*Recall shown as 100.0% in the run; 1 false negative out of 2466 tests.

#### Threshold notes

- **0.4:** Very strict — almost no **false positives** (4) but many **false negatives** (962): correct users often rejected as unknown. Use when wrong identity must be avoided at almost any cost.

- **0.5:** Matches default **`DISTANCE_THRESHOLD`** on Edge — good overall trade-off (~90% accuracy, ~98% precision, ~92% recall). Reasonable baseline for attendance with cooldown and multiple enrollment samples.

- **0.6:** Loose acceptance — misses almost no genuine user (FN = 1) but **false positives spike** (158 vs 44). Higher risk of matching the wrong enrolled person; only justified when misses are unacceptable and operational guardrails exist.

Lower threshold ⇒ fewer accepts (stricter matching); tune on **your** cameras and enrollments—the LFW numbers are a coarse guide only.

## API Endpoints

| Method | Endpoint                         | Auth | Description                    |
|--------|----------------------------------|------|--------------------------------|
| GET    | `/health`                        | No   | Health check                   |
| POST   | `/api/users`                     | No   | Create user                    |
| GET    | `/api/users`                     | No   | List users                     |
| POST   | `/api/enroll/upload`             | No   | Enroll face via image upload   |
| GET    | `/api/users/{id}/enrollment-status` | No | Check enrollment status      |
| POST   | `/api/attendance`                | JWT  | Record check-in/check-out     |
| GET    | `/api/attendance?date=YYYY-MM-DD`| No   | List attendance records        |
| POST   | `/api/unknown`                   | JWT  | Report unknown face            |
| GET    | `/api/embeddings/sync`           | JWT  | Sync embeddings to edge        |
| GET    | `/docs`                          | No   | Swagger UI                     |

## Services

| Service  | Port | Description                          |
|----------|------|--------------------------------------|
| postgres | 5432 | PostgreSQL 16 database               |
| server   | 8000 | FastAPI backend (REST API + Swagger) |
| edge     | 8001 | Pi emulator (live view + enrollment) |

## Tech Stack

- **Face Detection**: dlib HOG (via face_recognition)
- **Face Encoding**: dlib ResNet 128-dimensional embeddings
- **Backend**: FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16
- **Auth**: JWT HS256
- **Edge HTTP**: httpx (async)
- **Offline Queue**: SQLite (local on edge)
- **Containers**: Docker Compose

## Project Structure

```
├── docker-compose.yml
├── .env
├── server/                    # FastAPI backend
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # FastAPI entry point
│       ├── config.py          # Settings from environment
│       ├── database.py        # SQLAlchemy async engine
│       ├── models.py          # ORM models (User, Attendance, etc.)
│       ├── schemas.py         # Pydantic request/response schemas
│       ├── auth.py            # JWT verification
│       └── routers/
│           ├── users.py       # CRUD users
│           ├── attendance.py  # Check-in/out logic
│           ├── enrollment.py  # Face enrollment via image upload
│           ├── embeddings.py  # Embedding sync for edge devices
│           └── unknown.py     # Unknown face logging
├── edge/                      # Pi emulator (face recognition)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # Recognition loop
│       ├── config.py          # Edge settings
│       ├── camera.py          # Threaded video capture
│       ├── detector.py        # HOG face detection + encoding
│       ├── recognizer.py      # Euclidean distance matching
│       ├── api_client.py      # Async HTTP client with JWT
│       └── offline_queue.py   # SQLite queue for offline events
├── tools/                     # Utility scripts
│   ├── requirements.txt       # Tool dependencies
│   ├── download_lfw.py        # Download LFW dataset (direct URL)
│   ├── download_lfw_sklearn.py # Download LFW via sklearn (alternative)
│   ├── seed_users.py          # Create users from dataset directories
│   ├── batch_enroll.py        # Upload images for enrollment
│   ├── evaluate_accuracy.py   # Train/test split accuracy evaluation
│   ├── create_test_video.py   # Generate test video from images
│   └── generate_token.py      # Generate JWT token for testing
├── dataset/                   # e.g. lfw_full_raw (canonical benchmark) or lfw_subset (Quick Start demo); gitignored
└── test_videos/               # Demo videos for edge emulator
```

## Configuration

All settings are in `.env`. Key parameters:

| Variable             | Default                                   | Description                              |
|----------------------|-------------------------------------------|------------------------------------------|
| DISTANCE_THRESHOLD   | 0.5                                       | Euclidean distance threshold             |
| COOLDOWN_SECONDS     | 5                                         | Seconds between duplicate scans          |
| CAMERA_SOURCE        | /app/test_videos/classroom_demo.mp4       | Video file path, `/dev/video0`, or `0`   |
| CAMERA_BACKEND       | _(empty)_                                 | Set `DSHOW` on Windows to fix MSMF issue |
| JWT_SECRET           | (set in .env)                             | Shared secret for JWT auth               |
| DEVICE_ID            | pi_emulator_01                            | Edge device identifier                   |
| DEVICE_LOCATION      | Classroom B201                            | Physical location of camera              |

## Stopping

```bash
# Stop all containers (keep data)
docker compose down

# Stop and delete all data (reset)
docker compose down -v
```
