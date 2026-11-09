"""Telegram notifications for the in-season watch list (GTD / OUT / swap / lock calls).

Setup: put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in backend/.env (see README.md, Telegram notifications); `python -m app.serve` then starts a
watcher thread. Test delivery alone with: python -m app.notify "hello"
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
POLL_S = 60


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


def send(text: str) -> bool:
    """Send a Telegram message to the configured chat; False (logged) when unconfigured or Telegram refuses."""
    if not configured():
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                          json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("telegram send failed: %s", exc)
        return False


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


def watch_once(state, sent: set[str]) -> None:
    """One poll: for every league, compute today's watch lines and send each newly due one."""
    from .core.api.deps import _session
    from .lockin.service import http_fetch, read_locks, team_plan, week_view

    for lid in state.leagues.list_ids():
        try:
            session = _session(state, lid)
            view = week_view(session, http_fetch(state.platform), None)
            today = team_plan(session, view, None, read_locks(state.store, lid, view["week"])).get("today") or {}
        except Exception as exc:   # a league with no Sleeper link, or Sleeper down: skip this round
            log.debug("watch skipped %s: %s", lid, exc)
            continue
        for key, w in due(today.get("watch", []), today.get("date", ""), datetime.now(timezone.utc), sent):
            if send(f"{title(w)}\n{w.get('text', '')}"):
                sent.add(key)


def start_watcher(state) -> None:
    """Start the daemon thread that polls every POLL_S seconds (no-op unless Telegram is configured). Sent keys persist in cache/notified.json."""
    load_env()
    if not configured():
        log.info("telegram not configured (backend/.env): notifications off")
        return
    path = state.store.root / "cache" / "notified.json"
    try:
        sent = set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        sent = set()

    def loop() -> None:
        """Poll forever, saving the sent keys after each round."""
        while True:
            before = len(sent)
            try:
                watch_once(state, sent)
                if len(sent) != before:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(sorted(sent)), encoding="utf-8")
            except Exception:
                log.exception("watch round failed")
            time.sleep(POLL_S)

    threading.Thread(target=loop, daemon=True, name="telegram-watch").start()
    log.info("telegram watcher started")


if __name__ == "__main__":
    import sys

    load_env()
    print("sent" if send(" ".join(sys.argv[1:]) or "NBA tool test message") else "NOT sent (check backend/.env)")
