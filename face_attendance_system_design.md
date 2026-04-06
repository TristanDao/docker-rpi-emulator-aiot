# Thiết Kế Chi Tiết Hệ Thống Điểm Danh Nhận Diện Khuôn Mặt (AIoT)

---

## 1. Logic Check-in / Check-out

### 1.1 Nguyên tắc xác định Check-in hay Check-out

Hệ thống sử dụng **trạng thái cuối cùng** (last known state) của mỗi người dùng trong ngày để quyết định hành động tiếp theo:

- Nếu người dùng **chưa có bản ghi nào** trong ngày → đây là **Check-in**
- Nếu người dùng **đã Check-in** nhưng chưa Check-out → đây là **Check-out**
- Nếu người dùng **đã Check-out** → có thể xem là Check-in lần 2 (ca làm thứ 2) hoặc bỏ qua tùy chính sách

Thời gian cooldown (ví dụ 5 phút) được áp dụng để tránh ghi trùng khi khuôn mặt xuất hiện liên tiếp trước camera.

---

### 1.2 Xử lý các trường hợp đặc biệt

| Trường hợp | Xử lý |
|---|---|
| Người chưa check-in | Ghi nhận Check-in, lưu timestamp |
| Người đã check-in, chưa check-out | Ghi nhận Check-out, tính thời gian làm việc |
| Nhận diện lại trong vòng cooldown | Bỏ qua, không ghi thêm |
| Người đã check-out, xuất hiện lại | Ghi Check-in mới (ca 2) hoặc cảnh báo tùy config |
| Nhận diện liên tiếp cùng khuôn mặt | Chỉ ghi 1 lần, chặn bằng `last_seen_time` |

---

### 1.3 Pseudo-code Logic Check-in / Check-out

```
FUNCTION handle_attendance(user_id, current_time):

    # Bước 1: Kiểm tra cooldown (chống ghi trùng)
    last_seen = get_last_seen_time(user_id)
    IF last_seen IS NOT NULL AND (current_time - last_seen) < COOLDOWN_SECONDS:
        RETURN "IGNORED - Cooldown active"

    # Bước 2: Cập nhật thời gian nhìn thấy gần nhất
    update_last_seen(user_id, current_time)

    # Bước 3: Tìm bản ghi attendance hôm nay
    today = get_date(current_time)
    record = get_attendance_today(user_id, today)

    # Bước 4: Chưa có bản ghi → CHECK-IN
    IF record IS NULL:
        insert_attendance(
            user_id   = user_id,
            date      = today,
            check_in  = current_time,
            check_out = NULL,
            status    = "present"
        )
        RETURN "CHECK-IN recorded"

    # Bước 5: Đã check-in nhưng chưa check-out → CHECK-OUT
    ELSE IF record.check_out IS NULL:
        duration = current_time - record.check_in
        update_attendance(
            record_id  = record.id,
            check_out  = current_time,
            duration   = duration
        )
        RETURN "CHECK-OUT recorded, duration = " + duration

    # Bước 6: Đã check-out rồi → ca làm thứ 2 hoặc bỏ qua
    ELSE:
        IF ALLOW_MULTI_SHIFT:
            insert_attendance(
                user_id   = user_id,
                date      = today,
                check_in  = current_time,
                check_out = NULL,
                status    = "shift_2"
            )
            RETURN "CHECK-IN (shift 2) recorded"
        ELSE:
            log_event("User already completed attendance today", user_id)
            RETURN "IGNORED - Already completed"
```

---

### 1.4 Sơ đồ luồng xử lý Check-in / Check-out

```
[Camera nhận diện khuôn mặt]
            |
            v
   [Xác định user_id]
            |
            v
   [Kiểm tra cooldown?]
     /             \
   Còn              Hết
    |                |
[Bỏ qua]    [Truy vấn DB ngày hôm nay]
                     |
          /----------+----------\
    Chưa có              Đã có record
    record                    |
       |             /--------+--------\
  [CHECK-IN]    check_out=NULL    check_out≠NULL
                     |                 |
                [CHECK-OUT]    [Ca 2 hoặc Bỏ qua]
```

---

## 2. Xử Lý Người "Unknown"

### 2.1 Các tình huống dẫn đến Unknown

- Khuôn mặt không có trong database (người lạ, khách)
- Khoảng cách nhận diện (confidence score) vượt ngưỡng cho phép (khuôn mặt bị che, góc nghiêng)
- Ánh sáng quá tối hoặc ảnh bị mờ

### 2.2 Ngưỡng nhận diện (Confidence Threshold)

```python
# face_recognition library: dùng khoảng cách Euclidean
DISTANCE_THRESHOLD = 0.5  # < 0.5: nhận diện được, >= 0.5: Unknown

# LBPH: dùng confidence (càng thấp càng chắc)
LBPH_THRESHOLD = 80  # > 80: Unknown
```

### 2.3 Quy trình xử lý khi gặp Unknown

```
FUNCTION handle_unknown_face(frame, face_location, current_time):

    # Bước 1: Cắt vùng khuôn mặt từ frame
    face_image = crop_face(frame, face_location)

    # Bước 2: Kiểm tra cooldown cho unknown (tránh spam log)
    IF (current_time - last_unknown_log_time) < UNKNOWN_COOLDOWN:
        RETURN

    # Bước 3: Lưu ảnh (nếu bật tính năng lưu ảnh unknown)
    IF SAVE_UNKNOWN_IMAGES:
        filename = "unknown_" + timestamp + ".jpg"
        save_image(face_image, path=UNKNOWN_IMAGES_DIR + filename)
    ELSE:
        filename = NULL

    # Bước 4: Ghi vào bảng unknown_logs
    insert_unknown_log(
        timestamp     = current_time,
        image_path    = filename,
        location      = DEVICE_LOCATION,
        device_id     = DEVICE_ID
    )

    # Bước 5: Cảnh báo nếu cần (tùy chính sách)
    IF ALERT_ON_UNKNOWN:
        send_alert_to_server(event="UNKNOWN_FACE", time=current_time)

    last_unknown_log_time = current_time
```

### 2.4 Thiết kế bảng `unknown_logs`

