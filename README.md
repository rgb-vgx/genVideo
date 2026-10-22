# genVideo

Render bài giảng hoạt hình 1280×720 / 24 fps từ một file JSON: cô giáo bên
trái, bảng đen bên phải, phụ đề hai ngôn ngữ, giọng TTS theo từng nhân vật.
Pipeline mới không dùng `espeak-ng` và không hard-code kịch bản.

Output mẫu (sinh bởi các lệnh bên dưới):

- [`output/service_en.mp4`](output/service_en.mp4) — bản tiếng Anh, Qwen3-TTS
- [`output/service_vi.mp4`](output/service_vi.mp4) — bản tiếng Việt, VieNeu-TTS
- [`output/english_greetings_demo.mp4`](output/english_greetings_demo.mp4) — demo cũ
  của `make_video.py` (legacy)

## Yêu cầu

- Python 3.12, `ffmpeg` / `ffprobe`
- `pillow`, `numpy` (xem `requirements.txt`)
- Hai môi trường TTS có sẵn: `.venv-qwen` (Qwen3-TTS) và `.venv-vieneu`
  (VieNeu-TTS). Nếu chưa có, chạy `bash setup_tts.sh` (cần GPU NVIDIA, ~12 GB
  đĩa; model cache nằm trong `~/.cache/huggingface`).
- GPU: RTX 3060 12 GB trở lên. Qwen và VieNeu **không bao giờ chạy đồng thời**.

## Chạy nhanh

```bash
# Kiểm tra JSON và voice coverage
python -m genvideo validate examples/lesson_min.json
python -m genvideo validate examples/lesson_min.json --language en --check-files

# Render hai ngôn ngữ
python -m genvideo render examples/lesson_min.json --language en --out output/service_en.mp4
python -m genvideo render examples/lesson_min.json --language vi --out output/service_vi.mp4

# Xem trước vài khung hình
python -m genvideo preview examples/lesson_min.json --language en --at 3,30 \
  --out-dir build/preview
```

Nếu máy không có lệnh `python`, dùng `python3` thay thế. Lần render đầu sẽ load
model và sinh TTS (khoảng 20–60 giây trên RTX 3060); các lần sau dùng cache
`build/cache/tts` và chỉ còn thời gian vẽ/encode.

## CLI

```text
python -m genvideo validate <episode.json> [--language L] [--check-files]
python -m genvideo render   <episode.json> --language L --out <file.mp4>
                            [--work-dir DIR] [--keep-work] [--force]
                            [--cache-dir DIR] [--fps N] [--crf N] [--preset NAME]
python -m genvideo preview  <episode.json> --language L --at 3,30
                            [--out-dir DIR] [--work-dir DIR] [--keep-work]
                            [--force] [--cache-dir DIR] [--fps N]
```

- Exit code `0` khi thành công, khác `0` khi lỗi.
- Progress (`[tts]`, `[timeline]`, `[render]`) in ra stderr; kết quả và thời
  gian in ra stdout.
- `--work-dir` giữ file tạm; `--keep-work` giữ ở
  `build/work/<episode>_<language>`.
- `--force` bỏ qua cache TTS và sinh lại toàn bộ clip.

## JSON episode

Schema đầy đủ: [`docs/episode-schema.md`](docs/episode-schema.md). Ví dụ chạy
được: [`examples/lesson_min.json`](examples/lesson_min.json), gồm 4 scene
`title`, `cards`, `dialog`, `repeat` và 2 nhân vật.

Điểm chính:

- Nhân vật đầu tiên trong `characters` là giáo viên; hỗ trợ thêm 1–3 nhân vật
  hội thoại.
- `voices` là map `language -> profile` (hoặc list profile có `language` như
  CMS).
- Backend: `qwen`, `qwen_clone` cho `en/zh/ja/ko`; `vieneu` cho `vi`.
- Thiếu bản dịch cho ngôn ngữ đích thì fallback về `source_language` (dùng cả
  text và voice nguồn).
- Board: `title` (kicker/title/sub/stars), `cards` (items + icon), `dialog`
  (bong bóng hội thoại từ `lines`), `repeat` (items + “Your turn!”).
