#!/usr/bin/env python3
"""Multilingual TTS wrapper for genVideo.

Each backend runs in its own virtualenv and its own process, one at a time:
  en / zh / ja / ko -> .venv-qwen    + tts_qwen.py
  vi                -> .venv-vieneu  + tts_vieneu.py

Examples:
  python3 tts_gen.py --lang en --text "Hello!" --out output/tts/en.wav
  python3 tts_gen.py --lang vi --text "Xin chào!" --out output/tts/vi.wav
  python3 tts_gen.py --lang all --text-file lines.txt --out-dir output/tts
  python3 tts_gen.py --list-voices
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QWEN_VENV = Path(os.environ.get("QWEN_VENV", ROOT / ".venv-qwen"))
VIENEU_VENV = Path(os.environ.get("VIENEU_VENV", ROOT / ".venv-vieneu"))

QWEN_LANGS = {"en", "zh", "ja", "ko"}
ALL_LANGS = ["en", "zh", "ja", "ko", "vi"]


def run(venv: Path, script: str, args: list[str]) -> None:
    python = venv / "bin" / "python"
    if not python.exists():
        raise SystemExit(
            f"Không thấy {python}. Chạy ./setup_tts.sh để tạo hai môi trường "
            f"({QWEN_VENV.name}, {VIENEU_VENV.name})."
        )
    cmd = [str(python), str(ROOT / script), *args]
    print("+", " ".join(cmd), file=sys.stderr, flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate multilingual narration (Qwen3-TTS + VieNeu-TTS)")
    p.add_argument("--lang", help="en, zh, ja, ko, vi, or 'all'")
    p.add_argument("--text")
    p.add_argument("--text-file", help="UTF-8 file; one line = one output")
    p.add_argument("--out", help="Output WAV path (single language, single text)")
    p.add_argument("--out-dir", default="output/tts")
    p.add_argument("--voice", help="Qwen speaker or VieNeu voice id")
    p.add_argument("--instruct", help="Qwen style instruction")
    p.add_argument("--list-voices", action="store_true")
    args = p.parse_args()

    if args.list_voices:
        run(QWEN_VENV, "tts_qwen.py", ["--list-voices"])
        run(VIENEU_VENV, "tts_vieneu.py", ["--list-voices"])
        return 0

    if not args.lang:
        p.error("--lang is required (or use --list-voices)")
    if not args.text and not args.text_file:
        p.error("pass --text or --text-file")

    langs = ALL_LANGS if args.lang == "all" else [x.strip() for x in args.lang.split(",") if x.strip()]
    unknown = [x for x in langs if x not in ALL_LANGS]
    if unknown:
        p.error(f"unsupported language(s): {', '.join(unknown)}")

    if len(langs) > 1 and args.out:
        p.error("--out chỉ dùng cho một ngôn ngữ; dùng --out-dir khi chạy nhiều ngôn ngữ")

    common: list[str] = []
    if args.text:
        common += ["--text", args.text]
    if args.text_file:
        common += ["--text-file", args.text_file]
    common += ["--out-dir", args.out_dir]
    if args.out:
        common += ["--out", args.out]

    qwen_langs = [x for x in langs if x in QWEN_LANGS]
    if qwen_langs:
        qargs = ["--lang", ",".join(qwen_langs), *common]
        if args.voice:
            qargs += ["--voice", args.voice]
        if args.instruct:
            qargs += ["--instruct", args.instruct]
        run(QWEN_VENV, "tts_qwen.py", qargs)

    if "vi" in langs:
        vargs = list(common)
        # --voice chỉ áp cho VieNeu khi chạy riêng tiếng Việt; khi chạy "all"
        # thì --voice được hiểu là speaker của Qwen.
        if args.voice and len(langs) == 1:
            vargs += ["--voice", args.voice]
        run(VIENEU_VENV, "tts_vieneu.py", vargs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