```sql
CREATE TABLE unknown_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME     NOT NULL,
    image_path  VARCHAR(255),          -- NULL nếu không lưu ảnh
    device_id   VARCHAR(50)  NOT NULL, -- Raspberry Pi nào ghi nhận
    location    VARCHAR(100),          -- Vị trí camera (phòng, cửa...)
    note        TEXT,                  -- Ghi chú thêm nếu cần
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Ví dụ dữ liệu:**

| id | timestamp | image_path | device_id | location |
|----|-----------|-----------|-----------|---------|
| 1 | 2025-01-10 08:32:11 | unknown_20250110_083211.jpg | pi_01 | Cổng chính |
| 2 | 2025-01-10 09:15:44 | NULL | pi_01 | Cổng chính |

---

## 3. Thiết Kế Cơ Sở Dữ Liệu

### 3.1 Sơ đồ quan hệ (ERD dạng text)

```
users (1) ----< face_embeddings (nhiều)
users (1) ----< attendance (nhiều)
[unknown_logs] độc lập, không liên kết users
```

### 3.2 Bảng `users`

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  VARCHAR(20)  UNIQUE NOT NULL,  -- Mã sinh viên / nhân viên
    full_name   VARCHAR(100) NOT NULL,
    email       VARCHAR(100),
    class_name  VARCHAR(50),                   -- Lớp / phòng ban
    role        VARCHAR(20)  DEFAULT 'student',-- student / teacher / staff
    is_active   BOOLEAN      DEFAULT 1,        -- Khóa tài khoản
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 Bảng `face_embeddings`

```sql
CREATE TABLE face_embeddings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    embedding    BLOB         NOT NULL,  -- Lưu dạng bytes (numpy array serialize)
    model_type   VARCHAR(20)  DEFAULT 'face_recognition', -- 'face_recognition' | 'LBPH'
    image_ref    VARCHAR(255),           -- Đường dẫn ảnh gốc (tuỳ chọn, có thể NULL)
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP -- Hỗ trợ incremental sync
);

-- Index để tăng tốc tìm kiếm theo user
CREATE INDEX idx_embeddings_user ON face_embeddings(user_id);
```

> **Lưu ý:** Embedding của `face_recognition` là numpy array 128 chiều → serialize bằng `numpy.tobytes()` trước khi lưu, và dùng `numpy.frombuffer()` khi đọc ra.

```python
# Lưu embedding
embedding_bytes = np.array(encoding).tobytes()

# Đọc embedding
encoding = np.frombuffer(embedding_bytes, dtype=np.float64)
```

### 3.4 Bảng `attendance`

```sql
CREATE TABLE attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER  NOT NULL REFERENCES users(id),
    date       DATE     NOT NULL,             -- Ngày điểm danh
    check_in   DATETIME,                      -- Giờ vào
    check_out  DATETIME,                      -- Giờ ra (NULL nếu chưa ra)
    duration   INTEGER,                       -- Thời gian làm việc (giây)
    shift      INTEGER  DEFAULT 1,            -- Ca làm (1, 2, ...)
    status     VARCHAR(20) DEFAULT 'present', -- present | late | absent
    device_id  VARCHAR(50),                   -- Pi nào ghi nhận
    match_distance REAL,                      -- Khoảng cách nhận diện (dùng phân tích drift)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Ràng buộc: mỗi người chỉ có 1 bản ghi check-in/ca/ngày
    UNIQUE (user_id, date, shift)
);

CREATE INDEX idx_attendance_user_date ON attendance(user_id, date);
```

### 3.5 Tổng quan Schema

```
┌──────────────────┐       ┌───────────────────────┐
│      users       │       │    face_embeddings     │
├──────────────────┤       ├───────────────────────┤
│ id (PK)          │──┐    │ id (PK)               │
│ student_id       │  └───>│ user_id (FK)          │
│ full_name        │       │ embedding (BLOB)       │
│ email            │       │ model_type             │
│ class_name       │       │ image_ref              │
│ role             │       └───────────────────────┘
│ is_active        │
└────────┬─────────┘       ┌───────────────────────┐
         │                 │      attendance        │
         │                 ├───────────────────────┤
         └────────────────>│ user_id (FK)          │
                           │ date                  │
                           │ check_in              │
                           │ check_out             │
                           │ duration              │
                           │ status                │
                           └───────────────────────┘

┌──────────────────────┐
│    unknown_logs      │  (Độc lập)
├──────────────────────┤
│ id (PK)              │
│ timestamp            │
│ image_path           │
│ device_id            │
│ location             │
└──────────────────────┘
```

---

## 4. Quy Trình Đăng Ký Khuôn Mặt (Face Enrollment)

### 4.1 Tổng quan quy trình

Đăng ký khuôn mặt được thực hiện **trên server/máy tính**, không phải trực tiếp trên Raspberry Pi, để đảm bảo hiệu năng và chất lượng dữ liệu.

### 4.2 Yêu cầu về ảnh đầu vào

| Tiêu chí | Yêu cầu |
|---|---|
| Số lượng ảnh | Tối thiểu 5 ảnh, khuyến nghị 10–20 ảnh |
| Góc chụp | Chính diện, nghiêng trái/phải nhẹ, ngước lên/cúi xuống |
| Điều kiện sáng | Đa dạng: sáng tốt, ánh sáng yếu, ngược sáng |
| Kích thước | Tối thiểu 100x100 px vùng khuôn mặt |
| Có đeo khẩu trang | Nên có thêm ảnh đeo khẩu trang nếu cần |

### 4.3 Pipeline đăng ký: Ảnh → Embedding → Lưu DB

```
[Ảnh người dùng (N tấm)]
         |
         v
[Phát hiện khuôn mặt trong từng ảnh]  ← face_recognition.face_locations()
         |
         v
[Kiểm tra: phát hiện đúng 1 khuôn mặt?]
     /        \
  Không        Có
    |           |
[Bỏ qua ảnh]  [Trích xuất embedding 128D]  ← face_recognition.face_encodings()
                |
                v
         [Lưu vào DB]
         face_embeddings(user_id, embedding_bytes)
                |
                v
         [Cập nhật cache]  ← Load tất cả embeddings vào RAM khi Pi khởi động
```

### 4.4 Pseudo-code Enrollment

```
FUNCTION enroll_user(user_id, image_folder_path):
    image_files = list_images(image_folder_path)
    successful = 0

    FOR each image_file IN image_files:
        image = load_image(image_file)

        # Phát hiện khuôn mặt
        face_locations = face_recognition.face_locations(image)

        IF len(face_locations) != 1:
            log("Skip: detected " + len(face_locations) + " faces in " + image_file)
            CONTINUE

        # Trích xuất embedding
        encoding = face_recognition.face_encodings(image, face_locations)[0]

        # Serialize và lưu vào DB
        embedding_bytes = encoding.tobytes()
        insert_face_embedding(
            user_id    = user_id,
            embedding  = embedding_bytes,
            model_type = "face_recognition",
            image_ref  = image_file  # tuỳ chọn lưu đường dẫn
        )
        successful += 1

    log("Enrolled " + successful + "/" + len(image_files) + " images for user " + user_id)
    RETURN successful
