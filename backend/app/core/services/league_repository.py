"""Persistence of league documents (DESIGN.md 1.8): `leagues/{league_id}.json` IS the export document."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from nba_fantasy_shared.models.draft import DraftState
from nba_fantasy_shared.models.export import DraftExport, KeeperBlock
from nba_fantasy_shared.models.league import LeagueSettings, Manager
from nba_fantasy_shared.storage import JsonStore

from ... import config

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class LeagueNotFound(KeyError):
    """Raised when a league document doesn't exist."""
    pass


def validate_league_id(league_id: str) -> str:
    """Validate a league id (letters, digits, '_', '-', '.', at most 64 chars) so it is safe as a file name."""
    if not _SAFE_ID.match(league_id):
        raise ValueError("league_id may only contain letters, digits, '_', '-' and '.' (max 64 chars)")
    return league_id


def default_managers(count: int, budget: int) -> list[Manager]:
    """Default managers m1..m{count} with the same budget; m1 is you."""
    return [
        Manager(manager_id=f"m{i}", name=f"Manager {i}", is_user=(i == 1), budget_total=budget)
        for i in range(1, count + 1)
    ]


def new_document(league: LeagueSettings, managers: list[Manager] | None = None) -> DraftExport:
    """A fresh league document: no picks, nomination order following the managers."""
    managers = managers or default_managers(league.num_managers, league.budget_per_manager)
    return DraftExport(
        generated_at=datetime.now(timezone.utc),
        league=league,
        managers=managers,
        draft=DraftState(nomination_order=[m.manager_id for m in managers]),
        keepers=KeeperBlock(),
        players={},
    )


class LeagueRepository:
    """Reads and writes league documents (leagues/{id}.json) through the JSON store."""
    def __init__(self, store: JsonStore) -> None:
        """Use the given store."""
        self.store = store

    def list_ids(self) -> list[str]:
        """Ids of every league on disk, sorted."""
        folder = self.store.path("leagues")
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.json"))

    def exists(self, league_id: str) -> bool:
        """Whether the league's document exists."""
        return self.store.exists(config.league_rel(league_id))

    def load(self, league_id: str) -> DraftExport:
        """Load a league document (LeagueNotFound when missing)."""
        rel = config.league_rel(league_id)
        if not self.store.exists(rel):
            raise LeagueNotFound(league_id)
        return self.store.read_model(rel, DraftExport)

    def save(self, doc: DraftExport) -> None:
        """Save a document, stamping its generation time."""
        doc.generated_at = datetime.now(timezone.utc)
        self.store.write_model(config.league_rel(doc.league.league_id), doc)

    def delete(self, league_id: str) -> None:
        """Delete a league's document if it exists."""
        path = self.store.path(config.league_rel(league_id))
        if path.is_file():
            path.unlink()

    def export_copy(self, doc: DraftExport) -> str:
        """Write a timestamped copy under exports/ and return its relative path."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rel = f"exports/{doc.league.league_id}_{stamp}.json"
        self.store.write_model(rel, doc)
        return rel

    def summaries(self) -> list[dict]:
        """One summary per league (id, name, status); a corrupt file is listed as unreadable instead of hiding the others."""
        out = []
        for league_id in self.list_ids():
            try:
                doc = self.load(league_id)
            except Exception:  # noqa: BLE001 - a corrupt file must not hide the others
                out.append({"league_id": league_id, "name": None, "status": "unreadable"})
                continue
            out.append({
                "league_id": league_id,
                "name": doc.league.name,
                "status": doc.draft.status,
                "managers": len(doc.managers),
                "picks": len(doc.draft.picks),
                "roster_season": doc.league.roster_season,
                "updated_at": doc.generated_at.isoformat(),
            })
        return out
