"""Deterministic timeline construction from validated lines and audio clips."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .errors import GenVideoError
from .schema import Character, Episode, Line, ResolvedLine, Scene
from .audio import SR

LEAD_IN = 0.9
SCENE_GAP = 0.6
TAIL = 0.8
DEFAULT_FPS = 24


@dataclass
class LineCue:
    scene_id: str
    line: Line
    character: Character
    resolved: ResolvedLine
    audio: np.ndarray
    show: float
    start: float
    end: float
    pause: float

    @property
    def duration(self) -> float:
        return len(self.audio) / SR

    @property
    def primary(self) -> str:
        return self.resolved.primary

    @property
    def secondary(self) -> str | None:
        return self.resolved.secondary


@dataclass
class SceneCue:
    scene: Scene
    show: float
    end: float
    lines: list[LineCue] = field(default_factory=list)


@dataclass
class Timeline:
    language: str
    source_language: str
    scenes: list[SceneCue]
    lines: list[LineCue]
    scene_show: dict[str, float]
    item_show: dict[tuple[str, int], float]
    chimes: list[float]
    total: float
    fps: int
    nframes: int
    character_ids: list[str]

    def current(self, t: float) -> LineCue:
        """The line whose reveal/show time is the latest one <= t."""
        if not self.lines:
            raise GenVideoError("timeline has no lines")
        current = self.lines[0]
        for cue in self.lines:
            if cue.show <= t:
                current = cue
            else:
                break
        return current

    def scene_cue(self, scene_id: str) -> SceneCue:
        for scene in self.scenes:
            if scene.scene.id == scene_id:
                return scene
        raise GenVideoError(f"unknown scene '{scene_id}' in timeline")

    def line_cue(self, scene_id: str, index: int) -> LineCue:
        scene = self.scene_cue(scene_id)
        if index < 0 or index >= len(scene.lines):
            raise GenVideoError(
                f"scene '{scene_id}' has no line at index {index}"
            )
        return scene.lines[index]


def build_timeline(
    episode: Episode,
    language: str,
    clips: dict[str, np.ndarray],
    *,
    fps: int = DEFAULT_FPS,
) -> Timeline:
    """Lay out scenes/lines using the same pacing as the legacy renderer."""
    if fps <= 0:
        raise GenVideoError("fps must be positive")
    if language not in episode.languages:
        raise GenVideoError(
            f"language '{language}' is not in episode.languages "
            f"({', '.join(episode.languages)})"
        )

    t = LEAD_IN
    chimes = [0.25]
    scene_show: dict[str, float] = {}
    item_show: dict[tuple[str, int], float] = {}
    scene_cues: list[SceneCue] = []
    line_cues: list[LineCue] = []

    for scene_index, scene in enumerate(episode.scenes):
        is_first = scene_index == 0
        if is_first:
            show = 0.0
            scene_show[scene.id] = 0.0
        else:
            t += SCENE_GAP
            show = t
            scene_show[scene.id] = t
            chimes.append(t)
            t += SCENE_GAP

        scene_cue = SceneCue(scene=scene, show=show, end=t)
        max_active = -1
        for line_index, line in enumerate(scene.lines):
            clip = clips.get(line.id)
            if clip is None:
                raise GenVideoError(
                    f"line '{line.id}' has no audio clip; run TTS first"
                )
            if len(clip) == 0:
                raise GenVideoError(f"line '{line.id}' has an empty audio clip")

            resolved = episode.resolve_line(line, language)
            cue_show = show if line_index == 0 else t
            start = t
            end = start + len(clip) / SR
            cue = LineCue(
                scene_id=scene.id,
                line=line,
                character=resolved.character,
                resolved=resolved,
                audio=clip,
                show=cue_show,
                start=start,
                end=end,
                pause=line.pause,
            )
            scene_cue.lines.append(cue)
            line_cues.append(cue)
            t = end + line.pause
            max_active = max(max_active, line.active)

        scene_cue.end = t
        scene_cues.append(scene_cue)

        # Reveal cards/dialog rows progressively, even if a script skips an
        # active index.  The first line that references index k or higher
        # controls when row/item k appears.
        if scene.board.type in {"cards", "repeat", "dialog"} and max_active >= 0:
            for item_index in range(max_active + 1):
                reveal = show
                for cue in scene_cue.lines:
                    if cue.line.active >= item_index:
                        reveal = cue.show
                        break
                item_show[(scene.id, item_index)] = reveal

    total = t + TAIL
    nframes = max(1, int(round(total * fps)))
    character_ids = [character.id for character in episode.characters]

    return Timeline(
        language=language,
        source_language=episode.source_language,
        scenes=scene_cues,
        lines=line_cues,
        scene_show=scene_show,
        item_show=item_show,
        chimes=chimes,
        total=total,
        fps=fps,
        nframes=nframes,
        character_ids=character_ids,
    )
