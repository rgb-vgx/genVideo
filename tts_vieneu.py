#!/usr/bin/env python3
"""VieNeu-TTS backend: Vietnamese only.

Run with the VieNeu environment:
  .venv-vieneu/bin/python tts_vieneu.py --text "Xin chào!" --out output/tts/vi.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

DEFAULT_VOICE = "Mai Anh"

_tts = None


def get_tts():
    global _tts
    if _tts is None:
        from vieneu import Vieneu

        print("Loading VieNeu-TTS v3 Turbo ...", file=sys.stderr, flush=True)
        _tts = Vieneu()
    return _tts


def synthesize(text: str, out: Path, voice: str | None = None) -> Path:
    tts = get_tts()
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    audio = tts.infer(text, voice=voice or DEFAULT_VOICE)
    tts.save(audio, str(out))
    print(f"[vi] {out} ({time.time() - t0:.1f}s, 48000 Hz)", file=sys.stderr, flush=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="VieNeu-TTS for Vietnamese")
    p.add_argument("--text")
    p.add_argument("--text-file", help="UTF-8 file; one line = one output")
    p.add_argument("--out", help="Output WAV path (single text)")
    p.add_argument("--out-dir", default="output/tts")
    p.add_argument("--voice", default=DEFAULT_VOICE, help=f"VieNeu voice (default: {DEFAULT_VOICE})")
    p.add_argument("--list-voices", action="store_true")
    args = p.parse_args()

    if args.list_voices:
        for label, voice_id in get_tts().list_preset_voices():
            print(f"{voice_id:20s} {label}")
        return 0

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

    out_dir = Path(args.out_dir)
    for i, text in enumerate(texts):
        if args.out and len(texts) == 1:
            out = Path(args.out)
        elif len(texts) == 1:
            out = out_dir / "vi.wav"
        else:
            out = out_dir / f"vi_{i:03d}.wav"
        synthesize(text, out, voice=args.voice)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
