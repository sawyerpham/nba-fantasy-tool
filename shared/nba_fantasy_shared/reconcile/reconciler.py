"""Five-stage identity reconciliation between the nba_api pool and Sleeper's player file.

Stage 0  drop Sleeper placeholders (DEF, DUP, 'duplicate player') — done by the provider
Stage 1  (normalized name, team) equal in both                         -> name_team
Stage 2  normalized name unique across the whole Sleeper file          -> name_only (+ team conflict / unsigned flag)
Stage 3  several candidates -> birthdate tiebreak (nba birthdate fetched on demand) -> birthdate
Stage 4  Sleeper-rostered players absent from the nba pool -> nba_api static list -> static_list
Stage 5  still unmatched -> nba_only (no eligibility seed) / sleeper_only (synthetic id, no stats)

Nothing is dropped silently: every non-stage-1 outcome lands in the ReconcileReport.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ..models.players import (
    FantasyAttributes,
    MatchMethod,
    PlayerBio,
    PlayerRecord,
    PlayerRef,
    ReconcileReport,
)
from ..providers.base import utcnow
from .names import normalize_name

BirthdateLookup = Callable[[int], date | None]


@dataclass
class ReconcileInputs:
    roster_season: str
    nba_pool: list[PlayerBio]
    sleeper_all: list[PlayerBio]  # every non-placeholder Sleeper entry, rostered or not
    fantasy: dict[str, FantasyAttributes] = field(default_factory=dict)
    nba_static: list[PlayerRef] = field(default_factory=list)


def sleeper_is_rostered(bio: PlayerBio) -> bool:
    return bool(bio.is_active) and bool(bio.team_abbr)


def synthetic_player_id(sleeper_id: str) -> int:
    """Sleeper ids are numeric strings; negative ids can never collide with NBA.com ids."""
    if sleeper_id.isdigit():
        return -int(sleeper_id)
    return -abs(hash(sleeper_id)) % 1_000_000_000 - 1_000_000_000


def merge_bio(nba: PlayerBio | None, sleeper: PlayerBio | None) -> PlayerBio:
    """nba_api bio with Sleeper fill-ins; Sleeper's current age wins when both exist."""
    if nba is None and sleeper is None:
        raise ValueError("merge_bio needs at least one bio")
    if nba is None:
        return sleeper.model_copy()  # type: ignore[union-attr]
    merged = nba.model_copy()
    if sleeper is not None:
        if merged.birthdate is None:
            merged.birthdate = sleeper.birthdate
        if sleeper.age is not None:
            merged.age = sleeper.age
        for attr in ("height_in", "weight_lbs", "years_exp", "college", "country"):
            if getattr(merged, attr) is None and getattr(sleeper, attr) is not None:
                setattr(merged, attr, getattr(sleeper, attr))
    return merged


def _brief(bio: PlayerBio) -> dict:
    return {
        "source_id": bio.source_id,
        "name": bio.full_name,
        "team": bio.team_abbr,
        "status": bio.roster_status,
        "birthdate": bio.birthdate.isoformat() if bio.birthdate else None,
    }


