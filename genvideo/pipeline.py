"""High-level preparation: TTS -> audio loading -> timeline -> mix."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import load_clip, mix_timeline, write_wav
from .errors import AudioError
from .schema import Episode
from .timeline import Timeline, build_timeline
from .tts import TTSReport, synthesize


@dataclass
class PreparedEpisode:
    episode: Episode
    language: str
    timeline: Timeline
    clips: dict[str, np.ndarray]
    mix: np.ndarray
    tracks: dict[str, np.ndarray]
    mix_path: Path
    tts_report: TTSReport


def prepare_episode(
    episode: Episode,
    language: str,
    *,
    root: Path,
    cache_dir: Path,
    work_dir: Path,
    force: bool = False,
    mock: bool = False,
    fps: int = 24,
    log: Callable[[str], None] | None = None,
) -> PreparedEpisode:
    """Run TTS (or reuse cache), load clips, then build the timeline and mix."""
    log = log or (lambda message: None)
    work_dir.mkdir(parents=True, exist_ok=True)

    report = synthesize(
        episode,
        language,
        root=root,
        cache_dir=cache_dir,
        work_dir=work_dir,
        force=force,
        mock=mock,
        log=log,
    )

    clips: dict[str, np.ndarray] = {}
    for scene in episode.scenes:
        for line in scene.lines:
            path = report.clips.get(line.id)
            if path is None:
                raise AudioError(f"line '{line.id}': TTS did not return a clip")
            try:
                clips[line.id] = load_clip(path)
            except AudioError as exc:
                raise AudioError(
                    f"line '{line.id}' (language={language}): {exc}"
                ) from exc

    timeline = build_timeline(episode, language, clips, fps=fps)
    log(
        f"[timeline] {timeline.total:.1f}s, {timeline.nframes} frame(s) "
        f"at {fps} fps, {len(timeline.lines)} line(s), "
        f"{len(timeline.scenes)} scene(s)"
    )

    mix, tracks = mix_timeline(timeline)
    mix_path = write_wav(work_dir / "mix.wav", mix)
    log(f"[audio] mixed -> {mix_path}")

    return PreparedEpisode(
        episode=episode,
        language=language,
        timeline=timeline,
        clips=clips,
        mix=mix,
        tracks=tracks,
        mix_path=mix_path,
        tts_report=report,
    )
