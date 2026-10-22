from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "lesson_min.json"


def example_data() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def tiny_data() -> dict:
    """Two short scenes, enough for a fast end-to-end CLI render."""
    return {
        "title": "Tiny Lesson",
        "template": "chalkboard",
        "source_language": "en",
        "languages": ["en", "vi"],
        "characters": [
            {
                "id": "teacher",
                "name": "Cô Lan",
                "color": "#2F6FA8",
                "appearance": {"hair": "#3F2A1E", "long_hair": True},
                "voices": {
                    "en": {"backend": "qwen", "voice_id": "Serena"},
                    "vi": {"backend": "vieneu", "voice_id": "Mai Anh"},
                },
            },
            {
                "id": "nam",
                "name": "Nam",
                "color": "#C96A2B",
                "appearance": {"hair": "#1E1E1E", "long_hair": False},
                "voices": {
                    "en": {"backend": "qwen", "voice_id": "Aiden"},
                    "vi": {"backend": "vieneu", "voice_id": "Hải Đăng"},
                },
            },
        ],
        "scenes": [
            {
                "id": "intro",
                "title": "Welcome",
                "subtitle": "Mở đầu",
                "board": {
                    "type": "title",
                    "kicker": "TEST",
                    "title": {"en": "Hello", "vi": "Xin chào"},
                    "sub": {"en": "A tiny lesson", "vi": "Bài học nhỏ"},
                },
                "lines": [
                    {
                        "id": "l1",
                        "character": "teacher",
                        "texts": {"en": "Hello!", "vi": "Xin chào!"},
                        "arm": "wave",
                        "pause": 0.2,
                        "active": -1,
                    }
                ],
            },
            {
                "id": "dialog",
                "title": "Talk",
                "subtitle": "Hội thoại",
                "board": {"type": "dialog"},
                "lines": [
                    {
                        "id": "l2",
                        "character": "teacher",
                        "texts": {"en": "How are you?", "vi": "Bạn khỏe không?"},
                        "arm": "down",
                        "pause": 0.2,
                        "active": 0,
                    },
                    {
                        "id": "l3",
                        "character": "nam",
                        "texts": {"en": "I am fine.", "vi": "Mình khỏe."},
                        "arm": "down",
                        "pause": 0.2,
                        "active": 1,
                    },
                ],
            },
        ],
    }


def clone(data: dict) -> dict:
    return copy.deepcopy(data)
