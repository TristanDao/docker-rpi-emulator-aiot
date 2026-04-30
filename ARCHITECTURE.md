# System Architecture — Face Attendance AIoT

## Overview

This system emulates an AIoT deployment where a **Raspberry Pi** (edge device) performs real-time face recognition from a USB webcam and syncs attendance records to a central **backend server**.

On a developer's machine (Windows or Mac), the entire stack runs locally:
- The **Edge** (Pi emulator) and **Server** run as Docker containers
- The **webcam** is bridged to Docker via a lightweight Python HTTP stream (`camera_bridge.py`)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     HOST MACHINE (Windows / Mac)                    │
│                                                                     │
│   ┌──────────────┐        MJPEG stream          ┌───────────────┐  │
│   │  USB Webcam  │──── cv2.VideoCapture ────────▶│ camera_bridge │  │
│   └──────────────┘                               │ :8888/stream  │  │
│                                                  └───────┬───────┘  │
│                                                          │ HTTP     │
│  ┌───────────────────────────────────────────────────────┼───────┐  │
│  │                   DOCKER COMPOSE                      │       │  │
│  │                                                       ▼       │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                  edge  :8001                            │  │  │
│  │  │                                                         │  │  │
│  │  │   CameraStream ──▶ detect_and_encode ──▶ FaceRecognizer │  │  │
│  │  │        │                                      │         │  │  │
│  │  │        │ annotate_frame (PIL Unicode)          │         │  │  │
│  │  │        ▼                                      ▼         │  │  │
│  │  │   MJPEG /video_feed              attendance / unknown   │  │  │
│  │  │        │                                      │         │  │  │
│  │  │        ▼                                      ▼         │  │  │
│  │  │   Browser UI                        OfflineQueue (SQLite)│  │  │
│  │  │   ├── Live camera view                        │         │  │  │
│  │  │   ├── New User registration                   │ retry   │  │  │
│  │  │   └── Existing User enrollment                │         │  │  │
│  │  └──────────────────────────────────┬────────────┘         │  │  │
│  │                                     │ HTTP REST API         │  │  │
│  │  ┌──────────────────────────────────▼──────────────────┐   │  │  │
│  │  │                  server  :8000                       │   │  │  │
│  │  │                                                      │   │  │  │
│  │  │   FastAPI                                            │   │  │  │
│  │  │   ├── POST /api/users              (register user)    │   │  │  │
│  │  │   ├── GET  /api/users              (list users)      │   │  │  │
│  │  │   ├── POST /api/enroll/upload      (enroll images)   │   │  │  │
│  │  │   ├── POST /api/enroll/embedding   (enroll from edge)│   │  │  │
│  │  │   ├── GET  /api/embeddings/sync    (sync to edge)    │   │  │  │
│  │  │   ├── POST /api/attendance         (log attendance)  │   │  │  │
│  │  │   ├── POST /api/unknown            (log unknown)     │   │  │  │
│  │  │   └── GET  /docs                   (Swagger UI)      │   │  │  │
│  │  └──────────────────────────────────┬───────────────────┘   │  │  │
│  │                                     │ SQLAlchemy async       │  │  │
│  │  ┌──────────────────────────────────▼──────────────────┐   │  │  │
│  │  │              postgres  :5432                         │   │  │  │
│  │  │   Tables: users, face_embeddings,                    │   │  │  │
│  │  │           attendance, unknown_logs                   │   │  │  │
│  │  └──────────────────────────────────────────────────────┘   │  │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

Browser:  http://localhost:8001  →  Live view + Enrollment UI
          http://localhost:8000/docs  →  Server Swagger UI
```

---

## Component Details

### 1. `camera_bridge.py` — Host process

| Property | Value |
|----------|-------|
| Language | Python 3.x |
| Runs on | Host OS (Windows / Mac) |
| Camera backend | Windows: `cv2.CAP_DSHOW`, Mac: `cv2.CAP_AVFOUNDATION` (auto-detected) |
| Output | MJPEG HTTP stream at `:8888/stream.mjpg` |
| Health endpoint | `GET :8888/health` → JSON `{status, frames, uptime_s}` |
| Auto-detection | Scans camera indexes 0–9 to find first working device |

**Why needed**: Docker containers cannot directly access USB devices on Windows/Mac without complex kernel driver passthrough. The bridge runs natively on the host, captures the webcam, and exposes it as a simple HTTP stream that any container can consume.

---

### 2. `edge` Docker container — Pi Emulator

| Property | Value |
|----------|-------|
| Base image | `python:3.11-slim` |
| Port | `8001` |
| Camera input | `CAMERA_SOURCE` env var (MJPEG URL or file path) |
| Reconnect | Auto-reconnects HTTP stream if bridge restarts |
| Face library | `face_recognition` (dlib HOG + OpenCV Haar cascade) |
| Text rendering | PIL / Pillow (full Unicode / Vietnamese support) |
| Offline mode | SQLite queue retries attendance when server unreachable |
| UI | Embedded aiohttp web server serving HTML + MJPEG |

**Key modules:**

```
edge/app/
├── main.py          # Entry point: recognition loop + aiohttp API
├── camera.py        # CameraStream — threaded OpenCV capture + auto-reconnect
├── detector.py      # detect_and_encode — find faces, extract 128-d embeddings
├── recognizer.py    # FaceRecognizer — Euclidean distance matching with cooldown
├── enroller.py      # EnrollmentSession — capture N face samples from camera
├── annotator.py     # annotate_frame — draw bounding boxes + PIL Unicode text
├── api_client.py    # httpx async client for server REST API
├── offline_queue.py # SQLite-backed retry queue for offline events
└── config.py        # All config from environment variables
```

**Edge API Endpoints (port 8001):**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Live View dashboard (HTML + MJPEG stream) |
| GET | `/video_feed` | Raw MJPEG stream with bounding boxes |
| POST | `/register` | Create user on server + enroll face in one step |
| POST | `/enroll` | Enroll face for existing user |
| POST | `/mode` | Toggle TRACE ↔ CHECK-IN mode |
| POST | `/algorithm` | Switch detection method (HOG / Haar) |
| GET | `/users` | Proxy server user list to UI |
| GET | `/status` | Device info, mode, known users, detection method |
| GET | `/events` | Poll recent attendance events (for toast notifications) |
| POST | `/delete_user` | Delete user + reload embeddings |

---

### 3. `server` Docker container — Backend

| Property | Value |
|----------|-------|
| Framework | FastAPI + SQLAlchemy async |
| Port | `8000` |
| Database | PostgreSQL 16 |
| Auth | JWT Bearer token |
| Image storage | Volume-mounted `unknown_images/` |

**Key routers:**

```
server/app/routers/
├── users.py       # CRUD users
├── enrollment.py  # Upload images / receive embeddings from edge
├── embeddings.py  # Incremental sync embeddings to edge devices
├── attendance.py  # Check-in/out logic + attendance list
├── unknown.py     # Log unrecognized face captures
└── dashboard.py   # Server-side attendance dashboard UI
```

---

### 4. `postgres` Docker container

| Property | Value |
|----------|-------|
| Image | `postgres:16-alpine` |
| Port | `5432` (internal) |
| Volume | `pgdata` (persistent) |
| Tables | `users`, `face_embeddings`, `attendance`, `unknown_logs` |

---

## Data Flow

### Recognition Flow
```
Webcam
  │ USB
  ▼
