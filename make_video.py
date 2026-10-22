import subprocess, os, math, wave, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("GENVIDEO_WORK", os.path.join(HERE, "build"))
os.makedirs(WORK, exist_ok=True)
OUT = os.environ.get("GENVIDEO_OUT", os.path.join(HERE, "output", "english_greetings_demo.mp4"))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
S = 2
W, H = 1280, 720
FPS = 24
SR = 22050


def find_font(cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("Không tìm thấy font hỗ trợ tiếng Việt. Đặt biến GENVIDEO_FONT_BOLD / GENVIDEO_FONT_REGULAR.")


FB = find_font([os.environ.get("GENVIDEO_FONT_BOLD"),
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf"])
FR = find_font([os.environ.get("GENVIDEO_FONT_REGULAR"),
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                "C:/Windows/Fonts/arial.ttf"])
_fc = {}


def F(sz, b=True):
    k = (int(sz), b)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FB if b else FR, int(sz * S))
    return _fc[k]


def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(c1, c2, a):
    a = max(0.0, min(1.0, a))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * a) for i in range(3))


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def Pp(*v):
    return [int(round(x * S)) for x in v]


WALL = hx("#F7EEDD")
WALL2 = hx("#F1E2C8")
BOARD = hx("#2E5A48")
WOOD = hx("#9A6534")
CHALK = hx("#F4F3EA")
YEL = hx("#FFD95A")
SOFT = hx("#B9D6C4")
SKIN = hx("#F3C9A3")
SKIN_D = hx("#E0A982")
HAIR = hx("#3F2A1E")
CARD = hx("#2F6FA8")
CARD_D = hx("#24588A")
ACCENT = hx("#E4572E")
INK = hx("#2B2B2B")
GRAY = hx("#6B6B6B")
BUBBLE = hx("#3B6E59")

# ---------------------------------------------------------------- script
SCENES = [
    ("intro", "Welcome", "Mở đầu"),
    ("hello", "Hello & Hi", "Lời chào cơ bản"),
    ("time", "Time of day", "Chào theo buổi"),
    ("how", "How are you?", "Hỏi thăm"),
    ("name", "Names", "Hỏi tên"),
    ("bye", "Goodbye", "Tạm biệt"),
    ("dialog", "Listen", "Nghe hội thoại"),
    ("repeat", "Practice", "Luyện nói"),
    ("outro", "Well done", "Kết thúc"),
]
SCENE_IDX = {s[0]: i for i, s in enumerate(SCENES)}

BOARDS = {
    "intro": {"type": "title", "kicker": "LESSON 1", "title": "Greetings", "sub": "Chào hỏi"},
    "hello": {"type": "cards", "items": [
        ("Hello!", "Xin chào", "bubble"),
        ("Hi!", "Chào (thân mật, với bạn bè)", "bubble")]},
    "time": {"type": "cards", "items": [
        ("Good morning", "Chào buổi sáng", "sunrise"),
        ("Good afternoon", "Chào buổi chiều", "sun"),
        ("Good evening", "Chào buổi tối", "moon"),
        ("NOTE", "“Good night” = chúc ngủ ngon, chỉ dùng khi tạm biệt", "note")]},
    "how": {"type": "cards", "items": [
        ("How are you?", "Bạn khỏe không?", "q"),
        ("I'm fine, thank you. And you?", "Mình khỏe, cảm ơn. Còn bạn?", "a")]},
    "name": {"type": "cards", "items": [
        ("What's your name?", "Bạn tên là gì?", "q"),
        ("My name is Lan.", "Tên mình là Lan.", "a"),
        ("Nice to meet you!", "Rất vui được gặp bạn!", "star")]},
    "bye": {"type": "cards", "items": [
        ("Goodbye!", "Tạm biệt!", "bubble"),
        ("See you later!", "Hẹn gặp lại nhé!", "bubble")]},
    "dialog": {"type": "dialog", "lines": [
        ("L", "Hi! I'm Lan. What's your name?"),
        ("N", "Hello, Lan. My name is Nam."),
        ("L", "Nice to meet you, Nam. How are you?"),
        ("N", "I'm fine, thank you. And you?"),
        ("L", "I'm great! See you later!"),
        ("N", "Goodbye!")]},
    "repeat": {"type": "repeat", "items": [
        ("Good morning.", "Chào buổi sáng."),
        ("How are you?", "Bạn khỏe không?"),
        ("Nice to meet you.", "Rất vui được gặp bạn.")]},
    "outro": {"type": "title", "kicker": "WELL DONE", "title": "Great job!", "sub": "Luyện tập mỗi ngày nhé!", "stars": True},
}


class Seg:
    pass


