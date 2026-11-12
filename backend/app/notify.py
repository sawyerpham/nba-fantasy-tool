"""Telegram notifications: the in-season watch list (GTD / OUT / swap / lock calls), the lineup moves (Sleeper lineup ->
best lineup) before the tip they must beat, and injury-tag changes on your roster (a player now OUT, now GTD / DTD, or
cleared). Which kinds go out, and the win chance a lock call must add, are the Notifications settings
(data/notify_prefs.json, Settings > Notifications). No roster-illegal pushes: the user can still move players then.

Setup: put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in backend/.env (see README.md, Telegram notifications); `python -m app.serve` then starts a
watcher thread, logging to data/cache/notify.log. Test delivery alone with: python -m app.notify "hello"
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .core.api.deps import get_state

log = logging.getLogger(__name__)
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
POLL_S = 60
MOVE_LEAD_MIN = 30   # a lineup move is pushed this long before the tip it must beat (like a LOCK reminder)
PREFS_FILE = "notify_prefs.json"   # Settings > Notifications, in the data directory
TELEGRAM = "https://api.telegram.org/bot{}/{}"
STATUS_TTL = 600   # seconds the bot's and chat's names from Telegram are kept (the Settings page polls them)
DOUBT_TAGS = {"GTD", "DTD", "Questionable", "Doubtful"}   # Sleeper's tags: might not play
OUT_TAGS = {"Out", "Suspended", "Sus", "IR"}            # Sleeper's tags: won't play
_UNSEEN = object()


class NotifyPrefs(BaseModel):
    """Which pushes to send. lock_min_wpa: a lock call goes out only when locking adds at least this many points of win
    chance over leaving the game open (0 = every lock call)."""
    lock: bool = True
    lock_min_wpa: int = Field(0, ge=0, le=100)
    swap: bool = True
    out: bool = True
    dtd: bool = True
    cleared: bool = True
    moves: bool = True


def read_prefs(store) -> dict:
    """The saved Notifications settings, defaults for anything unset or unreadable."""
    try:
        return NotifyPrefs.model_validate(store.read_json(PREFS_FILE) if store.exists(PREFS_FILE) else {}).model_dump()
    except (OSError, ValueError):
        return NotifyPrefs().model_dump()


def write_prefs(store, prefs: NotifyPrefs) -> dict:
    """Save the Notifications settings; the watcher reads them on its next poll."""
    store.write_json(PREFS_FILE, prefs.model_dump())
    return prefs.model_dump()


def load_env(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines from the .env file into os.environ (real environment variables win)."""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def configured() -> bool:
    """Whether the bot token and chat id are both set."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _redact(exc: Exception) -> str:
    """An error message with the bot token blanked: requests puts the request URL, token included, in its messages."""
    return str(exc).replace(os.environ.get("TELEGRAM_BOT_TOKEN") or "\0", "<token>")


def _call(method: str, **params) -> dict:
    """One Telegram Bot API call; its `result`, or ValueError with Telegram's description when it refuses."""
    r = requests.get(TELEGRAM.format(os.environ["TELEGRAM_BOT_TOKEN"], method), params=params, timeout=10).json()
    if not r.get("ok"):
        raise ValueError(r.get("description") or "Telegram refused the call")
    return r.get("result") or {}


