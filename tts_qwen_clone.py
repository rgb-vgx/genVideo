#!/usr/bin/env python3
"""Qwen3-TTS Base: clone a voice from a short reference clip.

Run with the Qwen environment:
  .venv-qwen/bin/python tts_qwen_clone.py \
    --lang ja --text "こんにちは" \
    --ref-audio refs/teacher.wav --ref-text "Hello, I am your teacher." \
    --out output/tts/ja.wav

The reference clip should be 3-10 seconds, clean, one speaker. `--ref-text`
must match the reference audio exactly; use `--x-vector-only` to skip it
(lower similarity).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

LANGS = {
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

_model = None


def get_model():
    global _model
    if _model is None:
        import torch
        from qwen_tts import Qwen3TTSModel

        print(f"Loading {MODEL} ...", file=sys.stderr, flush=True)
        _model = Qwen3TTSModel.from_pretrained(
            MODEL,
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
    return _model


def main() -> int:
    p = argparse.ArgumentParser(description="Qwen3-TTS voice cloning for en/zh/ja/ko")
    p.add_argument("--lang", required=True, choices=sorted(LANGS))
    p.add_argument("--text", help="Text to synthesize")
    p.add_argument("--text-file", help="UTF-8 file; one line = one output")
    p.add_argument("--ref-audio", required=True, help="3-10s reference WAV/MP3")
    p.add_argument("--ref-text", required=True, help="Exact transcript of the reference clip")
    p.add_argument("--x-vector-only", action="store_true", help="Use speaker embedding only (no ref text)")
    p.add_argument("--out", help="Output WAV (single text)")
    p.add_argument("--out-dir", default="output/tts")
    args = p.parse_args()

    if not args.text and not args.text_file:
        p.error("pass --text or --text-file")

    texts: list[str] = []
    if args.text:
        texts = [args.text]
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            texts += [line.strip() for line in f if line.strip()]
    if not texts:
        p.error("no text to synthesize")

    import soundfile as sf

    model = get_model()
    print("building clone prompt ...", file=sys.stderr, flush=True)
    prompt = model.create_voice_clone_prompt(
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        x_vector_only_mode=args.x_vector_only,
    )

    out_dir = Path(args.out_dir)
    for i, text in enumerate(texts):
        if args.out and len(texts) == 1:
            out = Path(args.out)
        elif len(texts) == 1:
            out = out_dir / f"{args.lang}.wav"
        else:
            out = out_dir / f"{args.lang}_{i:03d}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=LANGS[args.lang],
            voice_clone_prompt=prompt,
        )
        sf.write(out, wavs[0], sr)
        print(f"[{args.lang}] {out} ({time.time() - t0:.1f}s, {sr} Hz)", file=sys.stderr, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