class _Reconciler:
    def __init__(self, inputs: ReconcileInputs, birthdate_lookup: BirthdateLookup | None) -> None:
        self.inputs = inputs
        self.lookup = birthdate_lookup
        self.records: list[PlayerRecord] = []
        self.used_sleeper: set[str] = set()
        self.used_player_ids: set[int] = set()
        self.counts: dict[str, int] = defaultdict(int)
        self.team_conflicts: list[dict] = []
        self.unsigned: list[dict] = []
        self.collisions: list[dict] = []
        self.unmatched_nba: list[dict] = []
        self.unmatched_sleeper: list[dict] = []
        self._nba_birthdates: dict[int, date | None] = {}

        self.sleeper_rostered = [b for b in inputs.sleeper_all if sleeper_is_rostered(b)]
        self.by_name_team: dict[tuple[str, str], list[PlayerBio]] = defaultdict(list)
        for b in self.sleeper_rostered:
            self.by_name_team[(b.normalized_name, b.team_abbr or "")].append(b)
        self.by_name_all: dict[str, list[PlayerBio]] = defaultdict(list)
        for b in inputs.sleeper_all:
            self.by_name_all[b.normalized_name].append(b)
        self.static_by_name: dict[str, list[PlayerRef]] = defaultdict(list)
        for ref in inputs.nba_static:
            self.static_by_name[normalize_name(ref.full_name)].append(ref)

    # ---- helpers --------------------------------------------------------------------------

    def _nba_birthdate(self, player_id: int) -> date | None:
        if player_id not in self._nba_birthdates:
            self._nba_birthdates[player_id] = self.lookup(player_id) if self.lookup else None
        return self._nba_birthdates[player_id]

    def _pick_by_birthdate(self, target: date | None, candidates: list[PlayerBio]) -> PlayerBio | None:
        if target is None:
            return None
        hits = [c for c in candidates if c.birthdate == target]
        return hits[0] if len(hits) == 1 else None

    def _add(self, nba: PlayerBio | None, sleeper: PlayerBio | None, method: MatchMethod, player_id: int) -> PlayerRecord:
        primary = nba or sleeper
        assert primary is not None
        team_conflict = None
        unsigned = False
        team = primary.team_abbr
        if nba is not None and sleeper is not None:
            if sleeper.team_abbr and nba.team_abbr and sleeper.team_abbr != nba.team_abbr:
                team_conflict = {"nba_api": nba.team_abbr, "sleeper": sleeper.team_abbr}
                team = sleeper.team_abbr  # Decision 8: Sleeper wins
            elif sleeper.team_abbr:
                team = sleeper.team_abbr
            elif nba.team_abbr:
                unsigned = True  # Sleeper says FA/RET; NBA.com still lists a team
                team = nba.team_abbr
        record = PlayerRecord(
            player_id=player_id,
            sleeper_id=sleeper.source_id if sleeper else None,
            full_name=primary.full_name,
            first_name=primary.first_name,
            last_name=primary.last_name,
            normalized_name=primary.normalized_name,
            team_abbr=team,
            team_conflict=team_conflict,
            unsigned_per_sleeper=unsigned,
            sleeper_status=sleeper.roster_status if sleeper else None,
            bio=merge_bio(nba, sleeper),
            fantasy=self.inputs.fantasy.get(sleeper.source_id) if sleeper else None,
            match_method=method,
            has_stats=player_id > 0,
        )
        self.records.append(record)
        self.counts[method] += 1
        self.used_player_ids.add(player_id)
        if sleeper is not None:
            self.used_sleeper.add(sleeper.source_id)
        if team_conflict:
            self.team_conflicts.append({"player_id": player_id, "name": record.full_name, **team_conflict})
        if unsigned:
            self.unsigned.append(
                {"player_id": player_id, "name": record.full_name, "nba_team": nba.team_abbr if nba else None,
                 "sleeper_status": sleeper.roster_status if sleeper else None}
            )
        return record

    def _available(self, candidates: list[PlayerBio]) -> list[PlayerBio]:
        return [c for c in candidates if c.source_id not in self.used_sleeper]

    # ---- stages ----------------------------------------------------------------------------

    def run_nba_side(self) -> None:
        for nba in self.inputs.nba_pool:
            player_id = int(nba.source_id)
            if player_id in self.used_player_ids:
                continue
            # Stage 1: name + team among rostered Sleeper players
            cands = self._available(self.by_name_team.get((nba.normalized_name, nba.team_abbr or ""), []))
            if len(cands) == 1:
                self._add(nba, cands[0], "name_team", player_id)
                continue
            if len(cands) > 1:
                if self._resolve_collision(nba, player_id, cands, stage="name_team"):
                    continue
                self._unmatched_nba(nba, player_id, "collision_unresolved")
                continue
            # Stage 2: name only across the whole Sleeper file
            cands = self._available(self.by_name_all.get(nba.normalized_name, []))
            if len(cands) == 1:
                self._add(nba, cands[0], "name_only", player_id)
                continue
            if len(cands) > 1:
                if self._resolve_collision(nba, player_id, cands, stage="name_only"):
                    continue
                self._unmatched_nba(nba, player_id, "collision_unresolved")
                continue
            self._unmatched_nba(nba, player_id, "no_sleeper_name_match")

    def _resolve_collision(self, nba: PlayerBio, player_id: int, cands: list[PlayerBio], stage: str) -> bool:
        target = nba.birthdate or self._nba_birthdate(player_id)
        chosen = self._pick_by_birthdate(target, cands)
        entry = {
            "name": nba.full_name,
            "player_id": player_id,
            "stage": stage,
            "nba_birthdate": target.isoformat() if target else None,
            "candidates": [_brief(c) for c in cands],
            "resolved": chosen is not None,
        }
        self.collisions.append(entry)
        if chosen is None:
            return False
        self._add(nba, chosen, "birthdate", player_id)
        return True

    def _unmatched_nba(self, nba: PlayerBio, player_id: int, reason: str) -> None:
        self._add(nba, None, "nba_only", player_id)
        self.unmatched_nba.append({"player_id": player_id, "name": nba.full_name, "team": nba.team_abbr, "reason": reason})

    def run_sleeper_side(self) -> None:
        for sl in self.sleeper_rostered:
            if sl.source_id in self.used_sleeper:
                continue
            # Stage 4: nba_api static list by normalized name
            refs = [r for r in self.static_by_name.get(sl.normalized_name, []) if r.player_id not in self.used_player_ids]
            if len(refs) == 1:
                self._add(None, sl, "static_list", refs[0].player_id)
                continue
            if len(refs) > 1:
                chosen = self._pick_static_by_birthdate(sl, refs)
                if chosen is not None:
                    self._add(None, sl, "static_list", chosen.player_id)
                    continue
                self._unmatched_sleeper(sl, "static_collision_unresolved")
                continue
            self._unmatched_sleeper(sl, "not_in_nba_static_list")

    def _pick_static_by_birthdate(self, sl: PlayerBio, refs: list[PlayerRef]) -> PlayerRef | None:
        hits: list[PlayerRef] = []
        if sl.birthdate is not None and self.lookup is not None:
            for ref in refs:
                if self._nba_birthdate(ref.player_id) == sl.birthdate:
                    hits.append(ref)
        self.collisions.append(
            {
                "name": sl.full_name,
                "sleeper_id": sl.source_id,
                "stage": "static_list",
                "sleeper_birthdate": sl.birthdate.isoformat() if sl.birthdate else None,
                "candidates": [{"player_id": r.player_id, "name": r.full_name, "is_active": r.is_active} for r in refs],
                "resolved": len(hits) == 1,
            }
        )
        return hits[0] if len(hits) == 1 else None

    def _unmatched_sleeper(self, sl: PlayerBio, reason: str) -> None:
        self._add(None, sl, "sleeper_only", synthetic_player_id(sl.source_id))
        self.unmatched_sleeper.append(
            {"sleeper_id": sl.source_id, "name": sl.full_name, "team": sl.team_abbr, "status": sl.roster_status, "reason": reason}
        )

    def report(self) -> ReconcileReport:
        return ReconcileReport(
            run_at=utcnow(),
            roster_season=self.inputs.roster_season,
            nba_pool_size=len(self.inputs.nba_pool),
            sleeper_all_size=len(self.inputs.sleeper_all),
            sleeper_rostered_size=len(self.sleeper_rostered),
            counts=dict(self.counts),
            team_conflicts=self.team_conflicts,
            unsigned_per_sleeper=self.unsigned,
            collisions=self.collisions,
            unmatched_nba=self.unmatched_nba,
            unmatched_sleeper=self.unmatched_sleeper,
        )


def reconcile(
    inputs: ReconcileInputs, birthdate_lookup: BirthdateLookup | None = None
) -> tuple[list[PlayerRecord], ReconcileReport]:
    engine = _Reconciler(inputs, birthdate_lookup)
    engine.run_nba_side()
    engine.run_sleeper_side()
    records = sorted(engine.records, key=lambda r: (r.last_name.lower(), r.first_name.lower(), r.player_id))
    return records, engine.report()