```

### 4.5 Có nên lưu ảnh gốc?

| Phương án | Ưu điểm | Nhược điểm |
|---|---|---|
| Chỉ lưu embedding | Nhẹ, an toàn quyền riêng tư | Không thể re-train nếu đổi model |
| Lưu cả ảnh + embedding | Có thể re-train, debug dễ | Tốn dung lượng, rủi ro bảo mật |
| **Khuyến nghị** | Lưu embedding, lưu ảnh vào thư mục riêng có phân quyền | — |

---

## 5. Kiến Trúc Hệ Thống (Edge + Server)

### 5.1 Phân công trách nhiệm

#### Raspberry Pi (Edge Device) thực hiện:
- Thu nhận frame từ camera (OpenCV)
- Phát hiện khuôn mặt trong frame
- Trích xuất embedding từ khuôn mặt phát hiện
- So sánh embedding với danh sách đã biết (từ cache trong RAM)
- Xác định danh tính → gửi kết quả lên Server qua HTTP API
- Cache lại danh sách embedding khi khởi động (tải từ server 1 lần)
- Xử lý offline tạm thời: lưu queue nếu mất kết nối, gửi lại sau

#### Server (Backend) thực hiện:
- Cung cấp REST API nhận kết quả từ Pi
- Xử lý logic check-in / check-out
- Lưu trữ toàn bộ dữ liệu vào CSDL
- Cung cấp API quản lý user, enrollment
- Hiển thị dashboard điểm danh
- Đồng bộ danh sách embedding về Pi khi có cập nhật

### 5.2 Quyết định: Lưu DB ở đâu?

```
┌─────────────────────────────────────────────────────────┐
│              SO SÁNH VỊ TRÍ LƯU DATABASE                │
├──────────────────┬───────────────────┬──────────────────┤
│ Tiêu chí         │ Lưu ở Pi          │ Lưu ở Server     │
├──────────────────┼───────────────────┼──────────────────┤
│ Hoạt động offline│ ✅ Có             │ ❌ Không          │
│ Quản lý tập trung│ ❌ Khó            │ ✅ Dễ             │
│ Nhiều Pi         │ ❌ Phân tán       │ ✅ Đồng bộ 1 chỗ  │
│ Bảo mật dữ liệu  │ ❌ Rủi ro hơn    │ ✅ Kiểm soát tốt  │
│ Tài nguyên Pi    │ ❌ Tốn SD card    │ ✅ Không ảnh hưởng│
└──────────────────┴───────────────────┴──────────────────┘
```

**→ Khuyến nghị: Lưu DB chính ở Server.** Pi chỉ giữ cache embedding trong RAM và queue tạm thời khi offline.

### 5.3 Dữ liệu gửi từ Pi lên Server

Pi **không gửi ảnh gốc** lên server (tiết kiệm băng thông, bảo vệ quyền riêng tư). Chỉ gửi kết quả nhận diện:

```json
POST /api/attendance
{
  "user_id": 42,
  "timestamp": "2025-01-10T08:30:15",
  "confidence": 0.87,
  "match_distance": 0.42,
  "device_id": "pi_classroom_01",
  "location": "Phòng B201"
}
```

### 5.4 Sơ đồ kiến trúc tổng thể

```
┌──────────────────────────────────────────────┐
│           RASPBERRY PI (Edge)                │
│                                              │
│  Camera → OpenCV → Detect Face              │
│                       ↓                     │
│               Extract Embedding             │
│                       ↓                     │
│          Compare với Known Embeddings       │
│          (Cache trong RAM)                   │
│                       ↓                     │
│           Match found? → Send to API        │
│           No match?   → Log Unknown         │
│                                              │
│  [Offline Queue] → Gửi lại khi có mạng     │
└─────────────────────┬────────────────────────┘
                      │ HTTP POST (JSON)
                      │ (Không gửi ảnh)
                      ▼
┌──────────────────────────────────────────────┐
│             SERVER (Backend)                 │
│                                              │
│  FastAPI → Logic Check-in/out               │
│               ↓                             │
│           SQLite / MySQL                     │
│               ↓                             │
│           Dashboard (Web UI)                 │
└──────────────────────────────────────────────┘
```

### 5.5 API Endpoints cần thiết

```
# Nhận kết quả từ Pi (yêu cầu JWT)
POST   /api/attendance          - Pi gửi kết quả nhận diện
POST   /api/unknown             - Pi gửi cảnh báo unknown

# Đồng bộ embedding về Pi (yêu cầu JWT)
GET    /api/embeddings          - tải danh sách embedding (có hỗ trợ last_sync_time)

# Quản lý (Admin Dashboard)
GET    /api/attendance?date=    - Xem danh sách điểm danh theo ngày
POST   /api/users               - Thêm người dùng mới
POST   /api/users/{id}/enroll   - Đăng ký khuôn mặt
GET    /api/users               - Danh sách người dùng
```

---

## 6. Tối Ưu Hiệu Năng Trên Raspberry Pi

### 6.1 Vấn đề hiệu năng thường gặp

Raspberry Pi 4 có thể chạy nhận diện khuôn mặt nhưng dễ gặp bottleneck nếu xử lý từng frame toàn bộ pipeline. Các kỹ thuật sau đây giúp giảm lag đáng kể.

### 6.2 Các kỹ thuật tối ưu

#### (a) Giảm tần suất xử lý (Frame Skipping)

Không nhất thiết phải xử lý 30 fps. Xử lý 1 frame mỗi N frame là đủ:

```python
frame_count = 0
PROCESS_EVERY_N = 5  # Xử lý 1 frame trong 5

while True:
    ret, frame = cap.read()
    frame_count += 1

    if frame_count % PROCESS_EVERY_N != 0:
        continue  # Bỏ qua frame này

    # Xử lý nhận diện...
```

#### (b) Resize ảnh trước khi xử lý AI

```python
SCALE = 0.5  # Giảm xuống 50%

small_frame = cv2.resize(frame, (0, 0), fx=SCALE, fy=SCALE)
rgb_small   = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

face_locations = face_recognition.face_locations(rgb_small, model="hog")

# Scale lại tọa độ để vẽ lên frame gốc
face_locations = [(int(v / SCALE) for v in loc) for loc in face_locations]
```

#### (c) Cache embedding trong RAM (không đọc DB mỗi frame)

```python
# Tải 1 lần khi khởi động
known_embeddings = []
known_names = []

