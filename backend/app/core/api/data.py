"""Data pull (background thread with progress polling) and cache status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..services.app_state import AppState, PullAlreadyRunning
from .deps import get_state
from .schemas import PullRequest

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/pull", status_code=status.HTTP_202_ACCEPTED)
def start_pull(body: PullRequest, state: AppState = Depends(get_state)) -> dict:
    try:
        return state.start_pull(sources=body.sources, force_sleeper=body.force_sleeper, skip_game_logs=body.skip_game_logs)
    except PullAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/pull/status")
def pull_status(state: AppState = Depends(get_state)) -> dict:
    return state.pull_status()


@router.get("/status")
def data_status(state: AppState = Depends(get_state)) -> dict:
    return state.data_status()
