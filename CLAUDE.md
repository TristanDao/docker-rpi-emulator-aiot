# Face Attendance System — Project Context

> File này tóm tắt toàn bộ codebase để tiếp tục phát triển mà không cần đọc lại từng file.
> Cập nhật lần cuối: 2026-04-07.

---

## 1. Overview

Hệ thống điểm danh bằng nhận diện khuôn mặt theo kiến trúc AIoT (Edge-Server):

- **Edge** (Docker container giả lập Raspberry Pi): đọc camera/video → detect face (HOG) → extract 128D embedding → so khớp Euclidean → gửi kết quả lên server qua HTTP.
- **Server** (FastAPI + PostgreSQL 16): nhận kết quả → logic check-in/check-out theo shift → lưu DB → cung cấp API quản lý.
- **Offline Queue**: Edge lưu event vào SQLite khi mất kết nối, gửi lại sau.

---

## 2. Tech Stack

| Component | Technology |
|-----------|-----------|
| Face Detection | dlib HOG via `face_recognition` |
| Face Encoding | dlib ResNet → 128D float64 vector |
| Server Framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Database | PostgreSQL 16 (Docker) |
| Auth | JWT HS256 (shared secret giữa edge ↔ server) |
| Edge HTTP Client | httpx (async) |
| Edge API Server | aiohttp (enrollment trigger + status, port 8001) |
| Edge Offline | SQLite (thread-safe, file-backed queue) |
| Camera | OpenCV VideoCapture (threaded) |
| Container | Docker Compose (3 services) |

---

## 3. Project Structure

```
docker-rpi-emulator-aiot/
├── .env                          # All config vars
├── docker-compose.yml            # 3 services: postgres, server, edge
├── face_attendance_system_design.md  # Original design doc (Vietnamese)
│
├── server/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py               # FastAPI app, lifespan init_db
│       ├── config.py             # Pydantic Settings from env
│       ├── database.py           # async engine, session, init_db
│       ├── models.py             # User, FaceEmbedding, Attendance, UnknownLog
│       ├── schemas.py            # Pydantic request/response models
│       ├── auth.py               # JWT verify_token dependency
│       └── routers/
│           ├── users.py          # POST/GET /api/users
│           ├── enrollment.py     # POST /api/enroll/upload, POST /api/enroll/embedding, DELETE embeddings, GET status
│           ├── attendance.py     # POST /api/attendance (check-in/out), GET list
│           ├── embeddings.py     # GET /api/embeddings/sync (incremental)
│           └── unknown.py        # POST /api/unknown
│
├── edge/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py               # Main loop + aiohttp server (recognition, enrollment, live view)
│       ├── config.py             # Env vars + constants (thresholds, resize, etc.)
│       ├── camera.py             # Threaded VideoCapture (queue-based, auto-restart video)
│       ├── detector.py           # detect_and_encode(): HOG detect + face_encodings
│       ├── recognizer.py         # FaceRecognizer: vectorized distance match + cooldown
│       ├── annotator.py          # annotate_frame(): draw bounding boxes + labels on frame
│       ├── api_client.py         # send_attendance/unknown/enrollment, fetch_embeddings/user (JWT cached 23h)
│       ├── enroller.py           # EnrollmentSession: camera capture + quality checks for enrollment
│       ├── enroll.py             # CLI entry point: python -m app.enroll --user-id N
│       └── offline_queue.py      # SQLite queue: push/pop/retry for failed events
│
├── tools/                        # Host-side utility scripts
│   ├── requirements.txt          # requests, face-recognition, sklearn, python-jose, etc.
│   ├── download_lfw.py           # Download LFW from UMass (direct URL)
│   ├── download_lfw_sklearn.py   # Download LFW via sklearn (alternative mirror)
│   ├── seed_users.py             # Create users from dataset dir names
│   ├── batch_enroll.py           # Upload images to /api/enroll/upload
│   ├── evaluate_accuracy.py      # Train/test split → precision/recall/F1
│   ├── create_test_video.py      # Stitch dataset images into MP4 for edge
│   └── generate_token.py         # Generate JWT token for manual API testing
│
├── dataset/lfw_subset/           # Downloaded face images (gitignored)
└── test_videos/                  # Generated test videos (gitignored)
```

---

## 4. Database Schema (PostgreSQL)

