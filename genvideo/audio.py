"""Audio loading, silence trimming, mixing, and envelope extraction."""

from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from .errors import AudioError

SR = 22050


def _read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
            comptype = wav.getcomptype()
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioError(f"cannot read WAV {path}: {exc}") from exc

    if comptype != "NONE" or width != 2:
        raise AudioError(f"unsupported WAV encoding in {path}")
    if channels <= 0 or rate <= 0 or not frames:
        raise AudioError(f"empty WAV {path}")

    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _read_with_ffmpeg(path: Path, sr: int) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"cannot decode {path} with ffmpeg: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise AudioError(f"cannot decode {path} with ffmpeg: {detail or 'no output'}")
    return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0


def _resample(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(data) == 0:
        return data
    count = max(1, int(round(len(data) * target_rate / source_rate)))
    source_x = np.arange(len(data), dtype=np.float64)
    target_x = np.linspace(0.0, len(data) - 1.0, count)
    return np.interp(target_x, source_x, data).astype(np.float32)


def trim_silence(data: np.ndarray, sr: int = SR) -> np.ndarray:
    """Trim leading/trailing silence with a small guard band."""
    if len(data) == 0:
        raise AudioError("audio clip is empty")
    peak = float(np.max(np.abs(data)))
    if peak < 1e-4:
        raise AudioError("audio clip is silent")
    threshold = max(0.004, min(0.02, peak * 0.03))
    nonzero = np.where(np.abs(data) > threshold)[0]
    if len(nonzero) == 0:
        raise AudioError("audio clip is silent after thresholding")
    head = max(0, int(nonzero[0]) - int(0.010 * sr))
    tail = min(len(data), int(nonzero[-1]) + int(0.030 * sr))
    trimmed = data[head:tail]
    if len(trimmed) < int(0.02 * sr):
        raise AudioError("audio clip is too short after trimming silence")
    return trimmed.astype(np.float32, copy=False)


def load_clip(path: str | Path, sr: int = SR, *, trim: bool = True) -> np.ndarray:
    """Load any TTS WAV/MP3 as mono float32 at ``sr``, optionally trimmed."""
    file_path = Path(path)
    if not file_path.exists():
        raise AudioError(f"audio file does not exist: {file_path}")
    try:
        data, rate = _read_pcm16(file_path)
        data = _resample(data, rate, sr)
    except (AudioError, ValueError):
        data = _read_with_ffmpeg(file_path, sr)

    if len(data) == 0:
        raise AudioError(f"audio clip is empty: {file_path}")
    if trim:
        data = trim_silence(data, sr)
    return data


def envelope(track: np.ndarray, nframes: int, fps: int, sr: int = SR) -> np.ndarray:
    """Per-video-frame RMS envelope, normalised to the 90th percentile."""
    hop = max(1, sr // max(1, fps))
    count = min(nframes, max(0, math.ceil(len(track) / hop)))
    values = np.zeros(nframes, dtype=np.float32)
    if count:
        energies = np.array(
            [
                math.sqrt(float(np.mean(track[i * hop : (i + 1) * hop] ** 2)) + 1e-9)
                for i in range(count)
            ],
            dtype=np.float32,
        )
        active = energies[energies > 0.005]
        reference = float(np.percentile(active, 90)) if len(active) else 1.0
        values[:count] = np.clip(energies / max(reference, 1e-6), 0.0, 1.0)
        values[values < 0.08] = 0.0
    return values


def mix_timeline(timeline, *, sr: int = SR) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Mix per-character tracks and scene chimes into one float32 array."""
    total_samples = int(round(timeline.total * sr)) + sr
    character_ids = list(timeline.character_ids)
    tracks = {char_id: np.zeros(total_samples, dtype=np.float32) for char_id in character_ids}

    for cue in timeline.lines:
        track = tracks.setdefault(
            cue.character.id, np.zeros(total_samples, dtype=np.float32)
        )
        start = max(0, int(round(cue.start * sr)))
        end = min(total_samples, start + len(cue.audio))
        if end > start:
            track[start:end] += cue.audio[: end - start] * 0.9

    speech_peak = 0.0
    for track in tracks.values():
        speech_peak = max(speech_peak, float(np.max(np.abs(track))) if len(track) else 0.0)
    if speech_peak < 1e-4:
        raise AudioError("mixed speech is silent (all TTS clips are empty)")

    for chime_time in timeline.chimes:
        length = int(0.7 * sr)
        t = np.arange(length, dtype=np.float32) / sr
        tone = (
            np.sin(2 * np.pi * 784 * t) * np.exp(-t * 6)
            + 0.7
            * np.sin(2 * np.pi * 1175 * t)
            * np.exp(-np.maximum(t - 0.12, 0) * 6)
            * (t > 0.12)
        )
        start = max(0, int(round(chime_time * sr)))
        end = min(total_samples, start + length)
        if end > start:
            tone_slice = tone[: end - start] * 0.12
            # Add the chime to the first track (it is a global sound).
            if tracks:
                first = tracks[character_ids[0]]
                first[start:end] += tone_slice

    mix = np.zeros(total_samples, dtype=np.float32)
    for track in tracks.values():
        mix += track

    peak = float(np.max(np.abs(mix))) if len(mix) else 0.0
    if peak < 1e-4:
        raise AudioError("mixed audio is silent (all TTS clips are empty)")
    if peak > 0.98:
        scale = 0.98 / peak
        mix *= scale
        for track in tracks.values():
            track *= scale

    return mix, tracks


def write_wav(path: str | Path, data: np.ndarray, sr: int = SR) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(file_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())
    return file_path
