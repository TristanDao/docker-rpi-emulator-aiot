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

# 3. Download LFW dataset subset (15 people, ~400 images)
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

## Dataset (LFW — Labeled Faces in the Wild)

Hệ thống sử dụng LFW dataset để test và benchmark. Có 2 script download:

### Cách 1: via sklearn (khuyên dùng)

```bash
# Demo nhỏ (15 người, ~400 ảnh) — đủ để test pipeline
python tools/download_lfw_sklearn.py --output ./dataset/lfw_subset --min-images 10 --max-people 15

# Benchmark đầy đủ (50 người, ~2000 ảnh) — dùng cho báo cáo so sánh thuật toán
python tools/download_lfw_sklearn.py --output ./dataset/lfw_subset --min-images 10 --max-people 50
```

### Cách 2: direct URL từ UMass

```bash
python tools/download_lfw.py --output ./dataset/lfw_subset --min-images 10 --max-people 50
```

> **Lưu ý**: Cách 2 download từ `vis-www.cs.umass.edu` — có thể bị DNS/firewall chặn. Ưu tiên dùng cách 1.

### Sau khi download

```bash
# Tạo user từ tên thư mục dataset
python tools/seed_users.py --dataset ./dataset/lfw_subset --server http://localhost:8000

# Enroll toàn bộ ảnh
python tools/batch_enroll.py --dataset ./dataset/lfw_subset --server http://localhost:8000
```

### Benchmark so sánh thuật toán

```bash
# Chạy benchmark 4 tổ hợp (HOG/Haar × ResNet/LBPH), xuất markdown report
python tools/benchmark_algorithms.py --dataset ./dataset/lfw_subset --output ./tools/benchmark_results.md
```

Kết quả benchmark chi tiết xem tại [`tools/benchmark_results.md`](tools/benchmark_results.md).

## Verified Results — HOG + ResNet (LFW, 50 people, 2012 images)

| Metric         | Value   |
|----------------|---------|
| **Accuracy**   | 99.5%   |
| **Precision**  | 100.0%  |
| **Recall**     | 99.5%   |
| **F1 Score**   | 99.7%   |
| Detection Rate | 93.5% (HOG) |
| Speed          | 33.9 ms/frame |

### Confusion Matrix (HOG + ResNet)

| Actual \ Predicted | Known | Unknown |
|--------------------|-------|---------|
| **Known** | TP = 99.5% | FN = 0.5% |
| **Unknown** | FP = 0% | TN = N/A |

- **Precision (Known)** = 100% — không có trường hợp nhận sai người (FP = 0)
- **Recall (Known)** = 99.5% — chỉ 0.5% người đã enroll không được nhận ra
- **Accuracy** = 99.5%

> **Ghi chú:** TN (True Negative) = N/A vì test set LFW chỉ chứa người đã enroll, không có ảnh unknown. FP = 0 được tính từ các trường hợp nhận sai danh tính (gán nhầm người A thành người B).

### So sánh 4 tổ hợp thuật toán

| Tổ hợp | Accuracy | Precision | Recall | F1 Score | Speed (ms) |
|--------|----------|-----------|--------|----------|------------|
| **HOG + ResNet** (baseline) | **99.5%** | **100.0%** | **99.5%** | **99.7%** | **33.9** |
| HOG + LBPH | 65.3% | 65.3% | 100.0% | 79.0% | 104.1 |
| Haar + ResNet | 96.5% | 99.3% | 97.2% | 98.2% | 42.7 |
| Haar + LBPH | 81.7% | 81.7% | 100.0% | 89.9% | 40.5 |

> Dataset: LFW subset, 80/20 train/test split (seed=42). Chi tiết: [`tools/benchmark_results.md`](tools/benchmark_results.md)

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
├── dataset/                   # Face images (LFW subset)
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