### users
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| student_id | String(50) | unique, indexed |
| full_name | String(100) | |
| email | String(100) | nullable |
| class_name | String(50) | nullable |
| role | String(20) | default "student" |
| is_active | Boolean | default true |
| created_at | DateTime(tz) | |

### face_embeddings
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| user_id | FK → users.id | CASCADE delete |
| embedding | LargeBinary | 128 * 8 = 1024 bytes (float64) |
| model_type | String(20) | "face_recognition" |
| image_ref | String(255) | nullable |
| created_at | DateTime(tz) | |
| updated_at | DateTime(tz) | for incremental sync |

### attendance
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| user_id | FK → users.id | |
| date | Date | |
| check_in | DateTime(tz) | |
| check_out | DateTime(tz) | nullable until checkout |
| duration | Integer | seconds |
| shift | Integer | default 1, auto-increments per day |
| status | String(20) | "present" |
| device_id | String(50) | |
| match_distance | Float | for data drift analysis |
| UNIQUE | (user_id, date, shift) | |

### unknown_logs
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| timestamp | DateTime(tz) | |
| image_path | String(255) | nullable |
| device_id | String(50) | |
| location | String(100) | |
| note | Text | |

---

## 5. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| POST | `/api/users` | No | Create user (JSON: student_id, full_name, ...) |
| GET | `/api/users` | No | List users (optional ?student_id=) |
| GET | `/api/users/{id}` | No | Get single user |
| POST | `/api/enroll/upload?user_id=N` | No | Upload images → extract embeddings → save |
| POST | `/api/enroll/embedding` | No | Receive base64 embeddings from edge → save |
| GET | `/api/users/{id}/enrollment-status` | No | Check enrolled count |
| DELETE | `/api/users/{id}/embeddings` | No | Reset enrollment |
| POST | `/api/attendance` | JWT | Record check-in or check-out |
| GET | `/api/attendance?date=YYYY-MM-DD` | No | List attendance records |
| POST | `/api/unknown` | JWT | Log unknown face event |
| GET | `/api/embeddings/sync` | JWT | Fetch all/incremental embeddings |
| GET | `/docs` | No | Swagger UI |

---

## 6. Edge Recognition Pipeline

```
main.py::main()
  ├── load_embeddings_from_server()     # GET /api/embeddings/sync → load into FaceRecognizer
  ├── start_edge_api()                  # aiohttp server on port 8001 (enrollment trigger + status)
  ├── asyncio.create_task(retry_offline_events())  # background: retry queued events every 30s
  └── recognition_loop()
        ├── CameraStream.start()        # threaded VideoCapture, queue maxsize=2
        └── while running:
              # check _enrollment_queue → if enrollment request:
              #   stop camera → run EnrollmentSession → send to server → reload embeddings → restart camera
              frame = camera.read()
              if frame_count % 4 != 0: skip
              faces = detect_and_encode(frame)     # resize 0.5x → HOG → face_encodings
              for face_loc, encoding in faces:
                match = recognizer.recognize(encoding)  # vectorized euclidean, threshold 0.5
                if match and not cooldown:
                  → api_client.send_attendance(...)
                  → fallback: offline_queue.push("attendance", payload)
                else if no match:
                  → api_client.send_unknown(...)
                  → fallback: offline_queue.push("unknown", payload)
```

### Edge API (port 8001)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Live View dashboard (HTML page with video stream + enrollment form) |
| GET | `/video_feed` | MJPEG stream — live camera with bounding boxes + labels |
| POST | `/enroll` | Trigger face enrollment `{"user_id": 5, "samples": 15, "timeout": 60}` |
| GET | `/status` | Edge status: mode (recognition/enrolling), device info, known users |

Live View: mở `http://localhost:8001/` trên browser để xem camera Pi realtime. Bounding box xanh = known (kèm tên + confidence), đỏ = unknown. Overlay hiển thị device info + mode + timestamp.

Enrollment via API: recognition loop tự động pause, camera chuyển sang enrollment mode, capture xong gửi embedding lên server, reload embeddings, rồi resume recognition.

### Alternative: CLI enrollment

```
docker compose exec edge python -m app.enroll --user-id N [--samples 15] [--timeout 60]
```

---

