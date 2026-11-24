"""Compatibility adapter for application lifecycle transitions."""

from __future__ import annotations

from typing import Any

from app.services.states import (
    HiredState,
    RejectedState,
    ReviewedState,
    ShortlistedState,
    SubmittedState,
)

ACTIONS = (
    "mark_reviewed",
    "shortlist",
    "reject",
    "hire",
    "reopen",
)

STATE_CLASSES = {
    "submitted": SubmittedState,
    "reviewed": ReviewedState,
    "shortlisted": ShortlistedState,
    "rejected": RejectedState,
    "hired": HiredState,
}


def snapshot(app: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": app["id"],
        "status": app["status"],
        "flag_reviewed": bool(app["flag_reviewed"]),
        "flag_shortlisted": bool(app["flag_shortlisted"]),
        "flag_rejected": bool(app["flag_rejected"]),
        "flag_hired": bool(app["flag_hired"]),
    }


def apply_action(app: dict[str, Any], action: str) -> dict[str, Any]:
    """Dispatch one action through the explicit state implementation."""
    if action not in ACTIONS:
        return {
            "ok": False,
            "error": f"unknown action {action!r}; expected one of {ACTIONS}",
        }

    state_class = STATE_CLASSES.get(app["status"])
    if state_class is None:
        return {"ok": False, "error": f"unknown application status {app['status']!r}"}

    updated = dict(app)
    try:
        state = state_class()
        if action == "mark_reviewed":
            state.mark_reviewed(updated)
        elif action == "shortlist":
            state.shortlist(updated)
        elif action == "reject":
            state.reject(updated)
        elif action == "hire":
            state.hire(updated)
        else:
            state.reopen(updated)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "application": snapshot(updated),
        "row": updated,
        "changed": True,
    }


def derived_status_from_flags(app: dict[str, Any]) -> str:
    """Keep the public view consistent with the canonical status field."""
    return str(app["status"])