SEGS = []


def seg(scene, spk, text, vi, active=0, arm="point", pause=0.4, repeat=False, say=None):
    s = Seg()
    s.scene, s.spk, s.text, s.vi, s.active, s.arm = scene, spk, text, vi, active, arm
    s.pause, s.repeat, s.say = pause, repeat, say or text
    SEGS.append(s)


seg("intro", "T", "Hello everyone! Welcome to English Basics.", "Xin chào các bạn! Chào mừng đến với English Basics.", arm="wave")
seg("intro", "T", "Today, we will learn how to greet people in English.", "Hôm nay chúng ta học cách chào hỏi bằng tiếng Anh.", arm="point")

seg("hello", "T", "The easiest greeting is: Hello!", "Lời chào dễ nhất là: Hello! (Xin chào)", 0)
seg("hello", "T", "With friends, you can just say: Hi!", "Với bạn bè, bạn chỉ cần nói: Hi!", 1)

seg("time", "T", "In the morning, say: Good morning.", "Buổi sáng, hãy nói: Good morning.", 0)
seg("time", "T", "After lunch, say: Good afternoon.", "Sau bữa trưa, hãy nói: Good afternoon.", 1)
seg("time", "T", "In the evening, say: Good evening.", "Buổi tối, hãy nói: Good evening.", 2)
seg("time", "T", "Remember! Good night is only for saying goodbye before bed.", "Lưu ý! Good night chỉ dùng khi chào tạm biệt, đi ngủ.", 3)

seg("how", "T", "To ask about someone, say: How are you?", "Để hỏi thăm ai đó, hãy nói: How are you?", 0)
seg("how", "T", "You can answer: I'm fine, thank you. And you?", "Bạn có thể trả lời: I'm fine, thank you. And you?", 1)

seg("name", "T", "To ask a name, say: What's your name?", "Để hỏi tên, hãy nói: What's your name?", 0)
seg("name", "T", "Answer: My name is Lan.", "Trả lời: My name is Lan. (Tên mình là Lan.)", 1)
seg("name", "T", "Then smile and say: Nice to meet you!", "Rồi mỉm cười và nói: Nice to meet you!", 2)

seg("bye", "T", "When you leave, say: Goodbye!", "Khi rời đi, hãy nói: Goodbye!", 0, arm="wave")
seg("bye", "T", "Or more casually: See you later!", "Hoặc thân mật hơn: See you later!", 1)

seg("dialog", "T", "Now, let's listen to a short conversation.", "Bây giờ, cùng nghe một đoạn hội thoại ngắn nhé.", -1, pause=0.6)
dl = BOARDS["dialog"]["lines"]
dvi = ["Chào! Mình là Lan. Bạn tên gì?", "Chào Lan. Mình tên là Nam.",
       "Rất vui được gặp bạn, Nam. Bạn khỏe không?", "Mình khỏe, cảm ơn. Còn bạn?",
       "Mình rất khỏe! Hẹn gặp lại nhé!", "Tạm biệt!"]
for i, (who, line) in enumerate(dl):
    seg("dialog", "T" if who == "L" else "N", line, dvi[i], i, arm="down", pause=0.45)

seg("repeat", "T", "Your turn! Repeat after me.", "Đến lượt bạn! Hãy nhắc lại theo cô.", -1, pause=0.4)
for i, (en, vi) in enumerate(BOARDS["repeat"]["items"]):
    seg("repeat", "T", en, vi, i, pause=3.2, repeat=True)

seg("outro", "T", "Great job! Practice these greetings every day.", "Giỏi lắm! Hãy luyện các câu chào này mỗi ngày.", arm="point")
seg("outro", "T", "See you in the next lesson. Goodbye!", "Hẹn gặp lại ở bài sau. Tạm biệt!", arm="wave", pause=1.6)

# ---------------------------------------------------------------- audio
VOICE = {"T": ("en-us+f3", 55, 138), "N": ("en-us+m3", 68, 140)}


def read_wav(p):
    with wave.open(p) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if sr != SR:
        x = np.linspace(0, len(a) - 1, int(len(a) * SR / sr))
        a = np.interp(x, np.arange(len(a)), a)
    # trim silence
    nz = np.where(np.abs(a) > 0.01)[0]
    if len(nz):
        a = a[max(0, nz[0] - 200): nz[-1] + 400]
    return a


for i, s in enumerate(SEGS):
    v, p, sp = VOICE[s.spk]
    path = f"{WORK}/seg{i:02d}.wav"
    subprocess.run(["espeak-ng", "-v", v, "-p", str(p), "-s", str(sp), "-g", "4", "-w", path, s.say], check=True)
    s.audio = read_wav(path)