def load_embeddings_from_db():
    rows = db.query("SELECT user_id, embedding FROM face_embeddings")
    for row in rows:
        enc = np.frombuffer(row["embedding"], dtype=np.float64)
        known_embeddings.append(enc)
        known_names.append(row["user_id"])

load_embeddings_from_db()  # Gọi 1 lần khi khởi động
```

#### (d) Dùng HOG thay vì CNN cho face detection

```python
# CNN: chính xác hơn nhưng chậm ~5x trên Pi
face_locations = face_recognition.face_locations(frame, model="cnn")  # Chậm

# HOG: nhanh hơn, đủ dùng trong điều kiện đủ sáng
face_locations = face_recognition.face_locations(frame, model="hog")  # Nhanh hơn
```

#### (e) Xử lý bất đồng bộ với Thread

Tách luồng đọc camera và luồng xử lý AI để không bị block:

```python
import threading, queue

frame_queue = queue.Queue(maxsize=2)

def camera_thread():
    cap = cv2.VideoCapture(0)
    while True:
        ret, frame = cap.read()
        if not frame_queue.full():
            frame_queue.put(frame)

def recognition_thread():
    while True:
        if not frame_queue.empty():
            frame = frame_queue.get()
            # Xử lý nhận diện ở đây...

threading.Thread(target=camera_thread, daemon=True).start()
threading.Thread(target=recognition_thread, daemon=True).start()
```

#### (f) Cooldown sau khi nhận diện

Sau khi nhận diện thành công, dừng xử lý trong vài giây:

```python
last_recognized = {}  # {user_id: timestamp}
RECOGNITION_COOLDOWN = 10  # giây

def should_process(user_id):
    now = time.time()
    if user_id in last_recognized:
        if now - last_recognized[user_id] < RECOGNITION_COOLDOWN:
            return False
    last_recognized[user_id] = now
    return True
```

### 6.3 Bảng tổng hợp kỹ thuật tối ưu

| Kỹ thuật | Mức giảm tải | Đánh đổi |
|---|---|---|
| Frame skipping (1/5) | ~80% CPU | Phản hồi chậm hơn ~150ms |
| Resize 50% | ~75% CPU AI | Giảm độ chính xác nhẹ |
| HOG thay CNN | ~5x nhanh hơn | Kém chính xác hơn CNN |
| Cache embedding RAM | Không đọc DB | Tốn RAM (thường < 10MB) |
| Threading | Camera không lag | Code phức tạp hơn |
| Cooldown sau nhận diện | Giảm lặp xử lý | Không ảnh hưởng UX |

### 6.4 Cấu hình khuyến nghị cho Pi 4

```python
# Cấu hình cân bằng tốc độ / độ chính xác
CAMERA_WIDTH       = 640
CAMERA_HEIGHT      = 480
CAMERA_FPS         = 15
PROCESS_EVERY_N    = 4      # ~3.75 fps xử lý thực tế
RESIZE_SCALE       = 0.5
DETECTION_MODEL    = "hog"
RECOGNITION_MODEL  = "face_recognition"  # 128D embeddings
COOLDOWN_SECONDS   = 5
DISTANCE_THRESHOLD = 0.5
```

---

## 7. Chức Năng Đăng Ký Khuôn Mặt (Face Enrollment Feature)

Phần này mô tả chi tiết cách triển khai tính năng đăng ký khuôn mặt cho developer, bao gồm hai luồng chính: **đăng ký qua camera thời gian thực** (dùng cho demo) và **đăng ký qua upload ảnh** (dùng để chuẩn bị test data với số liệu chuẩn).

---

### 7.1 Tổng quan hai luồng đăng ký

```
┌────────────────────────────────────────────────────────────────┐
│                    FACE ENROLLMENT                             │
│                                                                │
│   Luồng A: Camera thời gian thực   Luồng B: Upload ảnh        │
│   (Demo / đăng ký 1 người)         (Test data / batch)        │
│                                                                │
│   Camera → Auto capture N ảnh      Upload thư mục ảnh         │
│   Hiển thị live preview            Hiển thị progress bar      │
│   Phản hồi trực quan               Báo cáo kết quả từng ảnh   │
│            ↓                                  ↓               │
│        [Detect Face] ─────────────────── [Detect Face]        │
│            ↓                                  ↓               │
│      [Extract Embedding]              [Extract Embedding]     │
│            ↓                                  ↓               │
│        [Lưu vào DB] ──────────────────── [Lưu vào DB]        │
│            ↓                                  ↓               │
│    Thông báo thành công            Báo cáo tổng kết           │
└────────────────────────────────────────────────────────────────┘
```

---

### 7.2 Luồng A — Đăng Ký Qua Camera Thời Gian Thực

#### Mô tả hoạt động

Khi người dùng chọn đăng ký qua camera, hệ thống mở luồng video và tự động chụp ảnh khi phát hiện khuôn mặt hợp lệ (đủ to, đủ rõ, không bị mờ). Người dùng thấy trực tiếp preview và tiến độ thu thập ảnh.

#### Thông số cần cấu hình

```python
# config.py - Enrollment settings
ENROLL_TARGET_SAMPLES   = 20      # Số ảnh cần thu thập
ENROLL_MIN_FACE_SIZE    = 100     # Kích thước mặt tối thiểu (pixel)
ENROLL_CAPTURE_INTERVAL = 0.5     # Giây giữa 2 lần chụp tự động
ENROLL_BLUR_THRESHOLD   = 100.0   # Laplacian variance - dưới mức này là ảnh mờ
ENROLL_ANGLE_GUIDANCE   = True    # Hướng dẫn người dùng xoay mặt
```

#### Pseudo-code Luồng A

```
FUNCTION enroll_via_camera(user_id, user_name):

    # --- Khởi tạo ---
    cap = open_camera()
    collected_samples = []
    last_capture_time = 0
    guidance_steps = ["Nhìn thẳng", "Quay trái nhẹ", "Quay phải nhẹ",
                      "Ngước lên", "Cúi xuống", "Nhìn thẳng (ánh sáng khác)"]
    current_step = 0

    DISPLAY overlay: "Chuẩn bị đăng ký cho: {user_name}"
    DISPLAY progress_bar: 0 / ENROLL_TARGET_SAMPLES

    WHILE len(collected_samples) < ENROLL_TARGET_SAMPLES:
        frame = cap.read()

        # B1: Phát hiện khuôn mặt trong frame
        face_locations = detect_faces(frame)

        IF len(face_locations) == 0:
            DISPLAY status: "⚠ Không tìm thấy khuôn mặt"
            DISPLAY frame (không highlight)
            CONTINUE

        IF len(face_locations) > 1:
            DISPLAY status: "⚠ Chỉ để 1 người trước camera"
            DISPLAY frame
            CONTINUE

        face_loc = face_locations[0]
        face_w, face_h = get_face_size(face_loc)

        # B2: Kiểm tra kích thước khuôn mặt
        IF face_w < ENROLL_MIN_FACE_SIZE OR face_h < ENROLL_MIN_FACE_SIZE:
            DISPLAY status: "⚠ Lại gần camera hơn"
            DRAW red_rectangle(frame, face_loc)
            CONTINUE

        # B3: Kiểm tra độ mờ của ảnh
        blur_score = calculate_laplacian_variance(crop_face(frame, face_loc))
        IF blur_score < ENROLL_BLUR_THRESHOLD:
            DISPLAY status: "⚠ Ảnh bị mờ, giữ nguyên tư thế"
            DRAW yellow_rectangle(frame, face_loc)
            CONTINUE

        # B4: Hướng dẫn góc chụp (tuỳ chọn)
        IF ENROLL_ANGLE_GUIDANCE AND current_step < len(guidance_steps):
            DISPLAY guidance: "👉 " + guidance_steps[current_step]

        # B5: Kiểm tra khoảng cách giữa 2 lần chụp
        now = current_time()
        IF (now - last_capture_time) < ENROLL_CAPTURE_INTERVAL:
            DRAW green_rectangle(frame, face_loc)  # Cho thấy mặt đang được track
            CONTINUE

        # B6: Chụp và lưu sample
        face_image = crop_and_preprocess(frame, face_loc)
        collected_samples.append(face_image)
        last_capture_time = now
        current_step += 1

        # B7: Cập nhật UI
        count = len(collected_samples)
        DISPLAY status: f"✅ Đã chụp {count}/{ENROLL_TARGET_SAMPLES}"
        DISPLAY progress_bar: count / ENROLL_TARGET_SAMPLES
        PLAY sound: "capture_beep"  # Tiếng beep xác nhận
        FLASH green_overlay(frame, duration=0.1s)

        DRAW green_rectangle(frame, face_loc)
        DISPLAY frame

    # --- Hoàn tất thu thập, bắt đầu xử lý ---
    cap.release()
    DISPLAY status: "⏳ Đang xử lý và lưu dữ liệu..."
    DISPLAY spinner

    result = process_and_save_embeddings(user_id, collected_samples)

    IF result.success_count >= ENROLL_TARGET_SAMPLES * 0.8:  # Đạt >= 80%
        DISPLAY success_screen(
            message  = f"✅ Đăng ký thành công!",
            subtitle = f"Đã lưu {result.success_count} mẫu khuôn mặt",
            user     = user_name
        )
        RETURN SUCCESS
    ELSE:
        DISPLAY error_screen(
            message = f"❌ Đăng ký thất bại",
            reason  = f"Chỉ trích xuất được {result.success_count} mẫu hợp lệ",
            action  = "Vui lòng thử lại với điều kiện sáng tốt hơn"
        )
        RETURN FAILURE
