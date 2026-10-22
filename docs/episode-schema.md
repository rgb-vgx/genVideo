# Episode JSON schema

`genvideo` renders a lesson video from one JSON file. The file is the stable
contract with the CMS: the renderer only reads this format and never imports
CMS code.

A complete, runnable example is
[`examples/lesson_min.json`](../examples/lesson_min.json). It contains one
`title`, one `cards`, one `dialog`, and one `repeat` scene.

Two language-teaching demos are included:

* [`examples/lesson_ja.json`](../examples/lesson_ja.json) — Japanese lesson,
  Vietnamese explanations, Japanese phrases.
* [`examples/lesson_ko.json`](../examples/lesson_ko.json) — Korean lesson,
  Vietnamese explanations, Korean phrases.

## Pipeline

```text
episode.json
  -> validate (schema + voice coverage)
  -> TTS per character/language (cache, sequential backends)
  -> load + trim + mix audio, compute timeline
  -> draw frames with PIL (1280x720, 24 fps)
  -> ffmpeg H.264 + AAC, +faststart
  -> output.mp4
```

The renderer process imports only Pillow and NumPy. Qwen and VieNeu are always
separate subprocesses in their own virtualenv; Qwen groups run first, VieNeu
groups run afterwards, and the two models are never loaded at the same time.

## Top level

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `title` | string | yes | Shown in the header pill and used in logs. |
| `template` | string | no | Only `chalkboard` is supported. Default: `chalkboard`. |
| `source_language` | string | no | Defaults to `languages[0]`. Must be in `languages`. |
| `languages` | string[] | yes | Languages the episode can be rendered into. Duplicates are rejected. |
| `characters` | Character[] | yes | The first character is the on-screen teacher. |
| `scenes` | Scene[] | yes | Rendered in array order. At least one scene. |

Language codes are lowercase ISO-639 style codes: `en`, `vi`, `zh`, `ja`, `ko`.
The TTS backends support `en/zh/ja/ko` (Qwen) and `vi` (VieNeu).

## Character

```json
{
  "id": "teacher",
  "name": "Cô Lan",
  "color": "#2F6FA8",
  "appearance": {"hair": "#3F2A1E", "long_hair": true},
  "voices": {
    "en": {"backend": "qwen", "voice_id": "Serena"},
    "vi": {"backend": "vieneu", "voice_id": "Mai Anh"}
  }
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string/int | yes | Unique within the episode. Numeric CMS ids are accepted. |
| `name` | string | yes | Caption/name-pill label and an accepted alias for `line.character`. |
| `color` | `#RRGGBB` | no | Outfit and caption pill colour. Default `#2F6FA8`. |
| `appearance.hair` | `#RRGGBB` | no | Hair colour. Default `#3F2A1E`. |
| `appearance.long_hair` | bool | no | Draw long hair behind the teacher/avatar. Default `true`. |
| `voices` | object or list | yes | One profile per spoken language. |

The **first character is the teacher**: full-body figure on the left. Up to
three further characters are supported in the dialog board (the layout also
works with more, but the demo target is one teacher + 1–3 speakers).

### Voice profile

Canonical form is a map keyed by language. The CMS list form is also accepted:

```json
"voices": [
  {"language": "en", "backend": "qwen", "voice_id": "Serena"},
  {"language": "vi", "backend": "vieneu", "voice_id": "Mai Anh"}
]
```

| Backend | Languages | Fields | Default |
| --- | --- | --- | --- |
| `qwen` | `en`, `zh`, `ja`, `ko` | `voice_id`, optional `instruct` | `Ryan` (en), `Serena` (zh), `Ono_Anna` (ja), `Sohee` (ko) |
| `qwen_clone` | `en`, `zh`, `ja`, `ko` | `ref_audio`, `ref_text`; empty `ref_text` uses x-vector-only | — |
| `vieneu` | `vi` | `voice_id` | `Mai Anh` |

`ref_audio` is resolved relative to the episode JSON file. `qwen_clone` does
not accept `voice_id` or `instruct`. `vieneu` does not accept `instruct` or
reference fields. `validate --check-files` verifies reference files exist.

Known VieNeu voices include `Mai Anh`, `Thùy Dung`, `Hải Đăng`, `Trúc Ly`,
`Thiện Minh`, `Ngọc Huyền`, `Quỳnh Anh`, `Kim Thanh`, `Adam`, `Quốc Tuấn`.
Run `.venv-vieneu/bin/python tts_vieneu.py --list-voices` for the full list.

### Language fallback

For a render in language `L`:

1. If a line/item has `texts[L]`, that text is spoken with the character's
   voice for `L`.
2. Otherwise `texts[source_language]` is spoken with the character's
   `source_language` voice.
