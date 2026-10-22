"""PIL frame renderer and ffmpeg encoder.

The drawing code is adapted from the original ``make_video.py`` demo.  The
style (chalkboard, teacher on the left, 1280x720/24 fps, bilingual captions)
is preserved; the hard-coded ``SCENES`` / ``BOARDS`` / ``SEGS`` data is gone.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import SR, envelope
from .errors import RenderError
from .schema import Board, Episode
from .timeline import LineCue, Timeline

S = 2
W, H = 1280, 720
DEFAULT_FPS = 24

BX0, BY0, BX1, BY1 = 470, 48, 1250, 548
IX0, IY0, IX1, IY1 = BX0 + 16, BY0 + 16, BX1 - 16, BY1 - 16
BCX = (IX0 + IX1) / 2

WALL = (247, 238, 221)
WALL2 = (241, 226, 200)
BOARD = (46, 90, 72)
WOOD = (154, 101, 52)
CHALK = (244, 243, 234)
YEL = (255, 217, 90)
SOFT = (185, 214, 196)
SKIN = (243, 201, 163)
SKIN_D = (224, 169, 130)
HAIR = (63, 42, 30)
CARD = (47, 111, 168)
CARD_D = (36, 88, 138)
ACCENT = (228, 87, 46)
INK = (43, 43, 43)
GRAY = (107, 107, 107)
BUBBLE = (59, 110, 89)

ARMS = {"down": (78, 92, 0), "point": (-14, -30, 1), "wave": (-62, -100, 0)}

UI = {
    "en": {
        "dialog": "LISTEN  ·  Conversation",
        "repeat": "REPEAT AFTER ME",
        "repeat_sub": "Listen and repeat",
        "your_turn": "Your turn!",
        "your_turn_sub": "Say it out loud!",
        "your_turn_caption": "Your turn! Say it out loud.",
        "you": "You",
    },
    "vi": {
        "dialog": "LISTEN  ·  Nghe hội thoại",
        "repeat": "REPEAT AFTER ME",
        "repeat_sub": "Nghe và nhắc lại",
        "your_turn": "Đến lượt bạn!",
        "your_turn_sub": "Hãy nói to lên nhé!",
        "your_turn_caption": "Đến lượt bạn — hãy nói to lên nhé!",
        "you": "Bạn",
    },
    "zh": {
        "dialog": "LISTEN  ·  对话",
        "repeat": "跟我读",
        "repeat_sub": "听并跟读",
        "your_turn": "轮到你了！",
        "your_turn_sub": "大声说出来！",
        "your_turn_caption": "轮到你了——大声说出来！",
        "you": "你",
    },
    "ja": {
        "dialog": "LISTEN  ·  会話",
        "repeat": "リピートしましょう",
        "repeat_sub": "聞いて繰り返しましょう",
        "your_turn": "あなたの番です！",
        "your_turn_sub": "大きな声で言ってみましょう！",
        "your_turn_caption": "あなたの番です。大きな声で言ってみましょう！",
        "you": "あなた",
    },
    "ko": {
        "dialog": "LISTEN  ·  대화",
        "repeat": "따라 말해 보세요",
        "repeat_sub": "듣고 따라 말해 보세요",
        "your_turn": "이제 당신 차례예요!",
        "your_turn_sub": "크게 말해 보세요!",
        "your_turn_caption": "이제 당신 차례예요. 크게 말해 보세요!",
        "you": "당신",
    },
}


def ui(language: str, key: str) -> str:
    return UI.get(language, UI["en"]).get(key, UI["en"].get(key, ""))


# --------------------------------------------------------------------------- fonts / colour
FB_CANDIDATES = [
    os.environ.get("GENVIDEO_FONT_BOLD"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FR_CANDIDATES = [
    os.environ.get("GENVIDEO_FONT_REGULAR"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_FB: str | None = None
_FR: str | None = None
_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _find_font(candidates: list[str | None], env_name: str) -> str:
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RenderError(
        f"cannot find a font for {env_name}; set GENVIDEO_FONT_BOLD / "
        "GENVIDEO_FONT_REGULAR to a TTF/OTF file with Vietnamese coverage"
    )


def _ensure_fonts() -> None:
    global _FB, _FR
    if _FB is None:
        _FB = _find_font(FB_CANDIDATES, "bold text")
    if _FR is None:
        _FR = _find_font(FR_CANDIDATES, "regular text")


def F(size: float, bold: bool = True) -> ImageFont.FreeTypeFont:
    _ensure_fonts()
    key = (int(size), bold)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(_FB if bold else _FR, int(size * S))
    return _font_cache[key]


def hx(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise RenderError(f"invalid colour '{value}'")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def lerp(c1, c2, a: float):
    a = max(0.0, min(1.0, a))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * a) for i in range(3))


def darken(color, amount: float = 0.18):
    return lerp(color, (0, 0, 0), amount)


def clamp(value, lo: float = 0.0, hi: float = 1.0):
    return max(lo, min(hi, value))


def ease(value):
    value = clamp(value)
    return value * value * (3 - 2 * value)


def Pp(*values):
    return [int(round(value * S)) for value in values]


# --------------------------------------------------------------------------- drawing helpers
def star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, col, rot: float = 0):
    points = []
    for k in range(10):
        angle = -math.pi / 2 + k * math.pi / 5 + rot
        radius = r if k % 2 == 0 else r * 0.45
        points.append(
            (
                (cx + radius * math.cos(angle)) * S,
                (cy + radius * math.sin(angle)) * S,
            )
        )
    d.polygon(points, fill=col)


def icon(d: ImageDraw.ImageDraw, kind: str, x: float, y: float, a: float):
    c = lerp(BOARD, CHALK, a)
    y_col = lerp(BOARD, YEL, a)
    if kind == "bubble":
        d.rounded_rectangle(
            Pp(x - 20, y - 16, x + 20, y + 12), radius=10 * S, outline=c, width=3 * S
        )
        d.polygon(
            [
                tuple(Pp(x - 8, y + 11)),
                tuple(Pp(x - 14, y + 22)),
                tuple(Pp(x + 2, y + 11)),
            ],
            fill=c,
        )
        for k in (-9, 0, 9):
            d.ellipse(Pp(x + k - 2.5, y - 4.5, x + k + 2.5, y + 0.5), fill=c)
    elif kind == "sun":
        for k in range(8):
            angle = k * math.pi / 4
            d.line(
                Pp(
                    x + 15 * math.cos(angle),
                    y + 15 * math.sin(angle),
                    x + 23 * math.cos(angle),
                    y + 23 * math.sin(angle),
                ),
                fill=y_col,
                width=3 * S,
            )
        d.ellipse(Pp(x - 11, y - 11, x + 11, y + 11), fill=y_col)
    elif kind == "sunrise":
        d.pieslice(Pp(x - 14, y - 8, x + 14, y + 20), 180, 360, fill=y_col)
        for k in range(5):
            angle = math.pi + (k + 0.5) * math.pi / 5
            d.line(
                Pp(
                    x + 18 * math.cos(angle),
                    y + 6 + 18 * math.sin(angle),
                    x + 25 * math.cos(angle),
                    y + 6 + 25 * math.sin(angle),
                ),
                fill=y_col,
                width=3 * S,
            )
        d.line(Pp(x - 24, y + 7, x + 24, y + 7), fill=c, width=3 * S)
    elif kind == "moon":
        d.ellipse(Pp(x - 15, y - 15, x + 15, y + 15), fill=y_col)
        d.ellipse(Pp(x - 6, y - 19, x + 20, y + 9), fill=BOARD)
        star(d, x + 16, y + 10, 4, c)
    elif kind in ("q", "a", "note"):
        col = y_col if kind == "note" else c
        d.ellipse(Pp(x - 18, y - 18, x + 18, y + 18), outline=col, width=3 * S)
        char = {"q": "?", "a": "✓", "note": "!"}[kind]
        d.text(Pp(x, y + 1), char, font=F(22), fill=col, anchor="mm")
    elif kind == "star":
        star(d, x, y, 18, y_col)
    else:
        # Unknown icons are normalised to "bubble" by the schema; this branch
        # only protects hand-constructed objects.
        d.ellipse(Pp(x - 8, y - 8, x + 8, y + 8), fill=c)


def fit(txt: str, size: int, max_width: float, bold: bool = True) -> int:
    while F(size, bold).getlength(txt) > max_width * S and size > 14:
        size -= 1
    return size


def wrap(txt: str, size: int, max_width: float, bold: bool = False) -> list[str]:
    words, lines, current = txt.split(), [], ""
    for word in words:
        test = (current + " " + word).strip()
        if F(size, bold).getlength(test) <= max_width * S:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def face(
    d: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    hair,
    mouth: float,
    long_hair: bool,
    blink: bool,
):
    if long_hair:
        d.ellipse(Pp(cx - r * 1.15, cy - r * 1.1, cx + r * 1.15, cy + r * 1.25), fill=hair)
    d.ellipse(Pp(cx - r, cy - r, cx + r, cy + r), fill=SKIN)
    d.chord(Pp(cx - r * 1.05, cy - r * 1.15, cx + r * 1.05, cy + r * 0.45), 180, 360, fill=hair)
    ey = cy + r * 0.12
    for sign in (-1, 1):
        ex = cx + sign * r * 0.38
        if blink:
            d.line(Pp(ex - r * 0.12, ey, ex + r * 0.12, ey), fill=INK, width=2 * S)
        else:
            d.ellipse(Pp(ex - r * 0.1, ey - r * 0.13, ex + r * 0.1, ey + r * 0.13), fill=INK)
    my = cy + r * 0.52
    if mouth > 0.05:
        mh = r * (0.08 + 0.32 * mouth)
        d.ellipse(Pp(cx - r * 0.22, my - mh / 2, cx + r * 0.22, my + mh / 2), fill=(142, 47, 47))
    else:
        d.arc(
            Pp(cx - r * 0.25, my - r * 0.22, cx + r * 0.25, my + r * 0.12),
            20,
            160,
            fill=(142, 47, 47),
            width=2 * S,
        )


def limb(
    d: ImageDraw.ImageDraw,
    p0,
    a1: float,
    a2: float,
    l1: float,
    l2: float,
    sleeve,
    stick: bool = False,
):
    r1, r2 = math.radians(a1), math.radians(a2)
    elbow = (p0[0] + l1 * math.cos(r1), p0[1] + l1 * math.sin(r1))
    hand = (elbow[0] + l2 * math.cos(r2), elbow[1] + l2 * math.sin(r2))
    width = 24
    d.line(Pp(*p0, *elbow), fill=sleeve, width=width * S)
    d.ellipse(
        Pp(elbow[0] - width / 2, elbow[1] - width / 2, elbow[0] + width / 2, elbow[1] + width / 2),
        fill=sleeve,
    )
    d.line(Pp(*elbow, *hand), fill=sleeve, width=(width - 2) * S)
    if stick:
        tip = (hand[0] + 78 * math.cos(r2 - 0.08), hand[1] + 78 * math.sin(r2 - 0.08))
        d.line(Pp(*hand, *tip), fill=(122, 74, 34), width=5 * S)
        d.ellipse(Pp(tip[0] - 4, tip[1] - 4, tip[0] + 4, tip[1] + 4), fill=CHALK)
    d.ellipse(Pp(hand[0] - 13, hand[1] - 13, hand[0] + 13, hand[1] + 13), fill=SKIN)
    return hand


def teacher_figure(
    d: ImageDraw.ImageDraw,
    t: float,
    mouth: float,
    blink: bool,
    arm,
    look: float,
    *,
    hair,
    long_hair: bool,
    outfit,
):
    cx = 245
    dy = 2.5 * math.sin(t * 1.7)
    hy = 300 + dy
    outfit_dark = darken(outfit)
    if long_hair:
        d.ellipse(Pp(cx - 80, hy - 82, cx + 80, hy + 108), fill=hair)
    d.rounded_rectangle(Pp(cx - 84, 428, cx + 84, 680), radius=44 * S, fill=outfit)
    d.polygon(
        [tuple(Pp(cx - 30, 426)), tuple(Pp(cx + 30, 426)), tuple(Pp(cx, 492))],
        fill=(255, 255, 255),
    )
    d.line(Pp(cx - 30, 428, cx, 492), fill=outfit_dark, width=3 * S)
    d.line(Pp(cx + 30, 428, cx, 492), fill=outfit_dark, width=3 * S)
    for by in (510, 545, 580):
        d.ellipse(Pp(cx - 4, by - 4, cx + 4, by + 4), fill=(242, 210, 122))
    d.rectangle(Pp(cx - 16, hy + 50, cx + 16, 432), fill=SKIN_D)
    limb(d, (cx - 66, 452), 102 + 2 * math.sin(t * 1.3), 94, 78, 70, outfit)
    limb(d, (cx + 66, 452), arm[0], arm[1], 80, 72, outfit, stick=arm[2] > 0.5)
    d.ellipse(Pp(cx - 64, hy - 70, cx + 64, hy + 70), fill=SKIN)
    for sign in (-1, 1):
        d.ellipse(Pp(cx + sign * 64 - 9, hy - 2, cx + sign * 64 + 9, hy + 22), fill=SKIN)
    d.ellipse(Pp(cx + 64 - 3, hy + 20, cx + 64 + 5, hy + 28), fill=YEL)
    d.ellipse(Pp(cx - 64 - 5, hy + 20, cx - 64 + 3, hy + 28), fill=YEL)
    d.chord(Pp(cx - 70, hy - 84, cx + 70, hy + 6), 180, 360, fill=hair)
    d.pieslice(Pp(cx - 70, hy - 84, cx + 90, hy + 40), 180, 250, fill=hair)
    if long_hair:
        d.ellipse(Pp(cx + 40, hy - 78, cx + 58, hy - 60), fill=ACCENT)
    ey = hy + 6
    lx = 3 * look
    for sign in (-1, 1):
        ex = cx + sign * 25
        d.arc(Pp(ex - 13, ey - 26, ex + 13, ey - 10), 200, 340, fill=hair, width=3 * S)
        if blink:
            d.arc(Pp(ex - 11, ey - 6, ex + 11, ey + 6), 10, 170, fill=INK, width=3 * S)
        else:
            d.ellipse(Pp(ex - 10, ey - 12, ex + 10, ey + 12), fill=(255, 255, 255))
            d.ellipse(Pp(ex - 6 + lx, ey - 7, ex + 6 + lx, ey + 7), fill=(58, 42, 32))
            d.ellipse(Pp(ex - 2 + lx, ey - 5, ex + 2 + lx, ey - 1), fill=(255, 255, 255))
    for sign in (-1, 1):
        d.ellipse(Pp(cx + sign * 40 - 11, hy + 22, cx + sign * 40 + 11, hy + 34), fill=(242, 167, 154))
    d.arc(Pp(cx - 6, hy + 12, cx + 6, hy + 26), 300, 60, fill=SKIN_D, width=3 * S)
    my = hy + 42
    if mouth > 0.05:
        mh = 5 + 20 * mouth
        mw = 17 - 3 * mouth
        d.ellipse(Pp(cx - mw, my - mh / 2, cx + mw, my + mh / 2), fill=(142, 47, 47))
        if mh > 12:
            d.ellipse(Pp(cx - mw * 0.6, my + mh / 2 - 7, cx + mw * 0.6, my + mh / 2 - 1), fill=(224, 122, 122))
    else:
        d.arc(Pp(cx - 18, my - 14, cx + 18, my + 8), 20, 160, fill=(142, 47, 47), width=4 * S)


# --------------------------------------------------------------------------- renderer
class Renderer:
    def __init__(
        self,
        episode: Episode,
        timeline: Timeline,
        tracks: dict[str, np.ndarray],
        language: str,
    ) -> None:
        if language not in episode.languages:
            raise RenderError(
                f"language '{language}' is not in episode.languages "
                f"({', '.join(episode.languages)})"
            )
        self.episode = episode
        self.timeline = timeline
        self.language = language
        self.source_language = episode.source_language
        self.fps = timeline.fps
        self.nframes = timeline.nframes
        self.total = timeline.total
        self.teacher_char = episode.teacher
        self.scene_by_id = {scene.id: scene for scene in episode.scenes}
        self.scene_order = [scene.id for scene in episode.scenes]
        self.env = {
            character.id: envelope(
                tracks.get(character.id, np.zeros(1, dtype=np.float32)),
                self.nframes,
                self.fps,
            )
            for character in episode.characters
        }
        self.arm_state = list(ARMS["down"])
        _ensure_fonts()
        self.bg = self._build_background()

    # ------------------------------------------------------------------ static
    def _build_background(self) -> Image.Image:
        bg = Image.new("RGB", (W * S, H * S), WALL)
        d = ImageDraw.Draw(bg)
        for y in range(H * S):
            d.line([(0, y), (W * S, y)], fill=lerp(WALL, WALL2, y / (H * S)))
        d.rectangle(Pp(0, 560, W, H), fill=hx("#D9C3A0"))
        for x, y, r, color in [
            (110, 160, 90, "#F2DFC0"),
            (360, 120, 50, "#F4E4C8"),
            (60, 470, 40, "#F0DCBA"),
        ]:
            d.ellipse(Pp(x - r, y - r, x + r, y + r), fill=hx(color))

        shadow = Image.new("L", (W * S, H * S), 0)
        ImageDraw.Draw(shadow).rounded_rectangle(
            Pp(BX0 + 6, BY0 + 10, BX1 + 6, BY1 + 12), radius=18 * S, fill=90
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(14 * S))
        bg = Image.composite(Image.new("RGB", bg.size, hx("#8C7A5E")), bg, shadow)
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle(Pp(BX0, BY0, BX1, BY1), radius=14 * S, fill=WOOD)
        d.rounded_rectangle(
            Pp(BX0 + 4, BY0 + 4, BX1 - 4, BY1 - 4),
            radius=12 * S,
            outline=hx("#B27A44"),
            width=2 * S,
        )

        board_width, board_height = (IX1 - IX0) * S, (IY1 - IY0) * S
        surface = Image.new("RGB", (board_width, board_height), BOARD)
        sd = ImageDraw.Draw(surface)
        rnd = random.Random(3)
        for _ in range(9):
            x, y = rnd.randint(0, board_width), rnd.randint(0, board_height)
            r = rnd.randint(80, 220) * S
            sd.ellipse(
                [x - r, y - r // 2, x + r, y + r // 2],
                fill=lerp(BOARD, CHALK, 0.045),
            )
        surface = surface.filter(ImageFilter.GaussianBlur(30 * S))
        sd = ImageDraw.Draw(surface)
        for _ in range(1800):
            x, y = rnd.randint(0, board_width - 1), rnd.randint(0, board_height - 1)
            sd.point((x, y), fill=lerp(BOARD, CHALK, rnd.uniform(0.05, 0.16)))
        bg.paste(surface, Pp(IX0, IY0))

        d.rounded_rectangle(
            Pp(BX0 + 30, BY1 - 4, BX1 - 30, BY1 + 10), radius=5 * S, fill=hx("#7E5129")
        )
        d.rounded_rectangle(
            Pp(BX1 - 140, BY1 - 9, BX1 - 100, BY1 - 1), radius=3 * S, fill=CHALK
        )
        d.rounded_rectangle(
            Pp(BX1 - 90, BY1 - 9, BX1 - 60, BY1 - 1), radius=3 * S, fill=YEL
        )

        d.rounded_rectangle(Pp(34, 30, 404, 78), radius=24 * S, fill=ACCENT)
        title = self.episode.title.upper()
        title_size = fit(title, 21, 240)
        d.text(Pp(56, 54), title, font=F(title_size), fill=(255, 255, 255), anchor="lm")
        d.text(
            Pp(384, 54),
            self.language.upper(),
            font=F(18, False),
            fill=hx("#FFE3D8"),
            anchor="rm",
        )
        return bg

    # ------------------------------------------------------------------ helpers
    def pair(self, texts: dict[str, str]) -> tuple[str, str | None]:
        return self.episode.text_pair(texts, self.language)

    def frame_index(self, t: float) -> int:
        return min(self.nframes - 1, max(0, int(t * self.fps)))

    def env_value(self, character_id: str, t: float) -> float:
        values = self.env.get(character_id)
        if values is None:
            return 0.0
        return float(values[self.frame_index(t)])

    # ------------------------------------------------------------------ UI
    def draw_progress(self, d: ImageDraw.ImageDraw, cue: LineCue) -> None:
        try:
            current = self.scene_order.index(cue.scene_id)
        except ValueError:
            current = 0
        scene = self.scene_by_id[cue.scene_id]
        d.text(Pp(40, 112), scene.title, font=F(26), fill=INK, anchor="lm")
        d.text(Pp(40, 142), scene.subtitle, font=F(18, False), fill=GRAY, anchor="lm")

        count = len(self.scene_order)
        step = 22 if count <= 10 else max(8, 220 / max(1, count - 1))
        for k in range(count):
            x = 46 + k * step
            color = ACCENT if k == current else (hx("#E9B9A6") if k < current else hx("#DCCBB0"))
            radius = 7 if k == current else 5
            d.ellipse(Pp(x - radius, 178 - radius, x + radius, 178 + radius), fill=color)

    def draw_board(self, d: ImageDraw.ImageDraw, t: float, cue: LineCue) -> None:
        scene = self.scene_by_id[cue.scene_id]
        board = scene.board
        scene_show = self.timeline.scene_show[scene.id]
        sa = ease((t - scene_show) / 0.45)
        index = self.scene_order.index(scene.id)
        if index + 1 < len(self.scene_order):
            next_show = self.timeline.scene_show[self.scene_order[index + 1]]
            sa *= ease((next_show - t) / 0.3)

        if board.type == "title":
            self._draw_title(d, t, board, scene_show, sa)
        elif board.type == "cards":
            self._draw_cards(d, t, board, scene, cue, sa)
        elif board.type == "dialog":
            self._draw_dialog(d, t, scene.id, cue, sa)
        elif board.type == "repeat":
            self._draw_repeat(d, t, board, scene.id, cue, sa)

    def _draw_title(
        self,
        d: ImageDraw.ImageDraw,
        t: float,
        board: Board,
        scene_show: float,
        sa: float,
    ) -> None:
        if board.kicker:
            d.text(
                Pp(BCX, 150),
                board.kicker,
                font=F(26),
                fill=lerp(BOARD, YEL, sa),
                anchor="mm",
            )
        title, _ = self.pair(board.title)
        title_size = fit(title, 88, 700)
        pop = 1 + 0.06 * math.sin(clamp((t - scene_show) / 0.6) * math.pi)
        d.text(
            Pp(BCX, 262),
            title,
            font=F(title_size * pop),
            fill=lerp(BOARD, CHALK, sa),
            anchor="mm",
        )
        width = F(title_size).getlength(title) / S
        progress = ease((t - scene_show - 0.3) / 0.8)
        d.line(
            Pp(BCX - width / 2, 330, BCX - width / 2 + width * progress, 330),
            fill=lerp(BOARD, YEL, sa),
            width=5 * S,
        )
        sub, _ = self.pair(board.sub)
        if sub:
            d.text(
                Pp(BCX, 385),
                sub,
                font=F(36, False),
                fill=lerp(BOARD, SOFT, sa),
                anchor="mm",
            )
        if board.stars:
            for k, (x, y, r) in enumerate(
                [(600, 140, 16), (1120, 160, 20), (640, 430, 13), (1100, 440, 17), (860, 470, 11)]
            ):
                twinkle = 0.6 + 0.4 * math.sin(t * 4 + k)
                star(d, x, y, r * twinkle, lerp(BOARD, YEL, sa), rot=t * 0.5 + k)

    def _draw_cards(
        self,
        d: ImageDraw.ImageDraw,
        t: float,
        board: Board,
        scene,
        cue: LineCue,
        sa: float,
    ) -> None:
        items = board.items
        n = len(items)
        if not n:
            return
        row_height = min(112, 440 / n)
        y0 = IY0 + (IY1 - IY0 - n * row_height) / 2
        for k, item in enumerate(items):
            if k > cue.line.active:
                continue
            show = self.timeline.item_show.get((scene.id, k), self.timeline.scene_show[scene.id])
            ia = ease((t - show) / 0.45) * sa
            active = k == cue.line.active
            dim = 1.0 if active else 0.62
            cy = y0 + k * row_height + row_height / 2
            slide = (1 - ease((t - show) / 0.45)) * 30
            x0 = IX0 + 50 + slide
            primary, secondary = self.pair(item.texts)
            icon(d, item.icon, x0 + 10, cy - 8, ia * dim)
            if item.icon == "note":
                note = secondary or primary
                lines = wrap(note, 23, 600, False)
                for j, line in enumerate(lines):
                    d.text(
                        Pp(x0 + 50, cy - 8 - (len(lines) - 1) * 15 + j * 30),
                        line,
                        font=F(23, False),
                        fill=lerp(BOARD, YEL if active else CHALK, ia * dim),
                        anchor="lm",
                    )
                continue
            size = fit(primary, 46, 600)
            color = YEL if active else CHALK
            d.text(
                Pp(x0 + 50, cy - 14),
                primary,
                font=F(size),
                fill=lerp(BOARD, color, ia * dim),
                anchor="ls",
            )
            if secondary:
                d.text(
                    Pp(x0 + 52, cy + 22),
                    secondary,
                    font=F(23, False),
                    fill=lerp(BOARD, SOFT, ia * dim),
                    anchor="ls",
                )
            if active:
                width = F(size).getlength(primary) / S
                progress = ease((t - show - 0.4) / 0.7)
                d.line(
                    Pp(x0 + 50, cy - 4, x0 + 50 + width * progress, cy - 4),
                    fill=lerp(BOARD, YEL, ia * 0.8),
                    width=3 * S,
                )

    def _draw_dialog(
        self,
        d: ImageDraw.ImageDraw,
        t: float,
        scene_id: str,
        cue: LineCue,
        sa: float,
    ) -> None:
        d.text(
            Pp(BCX, IY0 + 30),
            ui(self.language, "dialog"),
            font=F(22),
            fill=lerp(BOARD, YEL, sa),
            anchor="mm",
        )
        blink = (t % 3.3) < 0.12
        scene_cue = self.timeline.scene_cue(scene_id)
        for k, line_cue in enumerate(scene_cue.lines):
            if k > cue.line.active:
                continue
            show = self.timeline.item_show.get((scene_id, k), line_cue.show)
            ia = ease((t - show) / 0.4) * sa
            active = k == cue.line.active
            cy = IY0 + 88 + k * 66
            text = line_cue.primary
            left = k % 2 == 0
            if left:
                ax = IX0 + 34
                bx0 = ax + 34
                max_width = (IX1 - 30) - bx0 - 16
            else:
                ax = IX1 - 34
                bx1 = ax - 34
                max_width = bx1 - (IX0 + 30) - 16
            font_size = fit(text, 23, max_width, False)
            text_width = F(font_size, False).getlength(text) / S
            if left:
                bx1 = bx0 + text_width + 32
            else:
                bx0 = bx1 - text_width - 32

            fill = lerp(BOARD, BUBBLE, ia)
            outline = lerp(BOARD, YEL if active else lerp(BUBBLE, CHALK, 0.35), ia)
            d.rounded_rectangle(
                Pp(bx0, cy - 24, bx1, cy + 24), radius=20 * S, fill=fill, outline=outline, width=2 * S
            )
            d.text(
                Pp((bx0 + bx1) / 2, cy + 1),
                text,
                font=F(font_size, False),
                fill=lerp(BOARD, CHALK, ia),
                anchor="mm",
            )
            if ia > 0.05:
                character = line_cue.character
                mouth = self.env_value(character.id, t) if active else 0.0
                face(
                    d,
                    ax,
                    cy,
                    22,
                    hx(character.hair),
                    mouth,
                    character.long_hair,
                    blink,
                )
                name = character.name
                name_size = fit(name, 11, 72, False)
                name_width = F(name_size, False).getlength(name) / S
                pill_width = max(28, name_width + 12)
                d.rounded_rectangle(
                    Pp(ax - pill_width / 2, cy + 22, ax + pill_width / 2, cy + 38),
                    radius=8 * S,
                    fill=lerp(BOARD, hx(character.color), ia),
                )
                d.text(
                    Pp(ax, cy + 30),
                    name,
                    font=F(name_size, False),
                    fill=(255, 255, 255),
                    anchor="mm",
                )

    def _draw_repeat(
        self,
        d: ImageDraw.ImageDraw,
        t: float,
        board: Board,
        scene_id: str,
        cue: LineCue,
        sa: float,
    ) -> None:
        d.text(
            Pp(BCX, IY0 + 50),
            ui(self.language, "repeat"),
            font=F(26),
            fill=lerp(BOARD, YEL, sa),
            anchor="mm",
        )
        d.text(
            Pp(BCX, IY0 + 85),
            ui(self.language, "repeat_sub"),
            font=F(20, False),
            fill=lerp(BOARD, SOFT, sa),
            anchor="mm",
        )
        active = cue.line.active
        if active >= 0 and active < len(board.items):
            item = board.items[active]
            primary, secondary = self.pair(item.texts)
            show = self.timeline.item_show.get((scene_id, active), cue.show)
            ia = ease((t - show) / 0.4) * sa
            d.text(
                Pp(BCX, 255),
                primary,
                font=F(fit(primary, 70, 680)),
                fill=lerp(BOARD, CHALK, ia),
                anchor="mm",
            )
            if secondary:
                d.text(
                    Pp(BCX, 318),
                    secondary,
                    font=F(fit(secondary, 30, 700, False), False),
                    fill=lerp(BOARD, SOFT, ia),
                    anchor="mm",
                )
            count = len(board.items)
            step = 30 if count <= 7 else max(14, 200 / max(1, count - 1))
            start = BCX - (count - 1) * step / 2
            for k in range(count):
                color = YEL if k <= active else lerp(BOARD, CHALK, 0.3)
                d.ellipse(
                    Pp(start + k * step - 6, 185 - 6, start + k * step + 6, 185 + 6),
                    fill=lerp(BOARD, color, sa),
                )
            if t > cue.end + 0.1:
                gap = max(0.1, cue.pause - 0.4)
                progress = clamp((t - cue.end - 0.1) / gap)
                pa = ease((t - cue.end - 0.1) / 0.3) * sa
                d.text(
                    Pp(BCX, 395),
                    ui(self.language, "your_turn"),
                    font=F(30),
                    fill=lerp(BOARD, YEL, pa),
                    anchor="mm",
                )
                d.rounded_rectangle(
                    Pp(BCX - 200, 430, BCX + 200, 446),
                    radius=8 * S,
                    fill=lerp(BOARD, BUBBLE, pa),
                )
                if progress > 0.02:
                    d.rounded_rectangle(
                        Pp(BCX - 200, 430, BCX - 200 + 400 * progress, 446),
                        radius=8 * S,
                        fill=lerp(BOARD, YEL, pa),
                    )
        else:
            d.text(
                Pp(BCX, 280),
                ui(self.language, "your_turn"),
                font=F(64),
                fill=lerp(BOARD, CHALK, sa),
                anchor="mm",
            )
            d.text(
                Pp(BCX, 345),
                ui(self.language, "your_turn_sub"),
                font=F(30, False),
                fill=lerp(BOARD, SOFT, sa),
                anchor="mm",
            )

    def draw_caption(self, d: ImageDraw.ImageDraw, t: float, cue: LineCue) -> None:
        if cue.line.repeat and t > cue.end + 0.1:
            primary = ui(self.language, "your_turn_caption")
            secondary = (
                ui(self.source_language, "your_turn_caption")
                if self.source_language != self.language
                else None
            )
            who = ui(self.language, "you")
            pill = hx("#3C9D5D")
        else:
            who = cue.character.name
            primary = cue.primary
            secondary = cue.secondary
            pill = hx(cue.character.color)

        x0, y0, x1, y1 = 34, 588, 1246, 704
        d.rounded_rectangle(Pp(x0 + 3, y0 + 5, x1 + 3, y1 + 5), radius=20 * S, fill=hx("#C9B08A"))
        d.rounded_rectangle(Pp(x0, y0, x1, y1), radius=20 * S, fill=(255, 255, 255))

        who_size = fit(who, 19, 220)
        pill_width = F(who_size).getlength(who) / S + 32
        d.rounded_rectangle(
            Pp(x0 + 18, y0 + 18, x0 + 18 + pill_width, y0 + 50),
            radius=16 * S,
            fill=pill,
        )
        d.text(
            Pp(x0 + 18 + pill_width / 2, y0 + 34),
            who,
            font=F(who_size),
            fill=(255, 255, 255),
            anchor="mm",
        )
        text_x = x0 + 36 + pill_width
        max_width = x1 - text_x - 24
        d.text(
            Pp(text_x, y0 + 35),
            primary,
            font=F(fit(primary, 27, max_width)),
            fill=INK,
            anchor="lm",
        )
        if secondary:
            d.text(
                Pp(text_x, y0 + 78),
                secondary,
                font=F(fit(secondary, 21, max_width, False), False),
                fill=GRAY,
                anchor="lm",
            )

    # ------------------------------------------------------------------ frame
    def render_frame(self, frame: int) -> Image.Image:
        t = frame / self.fps
        cue = self.timeline.current(t)
        scene = self.scene_by_id[cue.scene_id]
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        self.draw_progress(d, cue)
        self.draw_board(d, t, cue)

        target = list(ARMS[cue.line.arm])
        speaking_teacher = (
            cue.character.id == self.teacher_char.id
            and cue.start <= t <= cue.end + 0.2
        )
        if cue.line.arm == "point" and not speaking_teacher and not (
            cue.line.repeat and t > cue.end
        ):
            target = list(ARMS["down"])
        if cue.line.arm == "wave" and not speaking_teacher:
            target = list(ARMS["down"])
        if cue.line.arm == "wave" and speaking_teacher:
            target[1] += 22 * math.sin(t * 9)
        for k in range(2):
            self.arm_state[k] += (target[k] - self.arm_state[k]) * 0.22
        self.arm_state[2] = target[2]

        blink = (t % 3.7) < 0.11 or (t % 7.9) < 0.09
        look = 1 if cue.line.arm == "point" else (0.6 if scene.board.type == "dialog" else 0)
        mouth = self.env_value(self.teacher_char.id, t) if speaking_teacher else 0.0
        if scene.board.type == "dialog":
            mouth = mouth * 0.5 if speaking_teacher else 0.0
        teacher_figure(
            d,
            t,
            mouth,
            blink,
            self.arm_state,
            look,
            hair=hx(self.teacher_char.hair),
            long_hair=self.teacher_char.long_hair,
            outfit=hx(self.teacher_char.color),
        )
        self.draw_caption(d, t, cue)

        out = img.reduce(S)
        fade = min(clamp(t / 0.5), clamp((self.total - t) / 0.7))
        if fade < 1:
            out = Image.blend(Image.new("RGB", out.size, (0, 0, 0)), out, fade)
        return out

    # ------------------------------------------------------------------ output
    def preview(self, times: list[float], out_dir: str | Path) -> list[Path]:
        if not times:
            raise RenderError("preview needs at least one --at time")
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []
        for seconds in sorted(set(times)):
            if seconds < 0 or seconds > self.total + 1e-6:
                raise RenderError(
                    f"preview time {seconds:g}s is outside the video "
                    f"(0..{self.total:.1f}s)"
                )
            frame = min(self.nframes - 1, max(0, int(round(seconds * self.fps))))
            # Warm up the arm-smoothing state, matching make_video.py.
            for warm in range(max(0, frame - 30), frame):
                self.render_frame(warm)
            image = self.render_frame(frame)
            path = directory / f"preview_{self.language}_{seconds:g}s.png"
            image.save(path)
            results.append(path)
        return results

    def render_video(
        self,
        out_path: str | Path,
        audio_path: str | Path,
        *,
        crf: int = 20,
        preset: str = "medium",
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        output = Path(out_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not Path(audio_path).exists():
            raise RenderError(f"mixed audio is missing: {audio_path}")

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{W}x{H}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-i",
            str(audio_path),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise RenderError(f"could not start ffmpeg: {exc}") from exc

        stderr_lines: list[str] = []

        def drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line.decode("utf-8", "replace"))

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        started = time.monotonic()
        returncode: int | None = None
        try:
            assert proc.stdin is not None
            for frame in range(self.nframes):
                proc.stdin.write(self.render_frame(frame).tobytes())
                proc.stdin.flush()
                if progress is not None:
                    progress(frame + 1, self.nframes)
            proc.stdin.close()
            returncode = proc.wait(timeout=900)
        except BrokenPipeError as exc:
            try:
                returncode = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                returncode = proc.wait()
            detail = "".join(stderr_lines[-20:]).strip()
            raise RenderError(f"ffmpeg stopped early: {detail or exc}") from exc
        except KeyboardInterrupt:
            proc.kill()
            proc.wait()
            output.unlink(missing_ok=True)
            raise
        except Exception:
            proc.kill()
            proc.wait()
            output.unlink(missing_ok=True)
            raise
        finally:
            thread.join(timeout=5)

        if returncode != 0:
            detail = "".join(stderr_lines[-20:]).strip() or "unknown ffmpeg error"
            output.unlink(missing_ok=True)
            raise RenderError(f"ffmpeg failed (exit {returncode}): {detail}")
        if not output.exists() or output.stat().st_size < 1024:
            raise RenderError(f"ffmpeg did not create a valid video: {output}")
        elapsed = time.monotonic() - started
        print(
            f"[render] encoded {self.nframes} frame(s) in {elapsed:.1f}s "
            f"({self.nframes / max(elapsed, 1e-6):.1f} fps)",
            file=sys.stderr,
            flush=True,
        )
        return output