```

#### Phản hồi trực quan (Visual Feedback) trong Luồng A

| Trạng thái | Màu khung | Thông báo | Âm thanh |
|---|---|---|---|
| Không thấy mặt | Không có | ⚠ Không tìm thấy khuôn mặt | — |
| Nhiều hơn 1 mặt | — | ⚠ Chỉ để 1 người trước camera | — |
| Mặt quá nhỏ | 🔴 Đỏ | ⚠ Lại gần camera hơn | — |
| Ảnh bị mờ | 🟡 Vàng | ⚠ Giữ nguyên tư thế | — |
| Đang tracking | 🟢 Xanh lá | Sẵn sàng chụp... | — |
| Chụp thành công | 🟢 Flash xanh | ✅ Đã chụp N/20 | Beep |
| Đang xử lý | Spinner | ⏳ Đang lưu dữ liệu... | — |
| Thành công | Màn hình xanh | ✅ Đăng ký thành công | — |
| Thất bại | Màn hình đỏ | ❌ Thất bại + hướng dẫn | — |

#### Code mẫu kiểm tra chất lượng ảnh

```python
import cv2
import numpy as np

def is_face_valid(frame, face_location, min_size=100, blur_threshold=100.0):
    top, right, bottom, left = face_location
    face_h = bottom - top
    face_w = right - left

    # Kiểm tra kích thước
    if face_w < min_size or face_h < min_size:
        return False, "TOO_SMALL"

    # Kiểm tra độ mờ bằng Laplacian variance
    face_crop = frame[top:bottom, left:right]
    gray      = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    blur_var  = cv2.Laplacian(gray, cv2.CV_64F).var()

    if blur_var < blur_threshold:
        return False, "TOO_BLURRY"

    return True, "OK"
```

---

### 7.3 Luồng B — Đăng Ký Qua Upload Ảnh (Test Data)

#### Mô tả hoạt động

Luồng này được dùng để chuẩn bị test data chuẩn cho việc đánh giá hệ thống. Dev hoặc admin cung cấp một thư mục ảnh có cấu trúc sẵn, hệ thống xử lý hàng loạt (batch) và sinh báo cáo chi tiết.

#### Cấu trúc thư mục ảnh chuẩn

```
dataset/
├── nguyen_van_a/           ← Tên thư mục = tên người (hoặc student_id)
│   ├── img_001.jpg
│   ├── img_002.jpg
│   └── ...                 ← Tối thiểu 10 ảnh/người
├── tran_thi_b/
│   ├── img_001.jpg
│   └── ...
└── le_van_c/
    └── ...
