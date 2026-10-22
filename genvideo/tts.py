"""TTS orchestration: cache, batching, and sequential backend execution.

The renderer never imports torch.  Every backend is called as a subprocess in
its own virtualenv, one process at a time.  Qwen groups (``qwen`` and
``qwen_clone``) always run before VieNeu groups, so the two models are never
resident in VRAM at the same time.

Set ``GENVIDEO_TTS_MOCK=1`` (or pass ``mock=True`` to :func:`synthesize`) to
generate short deterministic test tones instead of loading a real model.  This
is used by the unit tests and is not a production backend.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import TTSError
from .schema import Episode, Voice

BACKEND_ORDER = {"qwen": 0, "qwen_clone": 1, "vieneu": 2}
MOCK_SAMPLE_RATE = 22050
DEFAULT_TIMEOUT = 1800


@dataclass(frozen=True)
class TTSRequest:
    line_id: str
    text: str
    language: str
    backend: str
    voice_id: str
    ref_audio: str
    ref_text: str
    instruct: str
    key: str


@dataclass
class TTSReport:
    clips: dict[str, Path]
    line_count: int
    unique_clips: int
    cached: int
    synthesized: int
    groups: int
    elapsed: float


def cache_key(
    text: str,
    language: str,
    backend: str,
    voice_id: str = "",
    ref_audio: str = "",
    ref_text: str = "",
    instruct: str = "",
) -> str:
    """Stable SHA-256 cache key for one spoken clip.

    The exact fields are part of the renderer contract; changing them
    invalidates every existing cache entry.
    """
    payload = {
        "text": text,
        "language": language,
        "backend": backend,
        "voice_id": voice_id or "",
        "ref_audio": ref_audio or "",
        "ref_text": ref_text or "",
        "instruct": instruct or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _request_for(line_id: str, text: str, language: str, voice: Voice) -> TTSRequest:
    key = cache_key(
        text=text,
        language=language,
        backend=voice.backend,
        voice_id=voice.voice_id,
        ref_audio=voice.ref_audio,
        ref_text=voice.ref_text,
        instruct=voice.instruct,
    )
    return TTSRequest(
        line_id=line_id,
        text=text,
        language=language,
        backend=voice.backend,
        voice_id=voice.voice_id,
        ref_audio=voice.ref_audio,
        ref_text=voice.ref_text,
        instruct=voice.instruct,
        key=key,
    )


def build_requests(episode: Episode, language: str) -> list[TTSRequest]:
    """Resolve every line to a spoken clip request for ``language``."""
    requests: list[TTSRequest] = []
    for scene in episode.scenes:
        for line in scene.lines:
            resolved = episode.resolve_line(line, language)
            requests.append(
                _request_for(
                    line.id,
                    resolved.spoken_text,
                    resolved.spoken_language,
                    resolved.voice,
                )
            )
    return requests


def _default_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _line_ids(requests: list[TTSRequest], limit: int = 8) -> str:
    ids = [r.line_id for r in requests]
    if len(ids) <= limit:
        return ", ".join(ids)
    return ", ".join(ids[:limit]) + f", ... ({len(ids)} lines)"


def _wav_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 44:
        return False
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() > 0 and wav.getframerate() > 0
    except Exception:
        # Non-PCM WAV is still accepted here; the audio loader converts it.
        return path.stat().st_size > 44


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        text = "..." + text[-limit:]
    return text.replace("\n", " / ")


def _venv_python(root: Path, backend: str) -> Path:
    if backend in {"qwen", "qwen_clone"}:
        venv = Path(os.environ.get("QWEN_VENV", root / ".venv-qwen"))
    else:
        venv = Path(os.environ.get("VIENEU_VENV", root / ".venv-vieneu"))
    python = venv / "bin" / "python"
    if not python.exists():
        python = venv / "Scripts" / "python.exe"
    if not python.exists():
        raise TTSError(
            f"TTS backend '{backend}' is not installed: {python} is missing. "
            f"Run ./setup_tts.sh in {root}."
        )
    return python


def _group_requests(
    requests: list[TTSRequest],
) -> list[tuple[tuple, list[TTSRequest]]]:
    """Group misses by voice/model so each backend process loads its model once."""
    groups: dict[tuple, list[TTSRequest]] = {}
    first_seen: dict[tuple, int] = {}
    for index, req in enumerate(requests):
        key = (
            req.backend,
            req.language,
            req.voice_id,
            req.ref_audio,
            req.ref_text,
            req.instruct,
        )
        groups.setdefault(key, []).append(req)
        first_seen.setdefault(key, index)
    return sorted(
        groups.items(),
        key=lambda item: (
            BACKEND_ORDER.get(item[0][0], 99),
            first_seen[item[0]],
        ),
    )


def _group_label(group: list[TTSRequest]) -> str:
    req = group[0]
    bits = [req.backend, f"lang={req.language}"]
    if req.voice_id:
        bits.append(f"voice={req.voice_id}")
    if req.ref_audio:
        bits.append(f"ref={Path(req.ref_audio).name}")
    return " ".join(bits)


def _run_group(
    group: list[TTSRequest],
    *,
    root: Path,
    cache_dir: Path,
    group_dir: Path,
    timeout: int,
    log: Callable[[str], None],
) -> None:
    # The same clip can be shared by several lines; synthesize it once.
    unique: list[TTSRequest] = []
    seen: set[str] = set()
    for req in group:
        if req.key not in seen:
            seen.add(req.key)
            unique.append(req)

    group_dir.mkdir(parents=True, exist_ok=True)
    text_file = group_dir / "texts.txt"
    text_file.write_text(
        "\n".join(req.text for req in unique) + "\n", encoding="utf-8"
    )
    out_dir = group_dir / "out"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    req = unique[0]
    python = _venv_python(root, req.backend)
    if req.backend == "qwen":
        script = root / "tts_qwen.py"
        cmd = [
            str(python),
            str(script),
            "--lang",
            req.language,
            "--text-file",
            str(text_file),
            "--out-dir",
            str(out_dir),
            "--voice",
            req.voice_id,
        ]
        if req.instruct:
            cmd += ["--instruct", req.instruct]
    elif req.backend == "qwen_clone":
        script = root / "tts_qwen_clone.py"
        cmd = [
            str(python),
            str(script),
            "--lang",
            req.language,
            "--text-file",
            str(text_file),
            "--out-dir",
            str(out_dir),
            "--ref-audio",
            req.ref_audio,
            "--ref-text",
            req.ref_text,
        ]
        if not req.ref_text:
            cmd.append("--x-vector-only")
    elif req.backend == "vieneu":
        script = root / "tts_vieneu.py"
        cmd = [
            str(python),
            str(script),
            "--text-file",
            str(text_file),
            "--out-dir",
            str(out_dir),
            "--voice",
            req.voice_id,
        ]
    else:  # pragma: no cover - schema rejects this first
        raise TTSError(f"unknown TTS backend '{req.backend}'")

    if not script.exists():
        raise TTSError(f"TTS backend script not found: {script}")

    log(f"[tts] {_group_label(group)}: {len(unique)} clip(s)")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TTSError(
            f"TTS timed out after {timeout}s for line(s) {_line_ids(unique)} "
            f"(language={req.language}, backend={req.backend})"
        ) from exc
    except OSError as exc:
        raise TTSError(
            f"could not start TTS backend for line(s) {_line_ids(unique)} "
            f"(language={req.language}, backend={req.backend}): {exc}"
        ) from exc

    if proc.returncode != 0:
        detail = _tail(proc.stderr) or _tail(proc.stdout) or "no stderr output"
        raise TTSError(
            f"TTS failed for line(s) {_line_ids(unique)} "
            f"(language={req.language}, backend={req.backend}, "
            f"voice={req.voice_id or req.ref_audio or '-'}): "
            f"backend exited {proc.returncode}: {detail}"
        )

    outputs = _collect_outputs(out_dir, unique, req)
    for source, clip_req in zip(outputs, unique):
        if not _wav_ok(source):
            detail = _tail(proc.stderr) or _tail(proc.stdout)
            raise TTSError(
                f"TTS produced an empty/missing clip for line '{clip_req.line_id}' "
                f"(language={clip_req.language}, backend={clip_req.backend}): "
                f"{source}"
                + (f": {detail}" if detail else "")
            )
        destination = cache_dir / f"{clip_req.key}.wav"
        _atomic_copy(source, destination)

    log(
        f"[tts] {_group_label(group)}: done in {time.monotonic() - started:.1f}s"
    )


def _expected_output(out_dir: Path, req: TTSRequest, index: int, count: int) -> Path:
    if req.backend == "vieneu":
        return out_dir / ("vi.wav" if count == 1 else f"vi_{index:03d}.wav")
    return out_dir / (
        f"{req.language}.wav" if count == 1 else f"{req.language}_{index:03d}.wav"
    )


def _collect_outputs(
    out_dir: Path, unique: list[TTSRequest], req: TTSRequest
) -> list[Path]:
    expected = [
        _expected_output(out_dir, req, idx, len(unique))
        for idx in range(len(unique))
    ]
    if all(path.exists() for path in expected):
        return expected

    # Be tolerant of a backend that adds a suffix (e.g. timestamps). If the
    # number of WAVs matches, map them in filename order to the text order.
    found = sorted(out_dir.glob("*.wav"))
    if len(found) == len(unique):
        return found

    missing = [str(path) for path in expected if not path.exists()]
    raise TTSError(
        f"TTS backend did not produce the expected output for line(s) "
        f"{_line_ids(unique)} (language={req.language}, backend={req.backend}): "
        f"missing {', '.join(missing)}; found {len(found)} wav file(s) "
        f"in {out_dir}"
    )


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(
        f".{destination.name}.{os.getpid()}.tmp"
    )
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _mock_clip(path: Path, text: str, language: str) -> None:
    """Write a short deterministic tone (test-only TTS backend)."""
    digest = hashlib.sha1(f"{text}|{language}".encode("utf-8")).hexdigest()
    rng = np.random.default_rng(int(digest[:8], 16))
    duration = min(2.4, max(0.45, 0.22 + 0.032 * len(text)))
    sr = MOCK_SAMPLE_RATE
    t = np.arange(int(duration * sr), dtype=np.float32) / sr
    base = 170.0 + float(rng.integers(0, 90))
    wave_data = (
        0.30 * np.sin(2 * np.pi * base * t)
        + 0.12 * np.sin(2 * np.pi * base * 2.01 * t)
        + 0.05 * np.sin(2 * np.pi * base * 3.03 * t)
    )
    attack = np.clip(t / 0.02, 0, 1)
    release = np.clip((duration - t) / 0.08, 0, 1)
    wave_data = wave_data * attack * release
    wave_data = 0.55 * wave_data / max(1e-6, float(np.max(np.abs(wave_data))))
    pcm = (wave_data * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())


def synthesize(
    episode: Episode,
    language: str,
    *,
    root: Path,
    cache_dir: Path,
    work_dir: Path,
    force: bool = False,
    mock: bool = False,
    timeout: int | None = None,
    log: Callable[[str], None] | None = None,
) -> TTSReport:
    """Ensure every line has a cached WAV clip and return the line -> path map."""
    log = log or _default_log
    started = time.monotonic()
    requests = build_requests(episode, language)
    cache_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    # Keep test tones out of the production cache: the cache key is identical,
    # so sharing a directory would let a later real render reuse fake audio.
    clip_cache = cache_dir / "mock" if mock else cache_dir
    clip_cache.mkdir(parents=True, exist_ok=True)

    # Deduplicate by cache key: identical text/voice lines share one clip.
    unique_by_key: dict[str, TTSRequest] = {}
    for req in requests:
        unique_by_key.setdefault(req.key, req)

    cached: list[TTSRequest] = []
    missing: list[TTSRequest] = []
    for req in unique_by_key.values():
        path = clip_cache / f"{req.key}.wav"
        if not force and _wav_ok(path):
            cached.append(req)
        else:
            missing.append(req)

    log(
        f"[tts] {len(requests)} line(s), {len(unique_by_key)} unique clip(s): "
        f"{len(cached)} cached, {len(missing)} to synthesize"
    )

    synthesized = 0
    groups = 0
    if missing and mock:
        log("[tts] mock backend enabled (GENVIDEO_TTS_MOCK=1)")
        for req in missing:
            path = clip_cache / f"{req.key}.wav"
            _mock_clip(path, req.text, req.language)
            log(f"[tts] mock line '{req.line_id}' ({req.language}) -> {path.name}")
            synthesized += 1
    elif missing:
        if timeout is None:
            try:
                timeout = int(os.environ.get("GENVIDEO_TTS_TIMEOUT", DEFAULT_TIMEOUT))
            except ValueError:
                timeout = DEFAULT_TIMEOUT
        for group_index, (_, group) in enumerate(_group_requests(missing)):
            groups += 1
            _run_group(
                group,
                root=root,
                cache_dir=clip_cache,
                group_dir=work_dir / "tts" / f"group_{group_index:02d}",
                timeout=timeout,
                log=log,
            )
            synthesized += len({req.key for req in group})

    clips: dict[str, Path] = {}
    for req in requests:
        path = clip_cache / f"{req.key}.wav"
        if not _wav_ok(path):
            raise TTSError(
                f"missing TTS clip for line '{req.line_id}' "
                f"(language={req.language}, backend={req.backend}): {path}"
            )
        clips[req.line_id] = path

    elapsed = time.monotonic() - started
    log(
        f"[tts] ready: {len(unique_by_key)} clip(s) in {elapsed:.1f}s "
        f"({len(cached)} cached, {synthesized} synthesized)"
    )
    return TTSReport(
        clips=clips,
        line_count=len(requests),
        unique_clips=len(unique_by_key),
        cached=len(cached),
        synthesized=synthesized,
        groups=groups,
        elapsed=elapsed,
    )