- `active` là chỉ số item/line đang hiển thị; `repeat: true` + `pause` dài để
  hiện đồng hồ “Your turn!”.

## TTS và cache

| Ngôn ngữ | Backend | Môi trường |
| --- | --- | --- |
| `en`, `zh`, `ja`, `ko` | Qwen3-TTS CustomVoice / Base clone | `.venv-qwen` |
| `vi` | VieNeu-TTS v3 Turbo | `.venv-vieneu` |

- Renderer gọi `tts_qwen.py`, `tts_qwen_clone.py`, `tts_vieneu.py` bằng
  `subprocess`, không import `torch`.
- Line được nhóm theo `(backend, language, voice_id/ref_audio, ref_text,
  instruct)` để mỗi process chỉ load model một lần cho cả nhóm.
- Thứ tự chạy: toàn bộ Qwen/Qwen clone xong và thoát, sau đó mới đến VieNeu.
  Không load hai model cùng lúc.
- Cache mặc định: `build/cache/tts/<sha256>.wav`. Key gồm đúng các trường
  `text, language, backend, voice_id, ref_audio, ref_text, instruct`.
- Line đã có cache thì bỏ qua TTS; `--force` để sinh lại.
- Lỗi TTS báo rõ line id, language, backend và voice/ref.
- `GENVIDEO_TTS_MOCK=1` sinh tone test (không cần GPU), lưu riêng trong
  `build/cache/tts/mock/` để không lẫn với cache thật.

Có thể gọi trực tiếp từng backend như cũ:

```bash
.venv-qwen/bin/python tts_qwen.py --lang en --text "Hello!" --out output/tts/en.wav
.venv-vieneu/bin/python tts_vieneu.py --text "Xin chào!" --out output/tts/vi.wav
```

## Renderer

- 1280×720, 24 fps, H.264 + AAC, `+faststart`.
- Giữ style cũ: bảng đen, cô giáo bên trái, phụ đề dưới; code vẽ được chuyển
  từ `make_video.py` sang `genvideo/render.py` và tham số hoá theo nhân vật.
- `dialog` vẽ mặt, màu tóc/áo và tên của từng nhân vật.
- Phụ đề: dòng chính là ngôn ngữ đích; dòng phụ là `source_language` nếu khác.
- Audio: mix track theo nhân vật, trim silence từng clip, chèn chime chuyển
  cảnh; video dùng `-shortest`.

## Test

```bash
python -m unittest discover -s tests -t . -v
```

Không cần GPU hay model. Test dùng TTS mock, kiểm tra validate JSON, fallback,
timeline/audio duration, cache key ổn định, cache reuse, `--help`, và render +
preview end-to-end bằng ffprobe/volumedetect.

## Cấu trúc

```text
genvideo/
  __init__.py
  __main__.py      # python -m genvideo
  cli.py           # validate / render / preview
  schema.py        # dataclass + validation + fallback
  tts.py           # subprocess backends, grouping, cache
  audio.py         # load/trim/resample/mix/envelope
  timeline.py      # scene/line timing
  pipeline.py      # TTS -> audio -> timeline
  render.py        # PIL drawing + ffmpeg
examples/lesson_min.json
tests/
docs/episode-schema.md
```

`make_video.py`, `tts_qwen.py`, `tts_qwen_clone.py`, `tts_vieneu.py`,
`tts_gen.py` vẫn được giữ. `make_video.py` là legacy hard-code và vẫn dùng
`espeak-ng`; pipeline mới không gọi nó.

## Tích hợp CMS

Interface ổn định cho worker CMS:

```bash
python -m genvideo render <episode.json> --language <code> --out <path>
```

CMS chưa bị sửa trong milestone này. Worker có thể serialize project detail
thành episode JSON (map `voices[]` sang map/list, `character_id` sang
`character`, `source_language = languages[0]` nếu chưa có), chạy lệnh trên và
đọc stderr để cập nhật progress/log. Renderer không cần import CMS và không
chiếm GPU trong process HTTP. Xem bảng mapping trong
[`docs/episode-schema.md`](docs/episode-schema.md#cms-mapping).