```

> **Quy tắc đặt tên thư mục:** Dùng `student_id` nếu muốn hệ thống tự map với DB. Ví dụ: thư mục `SV001` sẽ tự tìm user có `student_id = 'SV001'`.

#### Pseudo-code Luồng B

```
FUNCTION batch_enroll_from_folder(dataset_path):

    persons = list_subdirectories(dataset_path)
    report  = BatchEnrollReport()

    DISPLAY header: f"Bắt đầu đăng ký hàng loạt: {len(persons)} người"
    DISPLAY progress_bar: 0 / len(persons)

    FOR i, person_folder IN enumerate(persons):
        student_id = folder_name(person_folder)
        image_files = list_images(person_folder)  # .jpg, .png, .jpeg

        DISPLAY current: f"[{i+1}/{len(persons)}] Đang xử lý: {student_id}"

        # B1: Tìm user trong DB
        user = db.get_user_by_student_id(student_id)
        IF user IS NULL:
            report.add_error(student_id, reason="Không tìm thấy user trong DB")
            DISPLAY warning: f"⚠ Bỏ qua {student_id}: không có trong DB"
            CONTINUE

        # B2: Xử lý từng ảnh
        person_result = PersonEnrollResult(student_id)

        FOR img_file IN image_files:
            image = load_image(img_file)
            status = process_single_image(image, user.id)
            person_result.add(img_file, status)

            # Hiển thị kết quả từng ảnh
            icon = "✅" IF status == "OK" ELSE "❌"
            DISPLAY inline: f"  {icon} {filename(img_file)}: {status}"

        # B3: Tổng kết từng người
        report.add_person(person_result)
        ok_count    = person_result.count("OK")
        total_count = len(image_files)
        DISPLAY summary_row: f"  → {ok_count}/{total_count} ảnh hợp lệ"
        UPDATE progress_bar: (i + 1) / len(persons)

    # B4: In báo cáo tổng
    print_batch_report(report)
    RETURN report


FUNCTION process_single_image(image, user_id):
    face_locations = face_recognition.face_locations(image, model="hog")

    IF len(face_locations) == 0:
        RETURN "NO_FACE"
    IF len(face_locations) > 1:
        RETURN "MULTIPLE_FACES"

    # Kiểm tra chất lượng
    valid, reason = is_face_valid(image, face_locations[0])
    IF NOT valid:
        RETURN reason  # "TOO_SMALL" hoặc "TOO_BLURRY"

    # Trích xuất embedding
    encoding = face_recognition.face_encodings(image, face_locations)[0]
    IF encoding IS NULL:
        RETURN "ENCODING_FAILED"

    # Lưu vào DB
    db.insert_face_embedding(
        user_id    = user_id,
        embedding  = encoding.tobytes(),
        model_type = "face_recognition"
    )
    RETURN "OK"
```

#### Báo cáo tổng kết sau khi chạy Batch Enrollment

```
╔══════════════════════════════════════════════════════╗
║         BÁO CÁO ĐĂNG KÝ KHUÔN MẶT HÀNG LOẠT        ║
╠══════════════════════════════════════════════════════╣
║ Tổng số người xử lý : 10                            ║
║ Thành công           : 9                             ║
║ Thất bại (thiếu user): 1                             ║
╠══════════════════════════════════════════════════════╣
║ CHI TIẾT TỪNG NGƯỜI                                  ║
╠══════════════════════════════════════════════════════╣
║ SV001 - Nguyễn Văn A : 18/20 ảnh OK  ✅             ║
║   ↳ 2 ảnh lỗi: [img_005.jpg: TOO_BLURRY]            ║
║                [img_019.jpg: NO_FACE]                ║
║                                                      ║
║ SV002 - Trần Thị B   : 20/20 ảnh OK  ✅             ║
║                                                      ║
║ SV003 - Lê Văn C     : 15/20 ảnh OK  ✅             ║
║   ↳ 5 ảnh lỗi: [img_003.jpg: TOO_SMALL] x3          ║
║                [img_011.jpg: MULTIPLE_FACES] x2      ║
║                                                      ║
║ SV999 - [UNKNOWN]    : SKIPPED ❌                    ║
║   ↳ Không tìm thấy user SV999 trong database         ║
╠══════════════════════════════════════════════════════╣
║ THỐNG KÊ LỖI                                         ║
║   NO_FACE        : 3 ảnh                            ║
║   TOO_BLURRY     : 5 ảnh                            ║
║   TOO_SMALL      : 7 ảnh                            ║
║   MULTIPLE_FACES : 2 ảnh                            ║
║   ENCODING_FAILED: 0 ảnh                            ║
╚══════════════════════════════════════════════════════╝
```

---

### 7.4 Hàm Xử Lý Embedding Chung (Dùng Cho Cả Hai Luồng)

```python
import face_recognition
import numpy as np
from db import get_db_connection

def process_and_save_embeddings(user_id: int, images: list) -> dict:
    """
    Nhận vào danh sách ảnh (numpy array), trích xuất embedding và lưu DB.
    Trả về báo cáo kết quả.
    """
    conn = get_db_connection()
    success_count = 0
    error_log = []

    for idx, image in enumerate(images):
        try:
            # Chuyển BGR (OpenCV) → RGB (face_recognition)
            rgb_image = image[:, :, ::-1]

            face_locations = face_recognition.face_locations(rgb_image, model="hog")

            if len(face_locations) != 1:
                error_log.append({"index": idx, "reason": "INVALID_FACE_COUNT",
                                  "count": len(face_locations)})
                continue

            encodings = face_recognition.face_encodings(rgb_image, face_locations)

            if not encodings:
                error_log.append({"index": idx, "reason": "ENCODING_FAILED"})
                continue

            # Serialize numpy array → bytes để lưu DB
            embedding_bytes = encodings[0].tobytes()

            conn.execute(
                "INSERT INTO face_embeddings (user_id, embedding, model_type) VALUES (?, ?, ?)",
                (user_id, embedding_bytes, "face_recognition")
            )
            conn.commit()
            success_count += 1

        except Exception as e:
            error_log.append({"index": idx, "reason": "EXCEPTION", "detail": str(e)})

    return {
        "success_count": success_count,
        "total":         len(images),
        "errors":        error_log
    }


def load_known_embeddings() -> tuple[list, list]:
    """
    Tải tất cả embedding từ DB vào RAM (gọi 1 lần khi Pi khởi động).
    Trả về (danh sách encoding, danh sách user_id).
    """
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT fe.user_id, fe.embedding, u.full_name "
        "FROM face_embeddings fe JOIN users u ON fe.user_id = u.id"
    ).fetchall()

    known_encodings = []
    known_labels    = []

    for row in rows:
        enc = np.frombuffer(row["embedding"], dtype=np.float64)
        known_encodings.append(enc)
        known_labels.append({"user_id": row["user_id"], "name": row["full_name"]})

    return known_encodings, known_labels
```

---

### 7.5 API Endpoints cho Enrollment

```python
# api.py (FastAPI)

