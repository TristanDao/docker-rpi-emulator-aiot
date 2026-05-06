# Tổng quan Hệ thống Face Attendance AIoT

> Tài liệu tổng quan dành cho team. Chi tiết kỹ thuật: xem [CLAUDE.md](../CLAUDE.md).
> Cập nhật: 2026-04-30.

---

## 1. Giới thiệu

Hệ thống điểm danh tự động bằng nhận diện khuôn mặt, xây dựng theo kiến trúc AIoT (Edge-Server). Thiết bị Edge (giả lập Raspberry Pi chạy trong Docker) đọc camera, phát hiện và nhận diện khuôn mặt, rồi gửi kết quả về Server qua HTTP. Server (FastAPI + PostgreSQL) xử lý logic điểm danh và cung cấp API quản lý. Hệ thống hỗ trợ hoạt động offline — Edge lưu sự kiện vào hàng đợi SQLite khi mất kết nối và gửi lại tự động.

---

## 2. Kiến trúc hệ thống

```
┌─────────────────┐    HTTP/JSON     ┌──────────────────┐     SQL      ┌──────────────┐
│   Edge (Pi)     │ ─────────────→  │  Server (FastAPI) │ ──────────→ │ PostgreSQL 16│
│                 │                  │                   │             │              │
│ • Camera        │ ← embeddings ── │ • REST API        │             │ • users      │
│ • Face Detect   │      sync       │ • Auth (JWT)      │             │ • embeddings │
│ • Recognition   │                 │ • Business Logic  │             │ • attendance │
│ • Offline Queue │                 │                   │             │ • unknown    │
│ • Live View UI  │                 │                   │             │              │
└─────────────────┘                 └──────────────────┘             └──────────────┘
     Port 8001                           Port 8000                      Port 5432
```

3 Docker services: `postgres`, `server`, `edge`. Edge phụ thuộc server healthy; server phụ thuộc postgres healthy.

---

## 3. Tech Stack

| Component | Technology |
|-----------|------------|
| Face Detection | dlib HOG via `face_recognition` |
| Face Encoding | dlib ResNet — 128D float64 vector |
| Server Framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Database | PostgreSQL 16 (Docker) |
| Auth | JWT HS256 (shared secret edge — server) |
| Edge HTTP Client | httpx (async) |
| Edge API Server | aiohttp (port 8001) |
| Edge Offline | SQLite (thread-safe, file-backed queue) |
| Camera | OpenCV VideoCapture (threaded) |

---

## 4. Luồng dữ liệu (Data Flow)

1. Camera đọc frame — Edge xử lý mỗi frame thứ 4 (bỏ qua 3/4 để tiết kiệm CPU).
2. HOG detect khuôn mặt trên frame đã resize 0.5x.
3. dlib ResNet trích xuất embedding 128D (float64).
4. So khớp Euclidean với danh sách embedding đã đồng bộ từ server (ngưỡng 0.5).
5. Nếu khớp (known face): POST `/api/attendance` — server xử lý check-in/check-out theo ca (shift).
6. Nếu không khớp (unknown face): POST `/api/unknown` — server lưu log.
7. Nếu server không phản hồi: push vào SQLite offline queue — retry mỗi 30 giây.
8. Server: lưu bản ghi điểm danh vào PostgreSQL, tự động tăng shift nếu cùng ngày.
9. Edge đồng bộ lại embedding khi có yêu cầu enroll mới.

---

## 5. API tóm tắt

### Users

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/api/users` | Không | Tạo user mới |
| GET | `/api/users` | Không | Danh sách user (lọc theo `?student_id=`) |
| GET | `/api/users/{id}` | Không | Thông tin user |

### Enrollment

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/api/enroll/upload?user_id=N` | Không | Upload ảnh — trích embedding — lưu DB |
| POST | `/api/enroll/embedding` | Không | Nhận embedding base64 từ Edge |
| GET | `/api/users/{id}/enrollment-status` | Không | Số embedding đã enroll |
| DELETE | `/api/users/{id}/embeddings` | Không | Xóa toàn bộ embedding |

