from __future__ import annotations

from fastapi import Request

from ..services.app_state import AppState


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "app_state", None)
    if state is None:
        raise RuntimeError("AppState not initialised")
    return state
