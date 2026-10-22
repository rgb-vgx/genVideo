#!/usr/bin/env python3
"""Qwen3-TTS backend: English, Chinese, Japanese, Korean.

Run with the Qwen environment:
  .venv-qwen/bin/python tts_qwen.py --lang en --text "Hello!" --out output/tts/en.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

LANGS = {
    "en": {"language": "English", "speaker": "Ryan"},
    "zh": {"language": "Chinese", "speaker": "Serena"},
    "ja": {"language": "Japanese", "speaker": "Ono_Anna"},
    "ko": {"language": "Korean", "speaker": "Sohee"},
}

SPEAKERS = {
    "en": ["Ryan", "Aiden"],
    "zh": ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric"],
    "ja": ["Ono_Anna"],
    "ko": ["Sohee"],
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


def synthesize(text: str, lang: str, out: Path, voice: str | None = None,
               instruct: str | None = None) -> Path:
    import soundfile as sf

    model = get_model()
    t0 = time.time()
    wavs, sr = model.generate_custom_voice(
        text=text,
        language=LANGS[lang]["language"],
        speaker=voice or LANGS[lang]["speaker"],
        instruct=instruct,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, wavs[0], sr)
    print(f"[{lang}] {out} ({time.time() - t0:.1f}s, {sr} Hz)", file=sys.stderr, flush=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Qwen3-TTS for en/zh/ja/ko")
    p.add_argument("--lang", help="en, zh, ja, ko (comma-separated)")
    p.add_argument("--text")
    p.add_argument("--text-file", help="UTF-8 file; one line = one output")
    p.add_argument("--out", help="Output WAV path (single text, single lang)")
    p.add_argument("--out-dir", default="output/tts")
    p.add_argument("--voice", help="Qwen speaker, e.g. Serena, Ryan, Ono_Anna, Sohee")
    p.add_argument("--instruct", help="Style instruction, e.g. 'Speak warmly and slowly'")
    p.add_argument("--list-voices", action="store_true")
    args = p.parse_args()

    if args.list_voices:
        for lang, speakers in SPEAKERS.items():
            print(f"{lang}: {', '.join(speakers)}")
        return 0

    if not args.lang:
        p.error("--lang is required")
    if not args.text and not args.text_file:
        p.error("pass --text or --text-file")

    langs = [x.strip() for x in args.lang.split(",") if x.strip()]
    for lang in langs:
        if lang not in LANGS:
            p.error(f"unsupported language for Qwen backend: {lang} (use en, zh, ja, ko)")

    texts: list[str] = []
    if args.text:
        texts = [args.text]
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            texts += [line.strip() for line in f if line.strip()]
    if not texts:
        p.error("no text to synthesize")

    out_dir = Path(args.out_dir)
    for lang in langs:
        for i, text in enumerate(texts):
            if args.out and len(langs) == 1 and len(texts) == 1:
                out = Path(args.out)
            elif len(texts) == 1:
                out = out_dir / f"{lang}.wav"
            else:
                out = out_dir / f"{lang}_{i:03d}.wav"
            synthesize(text, lang, out, voice=args.voice, instruct=args.instruct)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