t = 0.9
scene_show = {}
chimes = [0.25]
prev = None
for i, s in enumerate(SEGS):
    if prev is not None and s.scene != prev.scene:
        t += 0.6
        scene_show[s.scene] = t
        chimes.append(t)
        t += 0.6
        s.show = t - 0.6
    elif prev is None:
        scene_show[s.scene] = 0.0
        s.show = 0.0
    else:
        s.show = t
    s.start = t
    s.dur = len(s.audio) / SR
    s.end = t + s.dur
    t = s.end + s.pause
    prev = s
TOTAL = t + 0.8
NF = int(TOTAL * FPS)
print("duration", round(TOTAL, 1), "s, frames", NF)

nsamp = int(TOTAL * SR) + SR
trackT = np.zeros(nsamp, np.float32)
trackN = np.zeros(nsamp, np.float32)
for s in SEGS:
    a = s.audio * 0.9
    st = int(s.start * SR)
    (trackT if s.spk == "T" else trackN)[st:st + len(a)] += a
mix = trackT + trackN
for c in chimes:
    n = int(0.7 * SR)
    tt = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * 784 * tt) * np.exp(-tt * 6) +
            0.7 * np.sin(2 * np.pi * 1175 * tt) * np.exp(-np.maximum(tt - 0.12, 0) * 6) * (tt > 0.12))
    st = int(c * SR)
    mix[st:st + n] += 0.12 * tone[: len(mix[st:st + n])]