## 7. Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| DB location | Server (PostgreSQL) | Centralized, multi-device support |
| Detection model | HOG (not CNN) | ~5x faster on Pi, sufficient accuracy |
| Embedding storage | BLOB in DB | No file dependency, easy sync |
| Pi → Server data | JSON only (no images) | Bandwidth + privacy |
| Offline handling | SQLite queue on edge | Persistent, survives restarts |
| Auth | JWT HS256 shared secret | Simple, sufficient for IoT |
| Timezone | All DateTime(timezone=True) | Consistent across edge/server |
| Cooldown | 5s in-memory dict (both edge + server) | Prevent duplicate scans |

---

## 8. Verified Test Results (LFW dataset, 15 people)

| Metric | Value |
|--------|-------|
| Dataset | 405 images, 15 people |
| Enrolled | 378/405 (93%) — 27 rejected (0 or 2+ faces) |
| **Accuracy** | **98.7%** |
| **Precision** | **100.0%** |
| **Recall** | **98.7%** |
| **F1 Score** | **99.4%** |
| False Positive | 0 |
| False Negative | 1 |
| Edge E2E | 10/10 people recognized, all HTTP 200 OK |
| Attendance records | 69 records written to PostgreSQL |

---

## 9. How to Run (Full Pipeline)

```bash
# 1. Start infrastructure
docker compose up -d postgres server

# 2. Install host tools (needs dlib → use conda on Windows, or run in Docker)
pip install -r tools/requirements.txt

# 3. Download dataset
python tools/download_lfw_sklearn.py --output ./dataset/lfw_subset --min-images 10 --max-people 15

# 4. Seed users
python tools/seed_users.py --dataset ./dataset/lfw_subset --server http://localhost:8000

# 5. Batch enroll
python tools/batch_enroll.py --dataset ./dataset/lfw_subset --server http://localhost:8000

# 6. Create test video
python tools/create_test_video.py

# 7. Run edge
docker compose up edge

# 8. Query results
curl "http://localhost:8000/api/attendance?date=2026-04-06"
```

---

## 10. Known Gaps / TODO

| Item | Status | Notes |
|------|--------|-------|
| Register user + image in 1 API call | Not implemented | Currently 2 separate calls: POST /api/users → POST /api/enroll/upload |
| Liveness detection (blink/EAR) | Design only | Described in design doc section 8.4, not coded |
| Dashboard / Web UI | **Implemented** | Live View at `http://localhost:8001/` (MJPEG stream + enrollment form) |
| Enrollment via live camera | **Implemented** | API: `POST http://localhost:8001/enroll` or CLI: `python -m app.enroll --user-id N` |
| Multi-worker cooldown | In-memory only | Would need Redis for multi-process |
| GET /api/attendance auth | None | Intentional for now (dashboard access) |
| POST /api/enroll auth | None | Admin-only endpoints, no JWT required |
| Data drift alerting | Logged only | match_distance saved but no automated alert |
| Incremental sync on edge | Full sync only | Edge always fetches all embeddings at startup |

---

## 11. Environment Variables (.env)

```
POSTGRES_USER=attendance
POSTGRES_PASSWORD=attendance_secret
POSTGRES_DB=face_attendance
DATABASE_URL=postgresql+asyncpg://attendance:attendance_secret@postgres:5432/face_attendance
JWT_SECRET=aiot-face-attendance-jwt-secret-2025
JWT_ALGORITHM=HS256
DISTANCE_THRESHOLD=0.5
COOLDOWN_SECONDS=5
DEVICE_ID=pi_emulator_01
DEVICE_LOCATION=Classroom B201
CAMERA_SOURCE=/app/test_videos/classroom_demo.mp4
SERVER_URL=http://server:8000
```

---

## 12. Bugs Fixed During Development

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `student_id` too long | VARCHAR(20) for "Arnold_Schwarzenegger" (21 chars) | Changed to VARCHAR(50) |
| `timestamp.isoformat()` on string | main.py already converted to ISO string before passing | Changed api_client type hint to `str` |
| Timezone naive/aware conflict | Edge sends UTC datetime, DB used TIMESTAMP WITHOUT TIME ZONE | Changed all columns to `DateTime(timezone=True)` |
| JWT token cached forever | Token expires in 24h but cache never invalidated | Added expiration check (refresh after 23h) |
| Parameter shadow in attendance.py | `date` param shadowed `datetime.date` import | Renamed to `date_str` with `Query(alias="date")` |
