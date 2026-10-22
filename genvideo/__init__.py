"""JSON-driven lesson video renderer for genVideo."""

from __future__ import annotations

from .errors import AudioError, GenVideoError, RenderError, TTSError, ValidationError
from .schema import Episode, load_episode, parse_episode

__all__ = [
    "AudioError",
    "Episode",
    "GenVideoError",
    "RenderError",
    "TTSError",
    "ValidationError",
    "load_episode",
    "parse_episode",
]

__version__ = "0.1.0"
