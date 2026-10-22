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

## TTS đa ngôn ngữ (Anh – Trung – Nhật – Hàn – Việt)

Repo dùng **2 môi trường tách biệt**, mỗi lần chỉ chạy một model:

| Ngôn ngữ | Model | Môi trường |
|---|---|---|
| `en`, `zh`, `ja`, `ko` | Qwen3-TTS 1.7B CustomVoice | `.venv-qwen` |
| `vi` | VieNeu-TTS v3 Turbo (48 kHz) | `.venv-vieneu` |

Cài đặt một lần:

```bash
bash setup_tts.sh
```

Sinh audio:

```bash
python3 tts_gen.py --lang en --text "Hello!" --out output/tts/en.wav
python3 tts_gen.py --lang vi --text "Xin chào!" --out output/tts/vi.wav
python3 tts_gen.py --lang all --text-file lines.txt --out-dir output/tts
python3 tts_gen.py --list-voices
```

`tts_gen.py` gọi từng backend trong process riêng, tuần tự: Qwen chạy xong và thoát trước khi VieNeu được load. Có thể gọi trực tiếp từng môi trường:

```bash
.venv-qwen/bin/python tts_qwen.py --lang zh,ja,ko --text-file lines.txt --out-dir output/tts
.venv-vieneu/bin/python tts_vieneu.py --text-file lines_vi.txt --out-dir output/tts
```

### Clone giọng với Qwen3-TTS Base

Cần clip mẫu 3–10 giây, sạch, một người nói, và transcript khớp chính xác:

```bash
.venv-qwen/bin/python tts_qwen_clone.py \
  --lang ja \
  --text "こんにちは、英語の授業へようこそ。" \
  --ref-audio refs/teacher.wav \
  --ref-text "Hello, I am your teacher." \
  --out output/tts/ja.wav
```

- `--lang`: `en`, `zh`, `ja`, `ko` (Base không hỗ trợ `vi`).
- `--x-vector-only` nếu không có transcript; độ giống giọng sẽ thấp hơn.
- Cùng một clip mẫu dùng được cho nhiều câu; script chỉ build prompt một lần.

- Giọng mặc định: `Ryan` (en), `Serena` (zh), `Ono_Anna` (ja), `Sohee` (ko), `Mai Anh` (vi).
- Đổi giọng bằng `--voice`; Qwen hỗ trợ thêm `--instruct "Speak warmly and slowly"`.
- VRAM: Qwen ~5–6 GB, VieNeu ~1,1 GB — không load đồng thời.
- Cache model: `~/.cache/huggingface` (Qwen CustomVoice + Base ~8,6 GB, VieNeu ~0,3 GB).
- License: Qwen3-TTS và VieNeu-TTS đều Apache 2.0.
- Nếu dùng clone giọng với Qwen, cài thêm SoX: `sudo apt install sox`.

Lưu ý: `make_video.py` hiện vẫn dùng `espeak-ng`; phần TTS mới đang để riêng để nghe thử trước khi tích hợp.

## Cấu trúc script

- `SCENES`, `BOARDS`: danh sách phần học và nội dung trên bảng.
- Các lệnh `seg(...)`: kịch bản từng câu (người nói, câu tiếng Anh, phụ đề tiếng Việt, mục đang chỉ trên bảng, động tác tay).
- `VOICE`: giọng espeak-ng cho cô Lan (`T`) và Nam (`N`).
- `teacher()`, `draw_board()`, `draw_caption()`: vẽ nhân vật, bảng và phụ đề cho từng khung hình (PIL), rồi pipe sang ffmpeg.

Muốn làm bài khác: sửa `SCENES`, `BOARDS` và các dòng `seg(...)`.
