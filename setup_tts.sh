#!/usr/bin/env bash
# Cài 2 môi trường TTS tách biệt cho genVideo.
# Yêu cầu: uv, Python 3.12, GPU NVIDIA (CUDA 12.8), ~12 GB đĩa trống.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-3.12}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Chưa có uv. Cài bằng: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

# 1) Qwen3-TTS: Anh / Trung / Nhật / Hàn
uv venv --python "$PYTHON" .venv-qwen
uv pip install --python .venv-qwen/bin/python -U qwen-tts soundfile \
  --constraint constraints-tts.txt

# 2) VieNeu-TTS v3 Turbo: Việt
uv venv --python "$PYTHON" .venv-vieneu
uv pip install --python .venv-vieneu/bin/python "vieneu[cuda]" \
  --constraint constraints-tts.txt

echo
for venv in .venv-qwen .venv-vieneu; do
  echo "== $venv =="
  "$venv/bin/python" - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda :", torch.version.cuda, "available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu  :", torch.cuda.get_device_name(0))
PY
done

echo
echo "Xong. Hai môi trường chạy riêng, không load cùng lúc:"
echo "  .venv-qwen/bin/python   tts_qwen.py   --lang en --text \"Hello!\" --out output/tts/en.wav"
echo "  .venv-vieneu/bin/python tts_vieneu.py --text \"Xin chào!\" --out output/tts/vi.wav"
echo "Hoặc dùng wrapper tuần tự:"
echo "  python3 tts_gen.py --lang all --text-file lines.txt --out-dir output/tts"