### Attendance & System

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/api/attendance` | JWT | Ghi check-in / check-out |
| GET | `/api/attendance?date=YYYY-MM-DD` | Không | Danh sách điểm danh theo ngày |
| POST | `/api/unknown` | JWT | Ghi log khuôn mặt lạ |
| GET | `/api/embeddings/sync` | JWT | Lấy embedding (full hoặc incremental) |
| GET | `/health` | Không | Health check |
| GET | `/docs` | Không | Swagger UI |

### Edge API (port 8001)

| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/` | Live View — stream camera + form enroll |
| GET | `/video_feed` | MJPEG stream với bounding box + label |
| POST | `/enroll` | Kích hoạt enroll `{"user_id": 5, "samples": 15}` |
| POST | `/register` | Tạo user mới + enroll face trong 1 bước |
| POST | `/mode` | Chuyển mode: trace / checkin |
| POST | `/algorithm` | Chuyển thuật toán detection: `{"detection": "hog"\|"haar"}` |
| GET | `/status` | Trạng thái Edge (mode, detection, device info, số user) |
| GET | `/users` | Proxy danh sách user từ server |
| GET | `/events` | Lấy sự kiện check-in/check-out gần nhất |
| POST | `/delete_user` | Xóa user và reload embeddings |

---

## 6. Database Schema

**users** — thông tin sinh viên/nhân viên: `student_id` (unique), `full_name`, `email`, `class_name`, `role`, `is_active`.

**face_embeddings** — vector khuôn mặt: FK đến `users`, `embedding` (1024 bytes BLOB), `updated_at` dùng cho incremental sync.

**attendance** — bản ghi điểm danh: `check_in`, `check_out`, `duration` (giây), `shift` (ca trong ngày), `match_distance`. Unique constraint: `(user_id, date, shift)`.

**unknown_logs** — log khuôn mặt không nhận diện được: `timestamp`, `device_id`, `location`, `note`.

---

## 7. Triển khai (Deployment)

```bash
# Khởi động toàn bộ hệ thống
docker compose up -d

# Truy cập
# Server API docs:  http://localhost:8000/docs
# Live View (Edge): http://localhost:8001/
```

Cấu hình qua file `.env` ở thư mục gốc. Các biến quan trọng:

| Biến | Mô tả |
|------|-------|
| `DATABASE_URL` | Chuỗi kết nối PostgreSQL |
| `JWT_SECRET` | Secret dùng ký JWT giữa edge và server |
| `CAMERA_SOURCE` | Đường dẫn file video hoặc index camera (0, 1, ...) |
| `DISTANCE_THRESHOLD` | Ngưỡng khớp Euclidean (mặc định: 0.5) |
| `COOLDOWN_SECONDS` | Thời gian chờ giữa hai lần điểm danh cùng người (mặc định: 5) |

---

## 8. Kết quả benchmark (chuẩn hóa)

**Quy mô báo cáo:** **`tools/evaluate_accuracy.py`**, dataset **`./dataset/lfw_full_raw`** (`download_lfw_sklearn.py --mode raw`, export đầy đủ), filter **`--min-images-per-person 2`** → **1680 người (identity)**, **9164 ảnh** trong các thư mục đủ điều kiện; **4069** thư mục chỉ 1 ảnh bị loại. Chia train/test **80%/20%** theo từng người (`train_ratio=0.8`, `seed=42`): **6562** đường dẫn ảnh enroll, **2602** ảnh probe; **2466** lần đánh giá có embedding probe hợp lệ (**Total tests**, HOG + đúng 1 mặt).

| Chỉ số (threshold **0.5**, **2466** probe embeddings; **1680** người · **9164** ảnh qualifying) | Giá trị |
|--------|--------|
| Accuracy | 90.2% |
| Precision | 98.1% |
| Recall | 91.8% |
| F1 | 94.8% |
| TP / FP / FN | 2224 / 44 / 198 |

So sánh ngưỡng Euclidean (cùng quy mô trên):

| Threshold | Accuracy | Precision | Recall | F1 | TP | FP | FN |
|-----------|----------|-----------|--------|----|----|----|-----|
| **0.4** | 60.8% | 99.7% | 60.9% | 75.6% | 1500 | 4 | 962 |
| **0.5** | 90.2% | 98.1% | 91.8% | 94.8% | 2224 | 44 | 198 |
| **0.6** | 93.6% | 93.6% | ~100% | 96.7% | 2307 | 158 | 1 |

**Nhận xét:** 0.4 lọc gắt; **0.5** khớp `DISTANCE_THRESHOLD` mặc định trên Edge; 0.6 lỏng (ít FN, FP tăng). Nên hiệu chỉnh trên dữ liệu camera thật.