camera_bridge.py  ──MJPEG HTTP──▶  CameraStream (edge)
                                        │
                                   detect_and_encode()
                                        │ 128-d face embedding
                                        ▼
                                   FaceRecognizer.recognize()
                                        │ match / unknown
                                        ▼
                              api_client.send_attendance()
                                        │ POST /api/attendance
                                        ▼
                                   server → postgres
```

### Enrollment Flow
```
Browser  ──POST /register──▶  edge API
                                  │
                             create_user()  ──▶  server  ──▶  postgres
                                  │
                             EnrollmentSession.capture()
                                  │ N frames from camera
                             detect_and_encode() × N
                                  │
                             api_client.send_enrollment()
                                  │ POST /api/enroll/embedding
                                  ▼
                             server → postgres
                                  │
                             reload embeddings into recognizer
```

### Offline Queue Flow
```
edge  ──POST /api/attendance──▶  [server unreachable]
         │
         ▼
  OfflineQueue (SQLite: /app/data/offline.db)
         │
  background task retries every 30s
         │
  server back online  ──▶  flush queue  ──▶  server
```

---

## Network Map

```
Host ports exposed:
  :5432  →  postgres  (host-exposed, dùng cho psql/pgAdmin)
  :8000  →  server    (REST API + Swagger)
  :8001  →  edge      (Live view + Enrollment UI)
  :8888  →  camera_bridge  (MJPEG stream, host process)

Docker internal network:
  edge   → server:8000   (REST API calls)
  server → postgres:5432 (database)

edge → host:8888:
  Windows: via LAN IP (e.g. 192.168.x.x:8888) — auto-updated by start.ps1
  Mac:     via host.docker.internal:8888        — works natively in Docker Desktop
```

---

## Environment Variables (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_USER` | DB username | `attendance` |
| `POSTGRES_PASSWORD` | DB password | `attendance_secret` |
| `POSTGRES_DB` | DB name | `face_attendance` |
| `DATABASE_URL` | Async SQLAlchemy URL | `postgresql+asyncpg://...` |
| `JWT_SECRET` | Token signing secret | `aiot-face-attendance-...` |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `DISTANCE_THRESHOLD` | Face match threshold (0–1) | `0.5` |
| `COOLDOWN_SECONDS` | Min seconds between attendance logs | `5` |
| `DEVICE_ID` | Edge device identifier | `pi_emulator_01` |
| `DEVICE_LOCATION` | Physical location label | `Classroom B201` |
| `CAMERA_SOURCE` | MJPEG URL or video file path | `http://host.docker.internal:8888/stream.mjpg` |
| `SERVER_URL` | Backend URL (from inside Docker) | `http://server:8000` |

---

## Prerequisites

### All platforms
- Docker Desktop (with Compose)
- Python 3.9+ with `opencv-python` and `numpy` (for `camera_bridge.py`)
  - Recommended: Conda env named `edge` (`conda env create -f environment.yml`)

### Windows-specific
- Conda environment: `edge`
- `start.ps1` — auto-starts `camera_bridge.py` and Docker services
- Optional autostart: run `setup_autostart_RUNAS_ADMIN.ps1` as Administrator

### Mac-specific
- Conda or system Python with OpenCV
- `start.sh` — equivalent to `start.ps1`
- `host.docker.internal` works out-of-the-box in Docker Desktop for Mac
- Camera bridge uses `cv2.CAP_AVFOUNDATION` (default on macOS)

---

## Quick Start

```bash
# Windows
.\start.ps1

# Mac / Linux
chmod +x start.sh && ./start.sh
```

After startup:
- **Live View + Enrollment**: http://localhost:8001
- **Server API Docs**: http://localhost:8000/docs