3. Captions show `texts[L]` as the main line and
   `texts[source_language]` as the second line when they differ.
4. Every text map must contain the source language, so a fallback always has
   something to say. Missing target-language text is allowed; missing target
   voice is an error only when the target text itself is used.

### Mixed-language teaching videos

A language lesson can combine Vietnamese explanations with Korean/Japanese
example phrases in one video:

```json
{"source_language": "vi", "languages": ["vi", "ko"]}
```

* A line whose `texts` contains only `vi` is spoken with the Vietnamese
  (`vieneu`) voice; its caption is Vietnamese.
* A line whose `texts` contains both `vi` and `ko` is spoken with the Korean
  (`qwen`) voice; its caption is Korean with a Vietnamese subtitle.

`examples/lesson_ko.json` and `examples/lesson_ja.json` use this pattern. For a
`ko` render the pipeline runs the Qwen Korean clips first and the VieNeu
Vietnamese explanation clips afterwards, still one backend at a time.

## Scene

```json
{
  "id": "intro",
  "title": {"en": "Welcome", "vi": "Mở đầu"},
  "subtitle": {"en": "Introduction", "vi": "Giới thiệu"},
  "board": {"type": "title", "...": "..."},
  "lines": ["..."]
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string/int | yes | Unique within the episode. |
| `title` | string or map | no | Progress label (top-left). A plain string means source-language text. |
| `subtitle` | string or map | no | Secondary progress label; same rules as `title`. |
| `board` | Board | yes | One of the four board types below. |
| `lines` | Line[] | yes | At least one line per scene. |

Every scene needs narration because captions and timeline cues are line-based.

## Board types

### `title`

```json
{
  "type": "title",
  "kicker": "LESSON 1",
  "title": {"en": "Greetings", "vi": "Chào hỏi"},
  "sub": {"en": "Let's learn", "vi": "Cùng học nhé"},
  "stars": true
}
```

`title` is required; `sub` and `stars` are optional. `kicker` is a plain string
(not translated). Text fields accept either a language map or a plain string
(interpreted as source-language text).

### `cards`

```json
{
  "type": "cards",
  "items": [
    {"texts": {"en": "Hello!", "vi": "Xin chào!"}, "icon": "bubble"},
    {"texts": {"en": "Hi!", "vi": "Chào (thân mật)"}, "icon": "bubble"}
  ]
}
```

`items` must be non-empty. Text `en` is shown large, `vi` underneath when it
differs. Icons: `bubble`, `sun`, `sunrise`, `moon`, `q`, `a`, `note`, `star`;
unknown icons fall back to `bubble`. A `note` item displays its secondary
(translated) text as an explanatory paragraph, matching the legacy demo.

### `dialog`

```json
{"type": "dialog"}
```

The board has no content of its own; it draws the scene's `lines` as speech
bubbles. Sides alternate by line order. Each bubble shows the character's face,
hair (from `appearance`), colour (name pill) and name. `line.active` is the
index of the currently visible line and usually goes `0, 1, 2, ...`.

### `repeat`

```json
{
  "type": "repeat",
  "items": [
    {"texts": {"en": "Hello!", "vi": "Xin chào!"}},
    {"texts": {"en": "How are you?", "vi": "Bạn khỏe không?"}}
  ]
}
```

The active item is shown large; dots indicate progress. A line with
`repeat: true` and a long `pause` shows the “Your turn!” prompt and a countdown
bar after the speech ends.

## Line

```json
{
  "id": "l1",
  "character": "teacher",
  "texts": {"en": "Hello everyone!", "vi": "Xin chào các bạn!"},
  "arm": "wave",
  "pause": 0.4,
  "active": -1,
  "repeat": false
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string/int | yes | Unique across the whole episode (clearer TTS errors). |
| `character` / `character_id` | string/int | yes | Character id or display name. |
| `texts` | object | yes | Language -> text. Source language required. |
| `arm` | string | no | `down`, `point` (default), `wave`. |
| `pause` | number | no | Silence after the clip, 0–30 s. Default `0.4`. |
| `active` | int | no | Board item/line index, or `-1` for none. Default `-1`. |
| `repeat` | bool | no | Show the “Your turn!” overlay after this line. Default `false`. |

Validation rejects an out-of-range `active` value for `cards`, `repeat`, and
`dialog` boards, duplicate ids, unknown characters, unsupported backends, and
missing source text.

## Timing model

The renderer uses the same pacing as the legacy demo:

* lead-in before the first speech: `0.9 s`;
* scene transition: `0.6 s` gap + `0.6 s` board display before the first line;
* each line: its trimmed TTS duration + `pause`;
* tail after the last line: `0.8 s`;
* chime at `0.25 s` and at each scene transition.

Timing is frame-based at `24 fps` by default. Video: `1280x720`, H.264,
`yuv420p`, AAC 128 kbps 44.1 kHz mono, `+faststart`.

## Fonts

Vietnamese/Latin renders use DejaVu Sans (or `GENVIDEO_FONT_BOLD` /
`GENVIDEO_FONT_REGULAR`). When the episode contains Japanese, Korean, or Chinese
text, the renderer automatically switches to Noto Sans CJK:

* `GENVIDEO_FONT_CJK_BOLD` / `GENVIDEO_FONT_CJK_REGULAR` override the files;
* `GENVIDEO_FONT_CJK_INDEX` overrides the TrueType collection index;
* Noto Sans CJK also covers Vietnamese, so a Korean/Japanese lesson with
  Vietnamese explanations uses one consistent font.

On Ubuntu/Debian: `sudo apt install fonts-noto-cjk`.

## CLI

```bash
python -m genvideo validate examples/lesson_min.json
python -m genvideo validate examples/lesson_min.json --language en --check-files
python -m genvideo render examples/lesson_min.json --language en --out output/service_en.mp4
python -m genvideo render examples/lesson_min.json --language vi --out output/service_vi.mp4
python -m genvideo render examples/lesson_ja.json --language ja --out output/service_ja.mp4
python -m genvideo render examples/lesson_ko.json --language ko --out output/service_ko.mp4
python -m genvideo preview examples/lesson_min.json --language en --at 3,30 --out-dir build/preview
```

If the machine has no `python` alias, use `python3` in the same commands.

Common flags:

* `--work-dir DIR` — use and keep temporary TTS group files and `mix.wav`.
* `--keep-work` — keep the default `build/work/<episode>_<language>` directory.
* `--force` — ignore the TTS cache and synthesize every clip again.
* `--cache-dir DIR` — override the default `build/cache/tts`.
* `--fps N`, `--crf N`, `--preset NAME` — encoding controls.
* `--at 3,30` — preview timestamps in seconds.
* `--language L` on `validate` also checks that every needed voice exists.

Exit code is `0` on success and non-zero on validation, TTS, audio, or ffmpeg
failure. Progress and diagnostics go to stderr; the output path and timing
summary go to stdout.

## TTS cache

Cache path (default): `build/cache/tts/<sha256>.wav`.

The key is a SHA-256 of the canonical JSON of exactly these fields:

```text
text, language, backend, voice_id, ref_audio, ref_text, instruct
```

`ref_audio` is stored as an absolute path. Identical clips are synthesized once
and shared by every line with the same key. A line whose key is already on disk
never reaches a backend. Use `--force` to regenerate.

Backend grouping is `(backend, language, voice_id, ref_audio, ref_text,
instruct)`, so one model load serves all lines in the group. Groups are sorted
by backend: `qwen`, `qwen_clone`, then `vieneu`. Each backend runs to completion
and exits before the next group starts.

`GENVIDEO_TTS_MOCK=1` writes deterministic test tones under
`build/cache/tts/mock/` instead of loading a model. This is for tests only and
is kept separate from the production cache so mock audio can never be mistaken
for a real voice.

## CMS mapping

The CMS project detail can be converted without changing the CMS:

| CMS field | Episode field |
| --- | --- |
| `Project.title` | `title` |
| `Project.template` | `template` |
| `Project.languages` | `languages` |
| — (not in the current API) | `source_language`; use `languages[0]` until the CMS exposes it |
| `Character[]` | `characters` (ids can stay numeric) |
| `Character.voices[]` | a `voices` list with each profile's `language`, or convert to a map |
| `Scene[]` | `scenes` |
| `Line.character_id` | `character` (accepted alias) |
| `Board.title` / `Board.sub` | language map, or a plain source-language string |
| `Board.items[].texts` | same shape as the canonical schema |
| `sort_order` | not required; renderer uses array order |

The stable renderer interface is:

```bash
python -m genvideo render <episode.json> --language <code> --out <path>
```

The CMS worker is not modified in this milestone. It can later serialize a
project to this JSON, run the command above, and read stderr for progress (or
tail the process log). No renderer import or GPU access is needed in the CMS
process.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

The suite covers schema acceptance/rejection, CMS-shaped voice lists, language
fallback, timeline/audio durations, silence trimming, stable cache keys, cache
reuse, CLI `--help`, and a full mock-TTS render + preview with ffprobe checks.
It does not require CUDA, a model download, or `espeak-ng`.

The Japanese/Korean lesson files are validated too; `tests/test_render.py`
checks CJK font-family detection and (when Noto Sans CJK is installed) that the
KR/JP fonts load and measure Korean/Japanese text.