mix = np.clip(mix, -1, 1)
with wave.open(f"{WORK}/mix.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())


def envelope(tr):
    hop = SR // FPS
    e = np.array([np.sqrt(np.mean(tr[i * hop:(i + 1) * hop] ** 2) + 1e-9) for i in range(NF)])
    ref = np.percentile(e[e > 0.005], 90) if np.any(e > 0.005) else 1
    e = np.clip(e / ref, 0, 1)
    e[e < 0.08] = 0
    return e


envT, envN = envelope(trackT), envelope(trackN)

# ---------------------------------------------------------------- static background
BX0, BY0, BX1, BY1 = 470, 48, 1250, 548
IX0, IY0, IX1, IY1 = BX0 + 16, BY0 + 16, BX1 - 16, BY1 - 16
BCX = (IX0 + IX1) / 2

bg = Image.new("RGB", (W * S, H * S), WALL)
d = ImageDraw.Draw(bg)
for y in range(H * S):
    d.line([(0, y), (W * S, y)], fill=lerp(WALL, WALL2, y / (H * S)))
# floor
d.rectangle(Pp(0, 560, W, H), fill=hx("#D9C3A0"))
# decorative circles
for (x, y, r, c) in [(110, 160, 90, "#F2DFC0"), (360, 120, 50, "#F4E4C8"), (60, 470, 40, "#F0DCBA")]:
    d.ellipse(Pp(x - r, y - r, x + r, y + r), fill=hx(c))
# board shadow + frame
sh = Image.new("L", (W * S, H * S), 0)
ImageDraw.Draw(sh).rounded_rectangle(Pp(BX0 + 6, BY0 + 10, BX1 + 6, BY1 + 12), radius=18 * S, fill=90)
sh = sh.filter(ImageFilter.GaussianBlur(14 * S))
bg = Image.composite(Image.new("RGB", bg.size, hx("#8C7A5E")), bg, sh)
d = ImageDraw.Draw(bg)
d.rounded_rectangle(Pp(BX0, BY0, BX1, BY1), radius=14 * S, fill=WOOD)
d.rounded_rectangle(Pp(BX0 + 4, BY0 + 4, BX1 - 4, BY1 - 4), radius=12 * S, outline=hx("#B27A44"), width=2 * S)
# board surface with texture
bw, bh = (IX1 - IX0) * S, (IY1 - IY0) * S
surf = Image.new("RGB", (bw, bh), BOARD)
sd = ImageDraw.Draw(surf)
rnd = random.Random(3)
for _ in range(9):
    x, y = rnd.randint(0, bw), rnd.randint(0, bh)
    r = rnd.randint(80, 220) * S
    sd.ellipse([x - r, y - r // 2, x + r, y + r // 2], fill=lerp(BOARD, CHALK, 0.045))
surf = surf.filter(ImageFilter.GaussianBlur(30 * S))
sd = ImageDraw.Draw(surf)
for _ in range(1800):
    x, y = rnd.randint(0, bw - 1), rnd.randint(0, bh - 1)
    sd.point((x, y), fill=lerp(BOARD, CHALK, rnd.uniform(0.05, 0.16)))
bg.paste(surf, Pp(IX0, IY0))
BOARD_BG = surf.copy()
# chalk tray
d.rounded_rectangle(Pp(BX0 + 30, BY1 - 4, BX1 - 30, BY1 + 10), radius=5 * S, fill=hx("#7E5129"))
d.rounded_rectangle(Pp(BX1 - 140, BY1 - 9, BX1 - 100, BY1 - 1), radius=3 * S, fill=CHALK)
d.rounded_rectangle(Pp(BX1 - 90, BY1 - 9, BX1 - 60, BY1 - 1), radius=3 * S, fill=YEL)
# header pill
d.rounded_rectangle(Pp(34, 30, 404, 78), radius=24 * S, fill=ACCENT)
d.text(Pp(56, 54), "ENGLISH BASICS", font=F(21), fill=(255, 255, 255), anchor="lm")
d.text(Pp(268, 54), "Lesson 1", font=F(18, False), fill=hx("#FFE3D8"), anchor="lm")
BG = bg


# ---------------------------------------------------------------- drawing helpers
def star(d, cx, cy, r, col, rot=0):
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5 + rot
        rr = r if k % 2 == 0 else r * 0.45
        pts.append(((cx + rr * math.cos(ang)) * S, (cy + rr * math.sin(ang)) * S))
    d.polygon(pts, fill=col)


def icon(d, kind, x, y, a):
    c = lerp(BOARD, CHALK, a)
    y_ = lerp(BOARD, YEL, a)
    if kind == "bubble":
        d.rounded_rectangle(Pp(x - 20, y - 16, x + 20, y + 12), radius=10 * S, outline=c, width=3 * S)
        d.polygon([Pp(x - 8, y + 11)[0:2], Pp(x - 14, y + 22)[0:2], Pp(x + 2, y + 11)[0:2]], fill=c)
        for k in (-9, 0, 9):
            d.ellipse(Pp(x + k - 2.5, y - 4.5, x + k + 2.5, y + 0.5), fill=c)
    elif kind == "sun":
        for k in range(8):
            an = k * math.pi / 4
            d.line(Pp(x + 15 * math.cos(an), y + 15 * math.sin(an), x + 23 * math.cos(an), y + 23 * math.sin(an)), fill=y_, width=3 * S)
        d.ellipse(Pp(x - 11, y - 11, x + 11, y + 11), fill=y_)
    elif kind == "sunrise":
        d.pieslice(Pp(x - 14, y - 8, x + 14, y + 20), 180, 360, fill=y_)
        for k in range(5):
            an = math.pi + (k + 0.5) * math.pi / 5
            d.line(Pp(x + 18 * math.cos(an), y + 6 + 18 * math.sin(an), x + 25 * math.cos(an), y + 6 + 25 * math.sin(an)), fill=y_, width=3 * S)
        d.line(Pp(x - 24, y + 7, x + 24, y + 7), fill=c, width=3 * S)
    elif kind == "moon":
        d.ellipse(Pp(x - 15, y - 15, x + 15, y + 15), fill=y_)
        d.ellipse(Pp(x - 6, y - 19, x + 20, y + 9), fill=BOARD)
        star(d, x + 16, y + 10, 4, c)
    elif kind in ("q", "a", "note"):
        col = y_ if kind == "note" else c
        d.ellipse(Pp(x - 18, y - 18, x + 18, y + 18), outline=col, width=3 * S)
        ch = {"q": "?", "a": "✓", "note": "!"}[kind]
        d.text(Pp(x, y + 1), ch, font=F(22), fill=col, anchor="mm")
    elif kind == "star":
        star(d, x, y, 18, y_)


def fit(txt, sz, maxw, b=True):
    while F(sz, b).getlength(txt) > maxw * S and sz > 14:
        sz -= 1
    return sz


def wrap(txt, sz, maxw, b=False):
    words, lines, cur = txt.split(), [], ""
    for w_ in words:
        tst = (cur + " " + w_).strip()
        if F(sz, b).getlength(tst) <= maxw * S:
            cur = tst
        else:
            lines.append(cur); cur = w_
    lines.append(cur)
    return lines


def face(d, cx, cy, r, hair, mouth, long_hair, blink):
    # small avatar for the dialogue
    if long_hair:
        d.ellipse(Pp(cx - r * 1.15, cy - r * 1.1, cx + r * 1.15, cy + r * 1.25), fill=hair)
    d.ellipse(Pp(cx - r, cy - r, cx + r, cy + r), fill=SKIN)
    d.chord(Pp(cx - r * 1.05, cy - r * 1.15, cx + r * 1.05, cy + r * 0.45), 180, 360, fill=hair)
    ey = cy + r * 0.12
    for sx in (-1, 1):
        ex = cx + sx * r * 0.38
        if blink:
            d.line(Pp(ex - r * 0.12, ey, ex + r * 0.12, ey), fill=INK, width=2 * S)
        else:
            d.ellipse(Pp(ex - r * 0.1, ey - r * 0.13, ex + r * 0.1, ey + r * 0.13), fill=INK)
    my = cy + r * 0.52
    if mouth > 0.05:
        mh = r * (0.08 + 0.32 * mouth)
        d.ellipse(Pp(cx - r * 0.22, my - mh / 2, cx + r * 0.22, my + mh / 2), fill=hx("#8E2F2F"))
    else:
        d.arc(Pp(cx - r * 0.25, my - r * 0.22, cx + r * 0.25, my + r * 0.12), 20, 160, fill=hx("#8E2F2F"), width=2 * S)


def limb(d, p0, a1, a2, L1, L2, sleeve, stick=False):
    r1, r2 = math.radians(a1), math.radians(a2)
    e = (p0[0] + L1 * math.cos(r1), p0[1] + L1 * math.sin(r1))
    h = (e[0] + L2 * math.cos(r2), e[1] + L2 * math.sin(r2))
    wdt = 24
    d.line(Pp(*p0, *e), fill=sleeve, width=wdt * S)
    d.ellipse(Pp(e[0] - wdt / 2, e[1] - wdt / 2, e[0] + wdt / 2, e[1] + wdt / 2), fill=sleeve)
    d.line(Pp(*e, *h), fill=sleeve, width=(wdt - 2) * S)
    if stick:
        tip = (h[0] + 78 * math.cos(r2 - 0.08), h[1] + 78 * math.sin(r2 - 0.08))
        d.line(Pp(*h, *tip), fill=hx("#7A4A22"), width=5 * S)
        d.ellipse(Pp(tip[0] - 4, tip[1] - 4, tip[0] + 4, tip[1] + 4), fill=CHALK)
    d.ellipse(Pp(h[0] - 13, h[1] - 13, h[0] + 13, h[1] + 13), fill=SKIN)
    return h


def teacher(d, t, mouth, blink, arm, look):
    cx = 245
    dy = 2.5 * math.sin(t * 1.7)
    hy = 300 + dy  # head center
    # hair back
    d.ellipse(Pp(cx - 80, hy - 82, cx + 80, hy + 108), fill=HAIR)
    # body
    d.rounded_rectangle(Pp(cx - 84, 428, cx + 84, 680), radius=44 * S, fill=CARD)
    d.polygon([tuple(Pp(cx - 30, 426)), tuple(Pp(cx + 30, 426)), tuple(Pp(cx, 492))], fill=(255, 255, 255))
    d.line(Pp(cx - 30, 428, cx, 492), fill=CARD_D, width=3 * S)
    d.line(Pp(cx + 30, 428, cx, 492), fill=CARD_D, width=3 * S)
    for by in (510, 545, 580):
        d.ellipse(Pp(cx - 4, by - 4, cx + 4, by + 4), fill=hx("#F2D27A"))
    # neck
    d.rectangle(Pp(cx - 16, hy + 50, cx + 16, 432), fill=SKIN_D)
    # left arm (static)
    limb(d, (cx - 66, 452), 102 + 2 * math.sin(t * 1.3), 94, 78, 70, CARD)
    # right arm
    limb(d, (cx + 66, 452), arm[0], arm[1], 80, 72, CARD, stick=arm[2] > 0.5)
    # head
    d.ellipse(Pp(cx - 64, hy - 70, cx + 64, hy + 70), fill=SKIN)
    # ears
    for sx in (-1, 1):
        d.ellipse(Pp(cx + sx * 64 - 9, hy - 2, cx + sx * 64 + 9, hy + 22), fill=SKIN)
    d.ellipse(Pp(cx + 64 - 3, hy + 20, cx + 64 + 5, hy + 28), fill=YEL)
    d.ellipse(Pp(cx - 64 - 5, hy + 20, cx - 64 + 3, hy + 28), fill=YEL)
    # fringe
    d.chord(Pp(cx - 70, hy - 84, cx + 70, hy + 6), 180, 360, fill=HAIR)
    d.pieslice(Pp(cx - 70, hy - 84, cx + 90, hy + 40), 180, 250, fill=HAIR)
    # hair bun clip
    d.ellipse(Pp(cx + 40, hy - 78, cx + 58, hy - 60), fill=ACCENT)
    # eyes
    ey = hy + 6
    lx = 3 * look
    for sx in (-1, 1):
        ex = cx + sx * 25
        d.arc(Pp(ex - 13, ey - 26, ex + 13, ey - 10), 200, 340, fill=HAIR, width=3 * S)
        if blink:
            d.arc(Pp(ex - 11, ey - 6, ex + 11, ey + 6), 10, 170, fill=INK, width=3 * S)
        else:
            d.ellipse(Pp(ex - 10, ey - 12, ex + 10, ey + 12), fill=(255, 255, 255))
            d.ellipse(Pp(ex - 6 + lx, ey - 7, ex + 6 + lx, ey + 7), fill=hx("#3A2A20"))
            d.ellipse(Pp(ex - 2 + lx, ey - 5, ex + 2 + lx, ey - 1), fill=(255, 255, 255))
    # cheeks
    for sx in (-1, 1):
        d.ellipse(Pp(cx + sx * 40 - 11, hy + 22, cx + sx * 40 + 11, hy + 34), fill=hx("#F2A79A"))
    # nose
    d.arc(Pp(cx - 6, hy + 12, cx + 6, hy + 26), 300, 60, fill=SKIN_D, width=3 * S)
    # mouth
    my = hy + 42
    if mouth > 0.05:
        mh = 5 + 20 * mouth
        mw = 17 - 3 * mouth
        d.ellipse(Pp(cx - mw, my - mh / 2, cx + mw, my + mh / 2), fill=hx("#8E2F2F"))
        if mh > 12:
            d.ellipse(Pp(cx - mw * 0.6, my + mh / 2 - 7, cx + mw * 0.6, my + mh / 2 - 1), fill=hx("#E07A7A"))
    else:
        d.arc(Pp(cx - 18, my - 14, cx + 18, my + 8), 20, 160, fill=hx("#8E2F2F"), width=4 * S)


# ---------------------------------------------------------------- per-frame state
for s in SEGS:
    s.item_show = None
item_show = {}  # (scene, idx) -> time
for s in SEGS:
    k = (s.scene, s.active)
    if k not in item_show:
        item_show[k] = s.show
scene_order = []
for s in SEGS:
    if s.scene not in scene_order:
        scene_order.append(s.scene)


def current(t):
    cur = SEGS[0]
    for s in SEGS:
        if s.show <= t:
            cur = s
    return cur


def draw_board(d, t, s):
    b = BOARDS[s.scene]
    sa = ease((t - scene_show[s.scene]) / 0.45)
    i = scene_order.index(s.scene)
    if i + 1 < len(scene_order):
        nxt = scene_show[scene_order[i + 1]]
        sa *= ease((nxt - t) / 0.3)
    if b["type"] == "title":
        d.text(Pp(BCX, 150), b["kicker"], font=F(26), fill=lerp(BOARD, YEL, sa), anchor="mm")
        tsz = 88
        pop = 1 + 0.06 * math.sin(clamp((t - scene_show[s.scene]) / 0.6) * math.pi)
        d.text(Pp(BCX, 262), b["title"], font=F(tsz * pop), fill=lerp(BOARD, CHALK, sa), anchor="mm")
        wline = F(tsz).getlength(b["title"]) / S
        prog = ease((t - scene_show[s.scene] - 0.3) / 0.8)
        d.line(Pp(BCX - wline / 2, 330, BCX - wline / 2 + wline * prog, 330), fill=lerp(BOARD, YEL, sa), width=5 * S)
        d.text(Pp(BCX, 385), b["sub"], font=F(36, False), fill=lerp(BOARD, SOFT, sa), anchor="mm")
        if b.get("stars"):
            for k, (x, y, r) in enumerate([(600, 140, 16), (1120, 160, 20), (640, 430, 13), (1100, 440, 17), (860, 470, 11)]):
                tw = 0.6 + 0.4 * math.sin(t * 4 + k)
                star(d, x, y, r * tw, lerp(BOARD, YEL, sa), rot=t * 0.5 + k)
    elif b["type"] == "cards":
        items = b["items"]
        n = len(items)
        rh = min(112, 440 / n)
        y0 = IY0 + (IY1 - IY0 - n * rh) / 2
        for k, (en, vi, ic) in enumerate(items):
            if k > s.active:
                continue
            ia = ease((t - item_show.get((s.scene, k), 0)) / 0.45) * sa
            act = (k == s.active)
            dim = 1.0 if act else 0.62
            cy = y0 + k * rh + rh / 2
            slide = (1 - ease((t - item_show.get((s.scene, k), 0)) / 0.45)) * 30
            x0 = IX0 + 50 + slide
            icon(d, ic, x0 + 10, cy - 8, ia * dim)
            if ic == "note":
                lines = wrap(vi, 23, 600, False)
                for j, ln in enumerate(lines):
                    d.text(Pp(x0 + 50, cy - 8 - (len(lines) - 1) * 15 + j * 30), ln, font=F(23, False),
                           fill=lerp(BOARD, YEL if act else CHALK, ia * dim), anchor="lm")
                continue
            sz = fit(en, 46, 600)
            col = YEL if act else CHALK
            d.text(Pp(x0 + 50, cy - 14), en, font=F(sz), fill=lerp(BOARD, col, ia * dim), anchor="ls")
            d.text(Pp(x0 + 52, cy + 22), vi, font=F(23, False), fill=lerp(BOARD, SOFT, ia * dim), anchor="ls")
            if act:
                wl = F(sz).getlength(en) / S
                pr = ease((t - item_show.get((s.scene, k), 0) - 0.4) / 0.7)
                d.line(Pp(x0 + 50, cy - 4, x0 + 50 + wl * pr, cy - 4), fill=lerp(BOARD, YEL, ia * 0.8), width=3 * S)
    elif b["type"] == "dialog":
        d.text(Pp(BCX, IY0 + 30), "LISTEN  ·  Nghe hội thoại", font=F(22), fill=lerp(BOARD, YEL, sa), anchor="mm")
        fi = int(t * FPS)
        blink = (t % 3.3) < 0.12
        for k, (who, line) in enumerate(b["lines"]):
            if k > s.active:
                continue
            ia = ease((t - item_show.get((s.scene, k), 0)) / 0.4) * sa
            act = (k == s.active)
            cy = IY0 + 88 + k * 66
            fsz = 23
            tw = F(fsz, False).getlength(line) / S
            if who == "L":
                ax = IX0 + 34
                bx0, bx1 = ax + 34, ax + 34 + tw + 32
            else:
                ax = IX1 - 34
                bx1 = ax - 34
                bx0 = bx1 - tw - 32
            bc = lerp(BOARD, BUBBLE, ia)
            oc = lerp(BOARD, YEL if act else lerp(BUBBLE, CHALK, 0.35), ia)
            d.rounded_rectangle(Pp(bx0, cy - 24, bx1, cy + 24), radius=20 * S, fill=bc, outline=oc, width=2 * S)
            d.text(Pp((bx0 + bx1) / 2, cy + 1), line, font=F(fsz, False), fill=lerp(BOARD, CHALK, ia), anchor="mm")
            if ia > 0.05:
                mouth = (envT[fi] if who == "L" else envN[fi]) if act else 0
                face(d, ax, cy, 22, HAIR if who == "L" else hx("#1E1E1E"), mouth, who == "L", blink)
    elif b["type"] == "repeat":
        d.text(Pp(BCX, IY0 + 50), "REPEAT AFTER ME", font=F(26), fill=lerp(BOARD, YEL, sa), anchor="mm")
        d.text(Pp(BCX, IY0 + 85), "Nghe và nhắc lại", font=F(20, False), fill=lerp(BOARD, SOFT, sa), anchor="mm")
        if s.active >= 0:
            en, vi = b["items"][s.active]
            ia = ease((t - item_show[(s.scene, s.active)]) / 0.4) * sa
            d.text(Pp(BCX, 255), en, font=F(fit(en, 70, 680)), fill=lerp(BOARD, CHALK, ia), anchor="mm")
            d.text(Pp(BCX, 318), vi, font=F(30, False), fill=lerp(BOARD, SOFT, ia), anchor="mm")
            for k in range(3):
                c = YEL if k <= s.active else lerp(BOARD, CHALK, 0.3)
                d.ellipse(Pp(BCX - 30 + k * 30 - 6, 185 - 6, BCX - 30 + k * 30 + 6, 185 + 6), fill=lerp(BOARD, c, sa))
            if t > s.end + 0.1:
                p = clamp((t - s.end - 0.1) / (s.pause - 0.4))
                pa = ease((t - s.end - 0.1) / 0.3) * sa
                d.text(Pp(BCX, 395), "Your turn!", font=F(30), fill=lerp(BOARD, YEL, pa), anchor="mm")
                d.rounded_rectangle(Pp(BCX - 200, 430, BCX + 200, 446), radius=8 * S, fill=lerp(BOARD, BUBBLE, pa))
                if p > 0.02:
                    d.rounded_rectangle(Pp(BCX - 200, 430, BCX - 200 + 400 * p, 446), radius=8 * S, fill=lerp(BOARD, YEL, pa))
        else:
            d.text(Pp(BCX, 280), "Your turn!", font=F(64), fill=lerp(BOARD, CHALK, sa), anchor="mm")
            d.text(Pp(BCX, 345), "Đến lượt bạn!", font=F(30, False), fill=lerp(BOARD, SOFT, sa), anchor="mm")


def draw_progress(d, s):
    cur = SCENE_IDX[s.scene]
    label = SCENES[cur]
    d.text(Pp(40, 112), label[1], font=F(26), fill=INK, anchor="lm")
    d.text(Pp(40, 142), label[2], font=F(18, False), fill=GRAY, anchor="lm")
    for k in range(len(SCENES)):
        x = 46 + k * 22
        c = ACCENT if k == cur else (hx("#E9B9A6") if k < cur else hx("#DCCBB0"))
        r = 7 if k == cur else 5
        d.ellipse(Pp(x - r, 178 - r, x + r, 178 + r), fill=c)


def draw_caption(d, t, s):
    if s.repeat and t > s.end + 0.1:
        who, en, vi = "Bạn", "Your turn! Say it out loud.", "Đến lượt bạn — hãy nói to lên nhé!"
        pill = hx("#3C9D5D")
    else:
        who = "Cô Lan" if s.spk == "T" else "Nam"
        if s.scene == "dialog" and s.active >= 0 and s.spk == "T":
            who = "Lan"
        en, vi = s.text, s.vi
        pill = ACCENT if s.spk == "T" else CARD
    x0, y0, x1, y1 = 34, 588, 1246, 704
    d.rounded_rectangle(Pp(x0 + 3, y0 + 5, x1 + 3, y1 + 5), radius=20 * S, fill=hx("#C9B08A"))
    d.rounded_rectangle(Pp(x0, y0, x1, y1), radius=20 * S, fill=(255, 255, 255))
    pw = F(19).getlength(who) / S + 32
    d.rounded_rectangle(Pp(x0 + 18, y0 + 18, x0 + 18 + pw, y0 + 50), radius=16 * S, fill=pill)
    d.text(Pp(x0 + 18 + pw / 2, y0 + 34), who, font=F(19), fill=(255, 255, 255), anchor="mm")
    tx = x0 + 36 + pw
    maxw = x1 - tx - 24
    d.text(Pp(tx, y0 + 35), en, font=F(fit(en, 27, maxw)), fill=INK, anchor="lm")
    d.text(Pp(tx, y0 + 78), vi, font=F(fit(vi, 21, maxw, False), False), fill=GRAY, anchor="lm")


ARMS = {"down": (78, 92, 0), "point": (-14, -30, 1), "wave": (-62, -100, 0)}
arm_state = list(ARMS["down"])


def render(f):
    t = f / FPS
    s = current(t)
    img = BG.copy()
    d = ImageDraw.Draw(img)
    draw_progress(d, s)
    draw_board(d, t, s)
    # teacher
    target = list(ARMS[s.arm])
    speaking_T = s.start <= t <= s.end + 0.2 and s.spk == "T"
    if s.arm == "point" and not speaking_T and not (s.repeat and t > s.end):
        target = list(ARMS["down"])
    if s.arm == "wave" and not speaking_T:
        target = list(ARMS["down"])
    if s.arm == "wave" and speaking_T:
        target[1] += 22 * math.sin(t * 9)
    for k in range(2):
        arm_state[k] += (target[k] - arm_state[k]) * 0.22
    arm_state[2] = target[2]
    blink = (t % 3.7) < 0.11 or (t % 7.9) < 0.09
    look = 1 if s.arm == "point" else (0.6 if s.scene == "dialog" else 0)
    mouth = 0 if (s.scene == "dialog" and s.active >= 0) else envT[f]
    if s.scene == "dialog" and s.active >= 0 and s.spk == "T":
        mouth = envT[f] * 0.5  # teacher reads Lan's part softly in sync
    teacher(d, t, mouth, blink, arm_state, look)
    draw_caption(d, t, s)
    # fades
    out = img.reduce(S)
    a = min(clamp(t / 0.5), clamp((TOTAL - t) / 0.7))
    if a < 1:
        out = Image.blend(Image.new("RGB", out.size, (0, 0, 0)), out, a)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        for tt in [float(x) for x in sys.argv[2:]]:
            f = int(tt * FPS)
            # warm up arm smoothing
            for g in range(max(0, f - 30), f):
                render(g)
            render(f).save(f"{WORK}/prev_{tt:.0f}.png")
        sys.exit()
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", f"{WORK}/mix.wav",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", "-movflags", "+faststart", OUT],
                          stdin=subprocess.PIPE)
    for f in range(NF):
        ff.stdin.write(render(f).tobytes())
        if f % 240 == 0:
            print("frame", f, "/", NF, flush=True)
    ff.stdin.close()
    ff.wait()
    print("done", OUT)