def send(text: str) -> bool:
    """Send a Telegram message to the configured chat; False (logged) when unconfigured or Telegram refuses."""
    if not configured():
        return False
    try:
        r = requests.post(TELEGRAM.format(os.environ["TELEGRAM_BOT_TOKEN"], "sendMessage"),
                          json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("telegram send failed: %s", _redact(exc))
        return False


_status: tuple[float, dict] = (0.0, {})


def status() -> dict:
    """Whether Telegram is set up and what it is linked to: the chat id from .env plus, from Telegram (kept STATUS_TTL),
    the bot's username and the chat's name. Never the token."""
    global _status
    if not configured():
        return {"configured": False}
    if time.monotonic() - _status[0] < STATUS_TTL:
        return _status[1]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    out: dict = {"configured": True, "chat_id": chat_id}
    try:
        me, chat = _call("getMe"), _call("getChat", chat_id=chat_id)
        out["bot"] = me.get("username")
        out["chat"] = {"type": chat.get("type"), "username": chat.get("username"),
                       "name": " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("title")}
    except (requests.RequestException, ValueError) as exc:
        out["error"] = _redact(exc)
    _status = (time.monotonic(), out)
    return out


def title(w: dict) -> str:
    """One-line headline for a watch line (same wording as the Season tab's list)."""
    k = w["kind"]
    if k == "gtd":
        return f"{w['name']} GTD: check, else start {w['backup']}"
    if k == "out":
        return f"{w['name']} OUT: bench" + (f", start {w['backup']}" if w.get("backup") else "")
    if k == "lock":
        return f"Lock {w['name']} now"
    return f"SWAP: bench {w['name']}, start {w['backup']}" if w.get("decision") == "SWAP" else f"{w.get('decision')}: {w['backup']} check"


def _t(iso: str) -> datetime:
    """Parse a watch line's UTC time ("2026-11-08T00:30Z")."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def due(lines: list[dict], date: str, now: datetime, sent: set[str]) -> list[tuple[str, dict]]:
    """The (dedupe key, line) pairs whose alarm time has come, whose tip hasn't passed, and that weren't sent yet today."""
    out = []
    for w in lines:
        key = f"{date}|{w['kind']}|{w['sid']}|{w.get('backup_sid', '')}"
        if key in sent or not w.get("alarm"):
            continue
        if (w["alarm"] == "now" or _t(w["alarm"]) <= now) and (not w.get("by") or w["by"] == "now" or _t(w["by"]) > now):
            out.append((key, w))
    return out


def move_lines(moves: list[dict]) -> list[dict]:
    """Today's lineup moves that must beat a tip, as watch-like lines (for `due`) alarmed MOVE_LEAD_MIN before it."""
    return [{**m, "kind": "move", "backup_sid": m["to"], "alarm": (_t(m["by"]) - timedelta(minutes=MOVE_LEAD_MIN)).isoformat()}
            for m in moves if m.get("by")]


def moves_text(due_moves: list[dict], free: list[dict], tz: ZoneInfo) -> str:
    """One message for the lineup moves now due, plus the moves with no deadline (they free the slots), in Sleeper's words."""
    first = min(_t(m["by"]) for m in due_moves).astimezone(tz).strftime("%I:%M %p").lstrip("0")
    return "\n".join([f"Set your lineup before {first}:"] + [f"{m['name']}: {m['from']} → {m['to']}" for m in due_moves + free])


def status_lines(prev: dict, players: dict, mine: list[str]) -> list[dict]:
    """Injury-tag changes on your roster since the last poll (`prev`: sid -> the tag then, updated here): a player now
    OUT, now GTD / DTD, or cleared (tag gone, or Probable, after one of those). The first poll only records the tags.
    Lines are due at once; their dedupe key carries the new tag."""
    lines = []
    for sid in mine:
        p = players.get(sid) or {}
        tag, old = p.get("injury_tag"), prev.get(sid, _UNSEEN)
        prev[sid] = tag
        if old is _UNSEEN or old == tag:
            continue
        if tag in OUT_TAGS:
            change = "out"
        elif tag in DOUBT_TAGS:
            change = "dtd"
        elif old in OUT_TAGS | DOUBT_TAGS and (tag is None or tag == "Probable"):
            change = "cleared"
        else:
            continue
        name, note = p.get("name", sid), p.get("injury_note") or ""
        reason = "" if note == tag else note.removeprefix(f"{tag}: ")   # the note is "Out: Knee - Sprain" (week_view)
        text = f"{name} cleared to play (was {old})" if change == "cleared" else f"{name} is now {tag}" + (f": {reason}" if reason else "")
        lines.append({"kind": "status", "change": change, "sid": sid, "name": name, "backup_sid": tag or "ok", "alarm": "now", "text": text})
    return lines


def wanted(w: dict, prefs: dict, players_by_sid: dict) -> bool:
    """Whether the Notifications settings want this line: its kind's switch, and for a lock call the win chance it must add
    (lock_min_wpa, in points; a call whose win chances aren't known passes only at 0)."""
    k = w["kind"]
    if k == "lock":
        if not prefs["lock"]:
            return False
        q = players_by_sid.get(w["sid"]) or {}
        if prefs["lock_min_wpa"] <= 0:
            return True
        return q.get("win_lock") is not None and (q["win_lock"] - (q.get("win_wait") or 0)) * 100 >= prefs["lock_min_wpa"]
    if k == "status":
        return bool(prefs[w["change"]])
    return bool(prefs.get({"gtd": "dtd"}.get(k, k), True))


def watch_once(state, sent: set[str], tags: dict | None = None) -> None:
    """One poll: for every league, compute today's plan and send each newly due watch line the settings want, the injury-tag
    changes on your roster (`tags`: league -> sid -> last tag seen), and the lineup moves due (one message)."""
    from .core.api.deps import _session
    from .lockin.service import http_fetch, read_locks, team_plan, week_view

    tags = {} if tags is None else tags
    prefs = read_prefs(state.store)
    for lid in state.leagues.list_ids():
        try:
            session = _session(state, lid)
            view = week_view(session, http_fetch(state.platform), None)
            plan = team_plan(session, view, None, read_locks(state.store, lid, view["week"]))
        except Exception as exc:   # a league with no Sleeper link, or Sleeper down: skip this round
            log.info("watch skipped %s: %s", lid, exc)
            continue
        today, now = plan.get("today") or {}, datetime.now(timezone.utc)
        date = today.get("date") or view["today"]
        by_sid = {q["sid"]: q for q in plan.get("players", [])}
        lines = today.get("watch", []) + status_lines(tags.setdefault(lid, {}), view["players"], list(by_sid))
        for key, w in due([w for w in lines if wanted(w, prefs, by_sid)], date, now, sent):
            if send(w["text"] if w["kind"] == "status" else f"{title(w)}\n{w.get('text', '')}"):
                sent.add(key)
                log.info("sent %s", key)
        moves = due(move_lines(today.get("moves", [])), date, now, sent) if prefs["moves"] else []
        if moves and send(moves_text([m for _, m in moves], [m for m in today.get("moves", []) if not m.get("by")], ZoneInfo(view["tz"]))):
            sent.update(k for k, _ in moves)
            log.info("sent %s", [k for k, _ in moves])


def start_watcher(state) -> None:
    """Start the daemon thread that polls every POLL_S seconds (no-op unless Telegram is configured). Sent keys persist in cache/notified.json."""
    load_env()
    if not configured():
        log.info("telegram not configured (backend/.env): notifications off")
        return
    path = state.store.root / "cache" / "notified.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # the servers usually run hidden (start.ps1): keep the watcher's own log on disk
    handler = logging.FileHandler(path.parent / "notify.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        sent = set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        sent = set()
    tags: dict = {}   # injury tags seen last poll, per league: status changes are relative to this process's first poll

    def loop() -> None:
        """Poll forever, saving the sent keys after each round."""
        while True:
            before = len(sent)
            try:
                watch_once(state, sent, tags)
                if len(sent) != before:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(sorted(sent)), encoding="utf-8")
            except Exception:
                log.exception("watch round failed")
            time.sleep(POLL_S)

    threading.Thread(target=loop, daemon=True, name="telegram-watch").start()
    log.info("telegram watcher started")


router = APIRouter(prefix="/notify", tags=["notify"])


@router.get("")
def get_notify(state=Depends(get_state)) -> dict:
    """The Telegram link (configured, chat id, bot and chat names; never the token) and the Notifications settings."""
    load_env()
    return {**status(), "prefs": read_prefs(state.store)}


@router.put("/prefs")
def put_prefs(body: NotifyPrefs, state=Depends(get_state)) -> dict:
    """Save the Notifications settings; the watcher reads them on its next poll."""
    return write_prefs(state.store, body)


if __name__ == "__main__":
    import sys

    load_env()
    print("sent" if send(" ".join(sys.argv[1:]) or "NBA tool test message") else "NOT sent (check backend/.env)")
