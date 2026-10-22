# genVideo

Tạo video bài giảng tiếng Anh hoạt hình (~2 phút, 1280×720) hoàn toàn bằng code: cô giáo hoạt hình, bảng đen, phụ đề Anh–Việt, giọng đọc TTS offline.

Demo: [`output/english_greetings_demo.mp4`](output/english_greetings_demo.mp4) — Lesson 1: Greetings.

## Cài đặt

Cần Python 3.9+, `ffmpeg` và `espeak-ng`.

```bash
# Ubuntu/Debian
sudo apt install ffmpeg espeak-ng
# macOS
brew install ffmpeg espeak-ng

pip install -r requirements.txt
```

## Chạy

```bash
python make_video.py                 # render video vào output/
python make_video.py preview 3 30 75 # chỉ xuất vài khung hình PNG (giây 3, 30, 75) vào build/
```

Biến môi trường tuỳ chọn:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GENVIDEO_OUT` | `output/english_greetings_demo.mp4` | File video đầu ra |
| `GENVIDEO_WORK` | `build/` | Thư mục file tạm (wav, preview) |
| `GENVIDEO_FONT_BOLD`, `GENVIDEO_FONT_REGULAR` | DejaVu Sans / Arial | Font hỗ trợ tiếng Việt |

## Cấu trúc script

- `SCENES`, `BOARDS`: danh sách phần học và nội dung trên bảng.
- Các lệnh `seg(...)`: kịch bản từng câu (người nói, câu tiếng Anh, phụ đề tiếng Việt, mục đang chỉ trên bảng, động tác tay).
- `VOICE`: giọng espeak-ng cho cô Lan (`T`) và Nam (`N`).
- `teacher()`, `draw_board()`, `draw_caption()`: vẽ nhân vật, bảng và phụ đề cho từng khung hình (PIL), rồi pipe sang ffmpeg.

Muốn làm bài khác: sửa `SCENES`, `BOARDS` và các dòng `seg(...)`.
