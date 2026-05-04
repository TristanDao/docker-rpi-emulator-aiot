# Benchmark: So sánh thuật toán nhận diện khuôn mặt

> Dataset: LFW subset (50 người, 2012 ảnh)
> Ngày: 2026-04-30
> Tỷ lệ chia: 80% train / 20% test (seed=42)

## So sánh Detection

| Phương pháp | Tỷ lệ phát hiện | Tốc độ TB (ms) | Số ảnh test |
|-------------|-----------------|----------------|-------------|
| HOG          | 93.5%            | 7.2             | 2012         |
| Haar         | 32.9%            | 2.9             | 2012         |

## So sánh Recognition (4 Tổ hợp)

| Tổ hợp | Accuracy | Precision | Recall | F1 Score | Tốc độ TB (ms) |
|--------|----------|-----------|--------|----------|----------------|
| HOG + ResNet (Hệ thống hiện tại)         | 99.5%     | 100.0%     | 99.5%   | 99.7%     | 33.9            |
| HOG + LBPH                               | 65.3%     | 65.3%      | 100.0%  | 79.0%     | 104.1           |
| Haar + ResNet                            | 96.5%     | 99.3%      | 97.2%   | 98.2%     | 42.7            |
| Haar + LBPH                              | 81.7%     | 81.7%      | 100.0%  | 89.9%     | 40.5            |

## Kết luận

- **Tốt nhất về F1**: `HOG + ResNet` (F1 = 99.7%)
- **Tốt nhất về accuracy**: `HOG + ResNet` (99.5%)
- **Nhanh nhất**: `HOG + ResNet` (33.9 ms/frame)
- HOG + ResNet là baseline của hệ thống hiện tại.

