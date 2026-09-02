"""Flat-file JSON store with atomic writes and cache-age queries."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class JsonStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return self.path(rel).is_file()

    def modified_at(self, rel: str) -> datetime | None:
        p = self.path(rel)
        if not p.is_file():
            return None
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

    def age(self, rel: str, now: datetime | None = None) -> timedelta | None:
        modified = self.modified_at(rel)
        if modified is None:
            return None
        return (now or datetime.now(timezone.utc)) - modified

    def read_json(self, rel: str) -> Any:
        with self.path(rel).open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def write_json(self, rel: str, data: Any, indent: int | None = 2) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=indent)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def read_model(self, rel: str, model_cls: type[M]) -> M:
        return model_cls.model_validate(self.read_json(rel))

    def read_model_or_none(self, rel: str, model_cls: type[M]) -> M | None:
        if not self.exists(rel):
            return None
        return self.read_model(rel, model_cls)

    def write_model(self, rel: str, model: BaseModel, indent: int | None = 2) -> Path:
        return self.write_json(rel, model.model_dump(mode="json"), indent=indent)

    def read_models(self, rel: str, model_cls: type[M]) -> list[M]:
        return [model_cls.model_validate(item) for item in self.read_json(rel)]

    def write_models(self, rel: str, models: list[BaseModel], indent: int | None = None) -> Path:
        return self.write_json(rel, [m.model_dump(mode="json") for m in models], indent=indent)
