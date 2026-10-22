"""Episode schema, validation, and text/voice resolution.

The JSON contract is intentionally close to the Zenford CMS entities, with a
few conveniences so the renderer can be wired to the CMS without an adapter:

* character ids and scene/line ids may be strings or integers;
* ``character.voices`` may be a ``{language: profile}`` map (canonical) or the
  CMS list of voice profiles, each carrying its own ``language`` field;
* a line may point at a character with ``character`` or ``character_id`` (and
  either the id or the display name is accepted);
* board text fields may be a plain string (meaning "source language") or a
  ``{language: text}`` map.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import GenVideoError, ValidationError

BACKENDS = {"qwen", "qwen_clone", "vieneu"}
QWEN_LANGUAGES = {"en", "zh", "ja", "ko"}
BOARD_TYPES = {"title", "cards", "dialog", "repeat"}
ARMS = {"down", "point", "wave"}
ICONS = {"bubble", "sun", "sunrise", "moon", "q", "a", "note", "star"}

DEFAULT_QWEN_SPEAKERS = {
    "en": "Ryan",
    "zh": "Serena",
    "ja": "Ono_Anna",
    "ko": "Sohee",
}
DEFAULT_VIENEU_VOICE = "Mai Anh"
DEFAULT_COLOR = "#2F6FA8"
DEFAULT_HAIR = "#3F2A1E"
SUPPORTED_TEMPLATES = {"chalkboard"}

_LANG_RE = re.compile(r"^[a-z]{2,3}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- models
@dataclass(frozen=True)
class Voice:
    backend: str
    voice_id: str = ""
    ref_audio: str = ""
    ref_text: str = ""
    instruct: str = ""


@dataclass
class Character:
    id: str
    name: str
    color: str = DEFAULT_COLOR
    hair: str = DEFAULT_HAIR
    long_hair: bool = True
    voices: dict[str, Voice] = field(default_factory=dict)


@dataclass
class BoardItem:
    texts: dict[str, str]
    icon: str = "bubble"


@dataclass
class Board:
    type: str
    kicker: str = ""
    title: dict[str, str] = field(default_factory=dict)
    sub: dict[str, str] = field(default_factory=dict)
    stars: bool = False
    items: list[BoardItem] = field(default_factory=list)


@dataclass
class Line:
    id: str
    character_id: str
    texts: dict[str, str]
    arm: str = "point"
    pause: float = 0.4
    active: int = -1
    repeat: bool = False
    sort_order: int = 0


@dataclass
class Scene:
    id: str
    title: str
    subtitle: str
    board: Board
    lines: list[Line] = field(default_factory=list)
    sort_order: int = 0


@dataclass(frozen=True)
class ResolvedLine:
    character: Character
    primary: str
    secondary: str | None
    spoken_text: str
    spoken_language: str
    voice: Voice


@dataclass
class Episode:
    title: str
    template: str
    source_language: str
    languages: list[str]
    characters: list[Character]
    scenes: list[Scene]
    path: Path | None = None

    @property
    def characters_by_id(self) -> dict[str, Character]:
        return {c.id: c for c in self.characters}

    @property
    def teacher(self) -> Character:
        """The first character is the on-screen teacher (legacy convention)."""
        return self.characters[0]

    def text_pair(self, texts: dict[str, str], language: str) -> tuple[str, str | None]:
        """Return the target-language text and the source-language subtitle."""
        primary = texts.get(language) or texts.get(self.source_language, "")
        if language == self.source_language:
            return primary, None
        secondary = texts.get(self.source_language)
        if not secondary or secondary == primary:
            secondary = None
        return primary, secondary

    def resolve_line(self, line: Line, language: str) -> ResolvedLine:
        """Resolve display text, spoken text, and voice for one line.

        Missing translations fall back to ``source_language``.  A fallback
        line is spoken with the source-language voice so the audio and the
        caption always match.
        """
        if language not in self.languages:
            raise GenVideoError(
                f"language '{language}' is not in episode.languages "
                f"({', '.join(self.languages)})"
            )

        character = self.characters_by_id.get(line.character_id)
        if character is None:
            raise GenVideoError(
                f"line '{line.id}': unknown character '{line.character_id}'"
            )

        primary, secondary = self.text_pair(line.texts, language)
        spoken_language = language if language in line.texts else self.source_language
        spoken_text = line.texts.get(spoken_language)
        if not spoken_text:
            raise GenVideoError(
                f"line '{line.id}' has no text for '{spoken_language}' "
                f"and source_language '{self.source_language}'"
            )

        voice = character.voices.get(spoken_language)
        if voice is None:
            available = ", ".join(sorted(character.voices)) or "none"
            raise GenVideoError(
                f"line '{line.id}' (language={spoken_language}, "
                f"character={character.id}): no voice profile for "
                f"'{spoken_language}' (available: {available})"
            )

        return ResolvedLine(
            character=character,
            primary=primary,
            secondary=secondary,
            spoken_text=spoken_text,
            spoken_language=spoken_language,
            voice=voice,
        )


# --------------------------------------------------------------------------- helpers
def _normalise_text(value: str) -> str:
    """Collapse whitespace so a line always fits a single caption/TTS line."""
    return " ".join(value.split())


def _error(errors: list[str], ctx: str, message: str) -> None:
    errors.append(f"{ctx}: {message}")


def _as_id(value: Any, ctx: str, errors: list[str]) -> str | None:
    if isinstance(value, bool) or value is None:
        _error(errors, ctx, "must be a string or integer id")
        return None
    if isinstance(value, (str, int)):
        text = str(value).strip()
        if not text:
            _error(errors, ctx, "must not be empty")
            return None
        return text
    _error(errors, ctx, "must be a string or integer id")
    return None


def _as_str(
    value: Any,
    ctx: str,
    errors: list[str],
    *,
    required: bool = False,
    default: str = "",
) -> str:
    if value is None or value == "":
        if required:
            _error(errors, ctx, "is required")
        return default
    if not isinstance(value, str):
        _error(errors, ctx, "must be a string")
        return default
    return value.strip()


def _as_bool(value: Any, ctx: str, errors: list[str], default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        _error(errors, ctx, "must be true or false")
        return default
    return value


def _as_float(
    value: Any,
    ctx: str,
    errors: list[str],
    *,
    default: float,
    lo: float | None = None,
    hi: float | None = None,
) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(errors, ctx, "must be a number")
        return default
    number = float(value)
    if lo is not None and number < lo:
        _error(errors, ctx, f"must be >= {lo}")
        return default
    if hi is not None and number > hi:
        _error(errors, ctx, f"must be <= {hi}")
        return default
    return number


def _as_int(
    value: Any,
    ctx: str,
    errors: list[str],
    *,
    default: int,
    lo: int | None = None,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _error(errors, ctx, "must be an integer")
        return default
    if lo is not None and value < lo:
        _error(errors, ctx, f"must be >= {lo}")
        return default
    return value


def _as_color(value: Any, ctx: str, errors: list[str], default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not _HEX_RE.match(value):
        _error(errors, ctx, "must be a #RRGGBB colour")
        return default
    return value.upper()


def _language(value: Any, ctx: str, errors: list[str]) -> str | None:
    if not isinstance(value, str):
        _error(errors, ctx, "must be a language code string")
        return None
    code = value.strip().lower()
    if not _LANG_RE.match(code):
        _error(errors, ctx, f"unsupported language code '{value}' (use e.g. en, vi)")
        return None
    return code


def _texts(
    value: Any,
    ctx: str,
    errors: list[str],
    source_language: str,
    *,
    required: bool = True,
) -> dict[str, str]:
    """Parse a string (source language) or a language -> text map."""
    if value is None:
        if required:
            _error(errors, ctx, "is required")
        return {}
    if isinstance(value, str):
        value = {source_language: value}
    if not isinstance(value, dict):
        _error(errors, ctx, "must be a string or an object of language -> text")
        return {}

    out: dict[str, str] = {}
    for raw_lang, raw_text in value.items():
        lang = _language(raw_lang, f"{ctx}.{raw_lang}", errors)
        if lang is None:
            continue
        if not isinstance(raw_text, str):
            _error(errors, f"{ctx}.{lang}", "must be a string")
            continue
        text = _normalise_text(raw_text)
        if not text:
            _error(errors, f"{ctx}.{lang}", "must not be empty")
            continue
        if lang in out:
            _error(errors, f"{ctx}.{lang}", "duplicate language")
            continue
        out[lang] = text

    if required and not out:
        _error(errors, ctx, "must contain at least one text")
    if out and source_language not in out:
        _error(
            errors,
            ctx,
            f"missing source_language '{source_language}' text",
        )
    return out


# --------------------------------------------------------------------------- parsing
def _parse_voice(
    value: Any,
    ctx: str,
    language: str,
    errors: list[str],
    base_dir: Path,
) -> Voice | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None

    backend = _as_str(value.get("backend"), f"{ctx}.backend", errors, required=True).lower()
    if backend not in BACKENDS:
        _error(
            errors,
            f"{ctx}.backend",
            f"must be one of {', '.join(sorted(BACKENDS))}",
        )
        return None

    if backend in {"qwen", "qwen_clone"} and language not in QWEN_LANGUAGES:
        _error(
            errors,
            ctx,
            f"backend '{backend}' supports {', '.join(sorted(QWEN_LANGUAGES))}, "
            f"not '{language}'",
        )
        return None
    if backend == "vieneu" and language != "vi":
        _error(errors, ctx, "backend 'vieneu' only supports 'vi'")
        return None

    voice_id = _as_str(value.get("voice_id"), f"{ctx}.voice_id", errors)
    ref_audio = _as_str(value.get("ref_audio"), f"{ctx}.ref_audio", errors)
    ref_text = _as_str(value.get("ref_text"), f"{ctx}.ref_text", errors)
    instruct = _as_str(value.get("instruct"), f"{ctx}.instruct", errors)

    if backend == "qwen":
        voice_id = voice_id or DEFAULT_QWEN_SPEAKERS[language]
        if ref_audio or ref_text:
            _error(errors, ctx, "ref_audio/ref_text are only valid for qwen_clone")
        if instruct:
            pass  # supported by tts_qwen.py
    elif backend == "qwen_clone":
        if not ref_audio:
            _error(errors, f"{ctx}.ref_audio", "is required for qwen_clone")
        if instruct:
            _error(errors, f"{ctx}.instruct", "qwen_clone does not support instruct")
        if voice_id:
            _error(errors, f"{ctx}.voice_id", "qwen_clone uses ref_audio, not voice_id")
        if ref_audio:
            ref_path = Path(ref_audio).expanduser()
            if not ref_path.is_absolute():
                ref_path = (base_dir / ref_path).resolve()
            ref_audio = str(ref_path)
    else:  # vieneu
        voice_id = voice_id or DEFAULT_VIENEU_VOICE
        if ref_audio or ref_text:
            _error(errors, ctx, "ref_audio/ref_text are only valid for qwen_clone")
        if instruct:
            _error(errors, f"{ctx}.instruct", "vieneu does not support instruct")

    return Voice(
        backend=backend,
        voice_id=voice_id,
        ref_audio=ref_audio,
        ref_text=ref_text,
        instruct=instruct,
    )


def _parse_voices(
    value: Any,
    ctx: str,
    errors: list[str],
    base_dir: Path,
) -> dict[str, Voice]:
    if value is None:
        _error(errors, ctx, "is required (one voice profile per language)")
        return {}

    entries: list[tuple[Any, Any, str]] = []
    if isinstance(value, dict):
        entries = [(lang, profile, f"{ctx}.{lang}") for lang, profile in value.items()]
    elif isinstance(value, list):
        for idx, profile in enumerate(value):
            item_ctx = f"{ctx}[{idx}]"
            if not isinstance(profile, dict):
                _error(errors, item_ctx, "must be an object")
                continue
            entries.append((profile.get("language"), profile, item_ctx))
    else:
        _error(errors, ctx, "must be an object of language -> profile or a list")
        return {}

    out: dict[str, Voice] = {}
    for raw_lang, profile, item_ctx in entries:
        lang = _language(raw_lang, f"{item_ctx}.language", errors)
        if lang is None:
            continue
        if lang in out:
            _error(errors, item_ctx, f"duplicate voice for language '{lang}'")
            continue
        voice = _parse_voice(profile, item_ctx, lang, errors, base_dir)
        if voice is not None:
            out[lang] = voice

    if not out:
        _error(errors, ctx, "must define at least one voice profile")
    return out


def _parse_character(
    value: Any,
    ctx: str,
    errors: list[str],
    base_dir: Path,
) -> Character | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None

    char_id = _as_id(value.get("id"), f"{ctx}.id", errors)
    name = _as_str(value.get("name"), f"{ctx}.name", errors, required=True)
    if char_id is None:
        return None

    appearance = value.get("appearance")
    if appearance is None:
        appearance = {}
    if not isinstance(appearance, dict):
        _error(errors, f"{ctx}.appearance", "must be an object")
        appearance = {}

    return Character(
        id=char_id,
        name=name or char_id,
        color=_as_color(value.get("color"), f"{ctx}.color", errors, DEFAULT_COLOR),
        hair=_as_color(
            appearance.get("hair"), f"{ctx}.appearance.hair", errors, DEFAULT_HAIR
        ),
        long_hair=_as_bool(
            appearance.get("long_hair"),
            f"{ctx}.appearance.long_hair",
            errors,
            default=True,
        ),
        voices=_parse_voices(value.get("voices"), f"{ctx}.voices", errors, base_dir),
    )


def _parse_item(
    value: Any,
    ctx: str,
    errors: list[str],
    source_language: str,
) -> BoardItem | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None
    texts = _texts(value.get("texts"), f"{ctx}.texts", errors, source_language)
    icon = _as_str(value.get("icon"), f"{ctx}.icon", errors, default="bubble") or "bubble"
    # Unknown icons fall back to the speech bubble rather than failing a render.
    if icon not in ICONS:
        icon = "bubble"
    return BoardItem(texts=texts, icon=icon)


def _parse_board(
    value: Any,
    ctx: str,
    errors: list[str],
    source_language: str,
) -> Board | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None

    board_type = _as_str(value.get("type"), f"{ctx}.type", errors, required=True).lower()
    if board_type not in BOARD_TYPES:
        _error(
            errors,
            f"{ctx}.type",
            f"must be one of {', '.join(sorted(BOARD_TYPES))}",
        )
        return None

    board = Board(type=board_type)
    if board_type == "title":
        board.kicker = _as_str(value.get("kicker"), f"{ctx}.kicker", errors)
        board.title = _texts(
            value.get("title"), f"{ctx}.title", errors, source_language
        )
        board.sub = _texts(
            value.get("sub"), f"{ctx}.sub", errors, source_language, required=False
        )
        board.stars = _as_bool(value.get("stars"), f"{ctx}.stars", errors)
    elif board_type in {"cards", "repeat"}:
        raw_items = value.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            _error(errors, f"{ctx}.items", "must be a non-empty list")
            raw_items = []
        for idx, raw_item in enumerate(raw_items):
            item = _parse_item(
                raw_item, f"{ctx}.items[{idx}]", errors, source_language
            )
            if item is not None:
                board.items.append(item)
    else:  # dialog
        pass

    return board


def _parse_line(
    value: Any,
    ctx: str,
    errors: list[str],
    source_language: str,
    character_ids: set[str],
    character_names: dict[str, str],
) -> Line | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None

    line_id = _as_id(value.get("id"), f"{ctx}.id", errors)
    if line_id is None:
        return None

    raw_character = value.get("character", value.get("character_id"))
    character_id = _as_id(raw_character, f"{ctx}.character", errors)
    if character_id is None:
        return None
    if character_id not in character_ids:
        # Accept the display name too; this makes hand-written CMS JSON easier.
        character_id = character_names.get(character_id, character_id)
    if character_id not in character_ids:
        _error(errors, f"{ctx}.character", f"unknown character '{character_id}'")

    texts = _texts(value.get("texts"), f"{ctx}.texts", errors, source_language)
    arm = _as_str(value.get("arm"), f"{ctx}.arm", errors, default="point").lower()
    if arm not in ARMS:
        _error(errors, f"{ctx}.arm", f"must be one of {', '.join(sorted(ARMS))}")
        arm = "point"

    return Line(
        id=line_id,
        character_id=character_id,
        texts=texts,
        arm=arm,
        pause=_as_float(
            value.get("pause"),
            f"{ctx}.pause",
            errors,
            default=0.4,
            lo=0.0,
            hi=30.0,
        ),
        active=_as_int(
            value.get("active"), f"{ctx}.active", errors, default=-1, lo=-1
        ),
        repeat=_as_bool(value.get("repeat"), f"{ctx}.repeat", errors),
        sort_order=_as_int(
            value.get("sort_order"), f"{ctx}.sort_order", errors, default=0
        ),
    )


def _parse_scene(
    value: Any,
    ctx: str,
    errors: list[str],
    source_language: str,
    character_ids: set[str],
    character_names: dict[str, str],
) -> Scene | None:
    if not isinstance(value, dict):
        _error(errors, ctx, "must be an object")
        return None

    scene_id = _as_id(value.get("id"), f"{ctx}.id", errors)
    if scene_id is None:
        return None

    board = _parse_board(
        value.get("board"), f"{ctx}.board", errors, source_language
    )
    if board is None:
        return None

    raw_lines = value.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        _error(
            errors,
            f"{ctx}.lines",
            "must contain at least one line (every scene needs narration)",
        )
        raw_lines = []

    lines: list[Line] = []
    for idx, raw_line in enumerate(raw_lines):
        line = _parse_line(
            raw_line,
            f"{ctx}.lines[{idx}]",
            errors,
            source_language,
            character_ids,
            character_names,
        )
        if line is not None:
            lines.append(line)

    scene = Scene(
        id=scene_id,
        title=_as_str(value.get("title"), f"{ctx}.title", errors),
        subtitle=_as_str(value.get("subtitle"), f"{ctx}.subtitle", errors),
        board=board,
        lines=lines,
        sort_order=_as_int(
            value.get("sort_order"), f"{ctx}.sort_order", errors, default=0
        ),
    )
    return scene


def parse_episode(
    data: Any,
    *,
    base_dir: str | Path | None = None,
    source_name: str = "<episode>",
) -> Episode:
    """Parse and validate an episode dictionary.

    ``base_dir`` is used to resolve ``qwen_clone`` reference audio paths.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValidationError(["top-level JSON must be an object"], source_name)

    base = Path(base_dir) if base_dir is not None else Path.cwd()

    title = _as_str(data.get("title"), "title", errors, required=True)
    template = _as_str(
        data.get("template"), "template", errors, default="chalkboard"
    ).lower()
    if template not in SUPPORTED_TEMPLATES:
        _error(
            errors,
            "template",
            f"unsupported template '{template}' (supported: "
            f"{', '.join(sorted(SUPPORTED_TEMPLATES))})",
        )

    raw_languages = data.get("languages")
    languages: list[str] = []
    if raw_languages is None:
        raw_languages = []
    if not isinstance(raw_languages, list):
        _error(errors, "languages", "must be a list of language codes")
        raw_languages = []
    for idx, raw_lang in enumerate(raw_languages):
        lang = _language(raw_lang, f"languages[{idx}]", errors)
        if lang and lang not in languages:
            languages.append(lang)
        elif lang in languages:
            _error(errors, f"languages[{idx}]", f"duplicate language '{lang}'")

    source_language = _language(
        data.get("source_language"), "source_language", errors
    )
    if source_language is None:
        if languages:
            source_language = languages[0]
        else:
            _error(errors, "source_language", "is required when languages is empty")
            source_language = "en"
    if languages and source_language not in languages:
        _error(
            errors,
            "source_language",
            f"must be one of languages ({', '.join(languages)})",
        )
    if not languages:
        languages = [source_language]

    raw_characters = data.get("characters")
    if not isinstance(raw_characters, list) or not raw_characters:
        _error(errors, "characters", "must be a non-empty list")
        raw_characters = []

    characters: list[Character] = []
    character_ids: set[str] = set()
    character_names: dict[str, str] = {}
    for idx, raw_character in enumerate(raw_characters):
        character = _parse_character(
            raw_character, f"characters[{idx}]", errors, base
        )
        if character is None:
            continue
        if character.id in character_ids:
            _error(errors, f"characters[{idx}].id", f"duplicate id '{character.id}'")
            continue
        character_ids.add(character.id)
        character_names.setdefault(character.name, character.id)
        characters.append(character)

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        _error(errors, "scenes", "must be a non-empty list")
        raw_scenes = []

    scenes: list[Scene] = []
    scene_ids: set[str] = set()
    line_ids: set[str] = set()
    for idx, raw_scene in enumerate(raw_scenes):
        scene = _parse_scene(
            raw_scene,
            f"scenes[{idx}]",
            errors,
            source_language,
            character_ids,
            character_names,
        )
        if scene is None:
            continue
        if scene.id in scene_ids:
            _error(errors, f"scenes[{idx}].id", f"duplicate id '{scene.id}'")
            continue
        scene_ids.add(scene.id)

        for line_idx, line in enumerate(scene.lines):
            if line.id in line_ids:
                _error(
                    errors,
                    f"scenes[{idx}].lines[{line_idx}].id",
                    f"duplicate line id '{line.id}' (line ids must be unique)",
                )
            line_ids.add(line.id)

            if scene.board.type in {"cards", "repeat"}:
                if line.active >= len(scene.board.items):
                    _error(
                        errors,
                        f"scenes[{idx}].lines[{line_idx}].active",
                        f"item index {line.active} is out of range "
                        f"(board has {len(scene.board.items)} item(s))",
                    )
            elif scene.board.type == "dialog":
                if line.active >= len(scene.lines):
                    _error(
                        errors,
                        f"scenes[{idx}].lines[{line_idx}].active",
                        f"line index {line.active} is out of range "
                        f"(scene has {len(scene.lines)} line(s))",
                    )

        scenes.append(scene)

    if errors:
        raise ValidationError(errors, source_name)

    return Episode(
        title=title,
        template=template,
        source_language=source_language,
        languages=languages,
        characters=characters,
        scenes=scenes,
        path=Path(source_name) if source_name not in {"<episode>", "<json>"} else None,
    )


def load_episode(path: str | Path) -> Episode:
    """Read and validate an episode JSON file."""
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError([f"cannot read file: {exc}"], str(file_path)) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            [f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"],
            str(file_path),
        ) from exc

    return parse_episode(data, base_dir=file_path.parent, source_name=str(file_path))