# --- Luồng B: Upload ảnh ---
@app.post("/api/enroll/upload")
async def enroll_from_upload(
    user_id: int,
    files: list[UploadFile] = File(...)
):
    """
    Nhận nhiều file ảnh, xử lý embedding và lưu DB.
    Trả về báo cáo chi tiết từng ảnh.
    """
    images = []
    for file in files:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        images.append(img)

    result = process_and_save_embeddings(user_id, images)

    return {
        "user_id":       user_id,
        "success_count": result["success_count"],
        "total":         result["total"],
        "success_rate":  result["success_count"] / result["total"],
        "errors":        result["errors"],
        "status":        "success" if result["success_count"] > 0 else "failed"
    }


# --- Đồng bộ embedding về Pi ---
@app.get("/api/embeddings/sync")
async def sync_embeddings(last_sync_time: str = None):
    """
    Pi gọi endpoint này để đồng bộ embedding mới nhất.
    Hỗ trợ đồng bộ một phần (incremental) thông qua last_sync_time.
    """
    if last_sync_time:
        rows = db.query("SELECT user_id, embedding, model_type FROM face_embeddings WHERE updated_at > ?", (last_sync_time,))
    else:
        rows = db.query("SELECT user_id, embedding, model_type FROM face_embeddings")
    return {
        "count": len(rows),
        "embeddings": [
            {
                "user_id":    row.user_id,
                "embedding":  base64.b64encode(row.embedding).decode(),
                "model_type": row.model_type
            }
            for row in rows
        ]
    }


# --- Xóa embedding (re-enroll) ---
@app.delete("/api/users/{user_id}/embeddings")
async def reset_enrollment(user_id: int):
    """Xóa toàn bộ embedding của 1 user để đăng ký lại."""
    deleted = db.execute(
        "DELETE FROM face_embeddings WHERE user_id = ?", (user_id,)
    )
    return {"deleted_count": deleted.rowcount, "status": "ok"}


# --- Kiểm tra trạng thái enrollment ---
@app.get("/api/users/{user_id}/enrollment-status")
async def get_enrollment_status(user_id: int):
    count = db.query_one(
        "SELECT COUNT(*) as cnt FROM face_embeddings WHERE user_id = ?", (user_id,)
    )
    return {
        "user_id":    user_id,
        "enrolled":   count > 0,
        "sample_count": count,
        "is_sufficient": count >= 10  # Đủ mẫu để nhận diện ổn định
    }
```

---

### 7.6 Chuẩn Bị Test Data — Hướng Dẫn Thực Tế

Đây là quy trình chuẩn để thu thập ảnh test data đảm bảo số liệu đánh giá có giá trị:

#### Yêu cầu về ảnh test data

| Tiêu chí | Yêu cầu tối thiểu | Khuyến nghị |
|---|---|---|
| Số ảnh / người (training) | 10 ảnh | 20–30 ảnh |
| Số ảnh / người (testing) | 5 ảnh | 10 ảnh |
| Số người trong dataset | 5 người | 10+ người |
| Đa dạng góc chụp | Bắt buộc | Có 5 góc khác nhau |
| Đa dạng ánh sáng | Khuyến nghị | Trong nhà, ngoài trời, tối |
| Độ phân giải tối thiểu | 640×480 | 1280×720 |

#### Script thu thập ảnh test nhanh bằng camera

```python
# tools/collect_test_images.py
# Chạy: python collect_test_images.py --name SV001 --count 30

import cv2, os, argparse, time

