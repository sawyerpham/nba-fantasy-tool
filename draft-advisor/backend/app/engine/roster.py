"""Roster slots, eligibility, slot assignment, and same-NBA-team stacking.

Slots are tracked by type and count (PG×1 ... UTIL×2, BN×8, IR×2). A pick occupies one slot of a
type. IR is never drafted into. Assignment is greedy most-specific-first (position slot, then G/F if
the league has them, then UTIL, then BN); the user may reassign a pick's slot afterwards.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings
from nba_fantasy_shared.models.players import SLOT_ACCEPTS, PlayerRecord

POSITION_SLOTS: tuple[str, ...] = ("PG", "SG", "SF", "PF", "C")
FLEX_SLOTS: tuple[str, ...] = ("G", "F")
GENERIC_SLOTS: tuple[str, ...] = ("UTIL", "BN")
DRAFTABLE_SLOTS: tuple[str, ...] = POSITION_SLOTS + FLEX_SLOTS + GENERIC_SLOTS  # IR excluded


def slot_capacity(league: LeagueSettings) -> dict[str, int]:
    caps: Counter[str] = Counter()
    for spec in league.roster_slots:
        caps[spec.slot] += spec.count
    return dict(caps)


def used_slots(picks: Iterable[Pick]) -> Counter[str]:
    return Counter(p.slot for p in picks)


def open_slots(league: LeagueSettings, picks: Iterable[Pick]) -> dict[str, int]:
    """Open count per slot type, including IR (for display); never negative."""
    used = used_slots(picks)
    return {slot: max(0, cap - used.get(slot, 0)) for slot, cap in slot_capacity(league).items()}


def open_mandatory_count(league: LeagueSettings, picks: Iterable[Pick]) -> int:
    return sum(n for slot, n in open_slots(league, picks).items() if slot != "IR")


def slot_accepts(slot: str, eligibility: Iterable[str]) -> bool:
    accepted = SLOT_ACCEPTS.get(slot)
    if accepted is None:
        return False
    if slot in GENERIC_SLOTS:
        return True  # UTIL/BN take anyone, even a player whose eligibility is still unset
    return any(pos in accepted for pos in eligibility)


def candidate_slots(eligibility: Iterable[str]) -> list[str]:
    """Slot types a player may fill, most specific first."""
    elig = list(eligibility)
    ordered = [slot for slot in POSITION_SLOTS if slot in elig]
    ordered += [slot for slot in FLEX_SLOTS if slot_accepts(slot, elig)]
    ordered += list(GENERIC_SLOTS)
    return ordered


def assign_slot(league: LeagueSettings, picks: Iterable[Pick], eligibility: Iterable[str]) -> str | None:
    """Most specific open, draftable slot the player can fill; None when nothing fits."""
    open_by_type = open_slots(league, picks)
    for slot in candidate_slots(eligibility):
        if open_by_type.get(slot, 0) > 0:
            return slot
    return None


def make_room(league: LeagueSettings, picks: list[Pick], eligibility: Iterable[str], eligibility_of) -> tuple[str, list[tuple[Pick, str]]] | None:
    """When nothing fits the new player: a chain of moves that frees a slot for him, e.g. an SG/SF in SG slides to the
    open SF so a PG/SG can take SG; or a PF/C slides to the open C, a bench SF/PF moves up to that PF, and the
    newcomer takes the bench spot. Returns (his slot, [(pick, its new slot), ...]) or None when no chain exists.
    The newcomer tries the bench first, so nobody already rostered loses a starting spot to make room."""
    opens = open_slots(league, picks)
    seen: set[str] = set()

    def path(slots: list[str]) -> list | None:   # [slot, occupant, slot, occupant, ..., open slot]
        for slot in slots:
            if slot == "IR" or slot in seen:
                continue
            seen.add(slot)
            if opens.get(slot, 0) > 0:
                return [slot]
            for p in picks:
                if p.slot == slot:
                    tail = path(candidate_slots(eligibility_of(p.player_id)))
                    if tail is not None:
                        return [slot, p, *tail]
        return None

    own = candidate_slots(eligibility)
    chain = path(sorted(own, key=lambda s: s != "BN"))
    if chain is None:
        return None
    return chain[0], [(chain[i], chain[i + 1]) for i in range(1, len(chain), 2)]


def is_rosterable(league: LeagueSettings, picks: Iterable[Pick], eligibility: Iterable[str]) -> bool:
    return assign_slot(league, picks, eligibility) is not None


def validate_slot(league: LeagueSettings, picks: Iterable[Pick], eligibility: Iterable[str], slot: str) -> str | None:
    """Error message when an explicitly requested slot is not usable, else None."""
    if slot == "IR" or slot not in DRAFTABLE_SLOTS:
        return f"slot {slot} cannot be drafted into"
    if slot not in slot_capacity(league):
        return f"league has no {slot} slot"
    if open_slots(league, picks).get(slot, 0) <= 0:
        return f"no open {slot} slot"
    if not slot_accepts(slot, eligibility):
        return f"player is not eligible for {slot} (eligibility: {', '.join(eligibility) or 'none'})"
    return None


# ----------------------------------------------------------------------------- stacking


def team_stack(players: Mapping[int, PlayerRecord], picks: Iterable[Pick]) -> Counter[str]:
    """Count of rostered players per NBA team for one manager's picks."""
    counts: Counter[str] = Counter()
    for pick in picks:
        rec = players.get(pick.player_id)
        if rec is not None and rec.team_abbr:
            counts[rec.team_abbr] += 1
    return counts


def stack_if_added(stack: Mapping[str, int], team_abbr: str | None) -> int:
    if not team_abbr:
        return 0
    return stack.get(team_abbr, 0) + 1
