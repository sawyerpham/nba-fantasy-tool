"""Seed PlayerOverrides from Sleeper attributes with source tracking.

Eligibility and injury come straight from Sleeper and are re-seeded on every pull (there is no manual
editing); records without Sleeper data keep whatever they had (or get an empty "none" override). The
user's free-text notes are never touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from ..models.players import InjuryStatus, PlayerOverrides, PlayerRecord
from ..providers.base import utcnow

DEFAULT_SLEEPER_INJURY_MAP: dict[str, InjuryStatus] = {
    "DTD": "day_to_day",
    "Out": "out_short_term",
    "IR": "out_long_term",
}


def injury_note_from(body_part: str | None, notes: str | None) -> str:
    parts = [p.strip() for p in (body_part, notes) if p and p.strip()]
    return " — ".join(parts)


def map_injury(raw: str | None, injury_map: Mapping[str, InjuryStatus]) -> InjuryStatus:
    if raw is None:
        return "healthy"
    return injury_map.get(raw, "day_to_day")


SHORT_TERM_TAGS = ("DTD", "GTD", "Questionable", "Doubtful")


def seed_overrides(
    records: list[PlayerRecord],
    existing: Mapping[int, PlayerOverrides] | None = None,
    injury_map: Mapping[str, InjuryStatus] | None = None,
    now: datetime | None = None,
    ignore_short_term: bool = False,
) -> dict[int, PlayerOverrides]:
    """ignore_short_term: before the regular season, DTD/GTD tags (preseason rest days, minor knocks) seed as
    healthy; Out/IR still count. A 'Rest' tag is never an injury. Sleeper's raw tag and note are kept either way."""
    existing = dict(existing or {})
    injury_map = injury_map or DEFAULT_SLEEPER_INJURY_MAP
    now = now or utcnow()
    result: dict[int, PlayerOverrides] = {}

    for record in records:
        current = existing.get(record.player_id)
        if current is None:
            current = PlayerOverrides(player_id=record.player_id, updated_at=now)
        else:
            current = current.model_copy(deep=True)

        fantasy = record.fantasy
        if fantasy is not None:
            current.eligibility = list(fantasy.fantasy_positions)
            current.eligibility_source = "sleeper" if fantasy.fantasy_positions else "none"
            raw = fantasy.injury_status_raw
            minor = (raw in SHORT_TERM_TAGS and ignore_short_term) or (fantasy.injury_body_part or "").lower() == "rest"
            current.injury_status = "healthy" if minor else map_injury(raw, injury_map)
            current.injury_source = "sleeper"
            note = injury_note_from(fantasy.injury_body_part, fantasy.injury_notes)
            current.injury_note = f"ignored: {raw} {note}".strip() if minor and raw else note
            current.injury_sleeper_raw = fantasy.injury_status_raw
            current.seeded_at = now
            current.updated_at = now
        result[record.player_id] = current

    # Keep overrides for players no longer in the pool (they may come back after a re-pull).
    for player_id, override in existing.items():
        result.setdefault(player_id, override)
    return result