def collect_images(student_id: str, target_count: int, output_dir: str = "dataset"):
    save_path = os.path.join(output_dir, student_id)
    os.makedirs(save_path, exist_ok=True)

    cap = cv2.VideoCapture(0)
    collected = 0
    last_capture = 0

    print(f"Thu thập ảnh cho: {student_id}")
    print(f"Nhấn SPACE để chụp thủ công, Q để thoát")
    print(f"Hoặc hệ thống tự chụp mỗi 1 giây khi phát hiện mặt")

    while collected < target_count:
        ret, frame = cap.read()
        display = frame.copy()

        # Hiển thị progress
        cv2.putText(display, f"{student_id}: {collected}/{target_count}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Hướng dẫn góc
        hints = ["Nhìn thẳng", "Trái", "Phải", "Ngước", "Cúi", "Bình thường"]
        hint  = hints[min(collected // 5, len(hints) - 1)]
        cv2.putText(display, f"Gợi ý: {hint}",
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)

        cv2.imshow("Thu thập ảnh", display)

        key = cv2.waitKey(1) & 0xFF
        now = time.time()

        # Tự động chụp mỗi 1 giây
        auto_capture = (now - last_capture) >= 1.0

        if key == ord(' ') or auto_capture:
            filename = os.path.join(save_path, f"img_{collected+1:03d}.jpg")
            cv2.imwrite(filename, frame)
            collected += 1
            last_capture = now
            print(f"  Đã chụp: {filename}")

        if key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nHoàn tất: {collected} ảnh lưu tại {save_path}/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name",  required=True, help="Student ID")
    parser.add_argument("--count", type=int, default=20, help="Số ảnh cần chụp")
    args = parser.parse_args()
    collect_images(args.name, args.count)
```

#### Script chạy batch enrollment từ thư mục dataset

```python
# tools/batch_enroll.py
# Chạy: python batch_enroll.py --dataset ./dataset

import os, requests, cv2, argparse

SERVER_URL = "http://localhost:8000"

def batch_enroll(dataset_path: str):
    persons = [d for d in os.listdir(dataset_path)
               if os.path.isdir(os.path.join(dataset_path, d))]

    print(f"\nBắt đầu đăng ký hàng loạt: {len(persons)} người\n")
    total_ok, total_fail = 0, 0

    for person in persons:
        student_id = person
        folder     = os.path.join(dataset_path, person)
        img_files  = [f for f in os.listdir(folder)
                      if f.lower().endswith((".jpg", ".jpeg", ".png"))]

        # Tìm user_id từ server
        r = requests.get(f"{SERVER_URL}/api/users?student_id={student_id}")
        if r.status_code != 200 or not r.json():
            print(f"❌ {student_id}: không tìm thấy trong DB")
            total_fail += 1
            continue

        user_id = r.json()[0]["id"]

        # Upload ảnh lên server
        files = []
        for img_file in img_files:
            path = os.path.join(folder, img_file)
            files.append(("files", (img_file, open(path, "rb"), "image/jpeg")))

        result = requests.post(
            f"{SERVER_URL}/api/enroll/upload?user_id={user_id}",
            files=files
        ).json()

        ok    = result["success_count"]
        total = result["total"]
        rate  = result["success_rate"] * 100
        status = "✅" if ok >= total * 0.8 else "⚠️"

        print(f"{status} {student_id}: {ok}/{total} ảnh OK ({rate:.0f}%)")

        for err in result.get("errors", []):
            print(f"   ↳ Ảnh {err['index']}: {err['reason']}")

        total_ok += 1

    print(f"\n{'='*50}")
    print(f"Hoàn tất: {total_ok} thành công, {total_fail} thất bại")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="./dataset")
    args = parser.parse_args()
    batch_enroll(args.dataset)
```

---

### 7.7 Sơ Đồ Luồng Tổng Hợp

```
DEMO (Camera thời gian thực)         TEST DATA (Upload ảnh)
          │                                    │
          ▼                                    ▼
  Mở camera, hiển thị preview       Chuẩn bị thư mục dataset/
          │                                    │
          ▼                                    ▼
  Phát hiện mặt liên tục            Chạy collect_test_images.py
  Kiểm tra: size, blur, 1 mặt       (thu thập 20–30 ảnh/người)
          │                                    │
          ▼                                    ▼
  Flash xanh + beep khi chụp OK     Chạy batch_enroll.py
  Progress bar tăng dần              Hệ thống xử lý từng thư mục
          │                                    │
          ▼                                    ▼
  Đủ N ảnh → xử lý embedding        Hiển thị báo cáo từng người
          │                                    │
          ▼                                    ▼
  Lưu DB → Màn hình thành công      Lưu DB → Báo cáo tổng kết
          │                                    │
          └────────────────┬───────────────────┘
                           ▼
              Cập nhật cache trên Pi
              (Pi gọi /api/embeddings/sync)
                           ▼
              Sẵn sàng nhận diện
```

---

## 8. Cải Tiến & Tính Năng Nâng Cao (AIoT)

Để cân bằng giữa một đồ án môn học AIoT và tính thực tế, hệ thống bổ sung một số cơ chế đơn giản nhưng mang lại hiệu quả cao theo các góp ý chuyên sâu:

### 8.1 Bảo mật API với JWT
*   **Vấn đề:** Các endpoint dễ bị gọi giả mạo (spoofing) từ người dùng trái phép trên cùng mạng WiFi.
*   **Thiết kế:** Áp dụng xác thực JWT cơ bản. Pi lưu trữ cấu hình `API_KEY` ở biến môi trường hoặc file local. Khi gọi API, gửi thêm Header: `Authorization: Bearer <token_jwt>`.

### 8.2 Cơ chế đồng bộ Incremental Sync cho Embedding
*   **Vấn đề:** Tải lại toàn bộ embedding từ đầu làm tốn băng thông và khá lâu trên Pi.
*   **Thiết kế:**
    *   Bảng `face_embeddings` có trường `updated_at`.
    *   Raspberry Pi lưu trạng thái thời điểm update gần nhất (`last_sync_time`).
    *   API sync `/api/embeddings/sync` có hỗ trợ `last_sync_time`. Nếu có truyền time, server **chỉ trả về** những embeddings mới hơn mốc này. Pi sẽ chèn/cập nhật vào cache trên RAM thay vì reset từ đầu.

### 8.3 Xử lý rủi ro Data Drift (Khuôn mặt thay đổi)
*   **Vấn đề:** Con người thay đổi qua thời gian (tuổi tác, tóc, mập/ốm). Nhận diện lâu ngày có thể giảm độ chính xác và chậm chạp.
*   **Thiết kế:**
    *   **Tracking Drift:** Server nhận thông số `match_distance` và lưu lại trong bản ghi lịch sử điểm danh.
    *   **Adaptive Threshold:** Dựa vào `match_distance`, nếu user có distance luôn lân cận ~0.45 – 0.49 (đúng nhưng không chắc chắn) liên tục, thì hệ thống cảnh báo **Warning Re-enroll**.
    *   **Re-enrollment Policy:** Đề xuất thông báo yêu cầu người dùng phải chủ động cập nhật lại thông tin khuôn mặt sau một khoảng thời gian (khoảng 3 – 6 tháng).

### 8.4 Anti-Spoofing & Liveness Detection Cơ Bản
*   **Vấn đề:** Người dùng giơ ảnh in hoặc màn hình điện thoại dẫn đến qua mặt được model nhận diện khuôn mặt.
*   **Thiết kế:** Dùng **Blink Detection** (đơn giản, dễ setup cho đồ án):
    *   Dùng haar-cascade, dlib, hoặc mediapipe face mesh để đo tham số EAR (Eye Aspect Ratio).
    *   Phát hiện người thật với thao tác chớp mắt từ Tốt -> Nhắm -> Tốt chỉ trong vài frames.
    *   Chỉ các hình ảnh xác định qua liveness mới tiến hành qua bước Extract embedding để so khớp.

---

## Tóm Tắt Các Quyết Định Thiết Kế

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| Logic Check-in/out | Dựa theo trạng thái cuối trong ngày | Đơn giản, rõ ràng |
| Lưu Unknown | Có log, ảnh tuỳ chọn | Audit trail, debug |
| Vị trí DB | Server | Tập trung, dễ quản lý |
| Lưu embedding | BLOB trong DB | Không phụ thuộc file |
| Gửi dữ liệu từ Pi | Chỉ gửi JSON kết quả | Tiết kiệm băng thông |
| Detection model | HOG | Cân bằng tốc độ/chính xác |
| Số ảnh enrollment | 10–20 ảnh | Đủ chính xác, không quá nặng |
| Offline handling | Queue tạm trên Pi | Tránh mất dữ liệu |
| Cải tiến bảo mật | Sử dụng JWT token Auth | Xác thực thiết bị một cách rõ ràng |
| Cập nhật Data | Incremental Sync | Tối ưu hóa băng thông, tải trên Server và RAM trên Pi |
| Cải thiện Face Drift | Adaptive Thresholds & distance | Phân tích xu hướng để nhắc nhở re-enrollment |
| Liveness Detection | Blink detection logic qua EAR | Hiệu suất khá tốt cho Raspberry Pi trong đồ án |
| Enrollment camera | Auto capture + quality check | Tránh ảnh mờ/xấu lọt vào DB |
| Enrollment upload | Batch từ thư mục | Dễ chuẩn bị test data hàng loạt |
| Kiểm tra chất lượng ảnh | Size + Laplacian blur | Loại ảnh mờ, quá nhỏ tự động |
| Phản hồi người dùng | Màu khung + text + beep | Trực quan, không cần đọc log |
| Re-enrollment | Xóa embedding cũ, đăng ký lại | Hỗ trợ qua API DELETE |
