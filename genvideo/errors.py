"""Exception types shared by the genvideo pipeline."""

from __future__ import annotations


class GenVideoError(Exception):
    """Base class for all user-facing genvideo errors."""


class ValidationError(GenVideoError):
    """The episode JSON is malformed or internally inconsistent."""

    def __init__(self, errors: list[str], source: str = "<episode>") -> None:
        self.errors = list(errors)
        self.source = source
        super().__init__("\n".join(self.errors))

    def __str__(self) -> str:
        lines = [f"invalid episode: {self.source} ({len(self.errors)} error(s))"]
        lines.extend(f"  - {err}" for err in self.errors)
        return "\n".join(lines)


class TTSError(GenVideoError):
    """A TTS backend failed while producing a clip."""


class AudioError(GenVideoError):
    """An audio clip is missing, unreadable, or silent."""


class RenderError(GenVideoError):
    """Frame rendering or ffmpeg encoding failed."""
