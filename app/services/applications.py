"""Application create / read / status transitions via lifecycle tracker."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.services.application_service import ApplicationService
from app.services.board_auth import get_user
from app.services.lifecycle import ACTIONS


def apply(
    graduate_id: int,
    listing_id: int,
    cover_letter: str,
    resume_text: str | None = None,
) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only"}
    if user.get("programme") not in {"DCIT"}:
        return {"ok": False, "error": "DCIT graduates only"}

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if listing.status != "published":
            return {"ok": False, "error": "listing is not published"}
        if listing.apply_mode != "collect":
            return {"ok": False, "error": "listing uses an external application link"}
        try:
            if date.fromisoformat(listing.deadline) < date.today():
                return {"ok": False, "error": "listing deadline has passed"}
        except (TypeError, ValueError):
            return {"ok": False, "error": "listing has an invalid deadline"}
        resume = resume_text or user.get("resume_text") or ""
        application = Application(
            listing_id=listing_id,
            graduate_id=graduate_id,
            cover_letter=cover_letter,
            resume_text=resume,
            status="submitted",
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return {
            "ok": True,
            "application_id": application.id,
            "status": "submitted",
        }


def my_applications(graduate_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Application)
            .where(Application.graduate_id == graduate_id)
            .order_by(Application.id)
        ).all()
        results = []
        for row in rows:
            app = row.model_dump()
            view = dict(app)
            # Use canonical status only
            view["status"] = app["status"]
            results.append(view)
        return results


def listing_applicants(viewer_id: int, listing_id: int) -> dict[str, Any]:
    viewer = get_user(viewer_id)
    if not viewer:
        return {"ok": False, "error": "unknown user"}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if viewer["role"] not in {"employer", "admin"}:
            return {"ok": False, "error": "forbidden"}
        if viewer["role"] == "employer" and listing.employer_id != viewer_id:
            return {
                "ok": False,
                "error": "only the listing employer may view applicants",
            }
        rows = session.exec(
            select(Application)
            .where(Application.listing_id == listing_id)
            .order_by(Application.id)
        ).all()
        return {"ok": True, "applicants": [r.model_dump() for r in rows]}


def export_applicants(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only"}
    result = listing_applicants(admin_id, listing_id)
    if not result.get("ok"):
        return result
    return {"ok": True, "format": "json", "package": result["applicants"]}


def transition_application(
    actor_id: int, application_id: int, action: str
) -> dict[str, Any]:
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user"}
    if actor["role"] != "employer":
        return {"ok": False, "error": "forbidden"}
    if action not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {ACTIONS}"}

    with Session(engine) as session:
        app = session.get(Application, application_id)
        if not app:
            return {"ok": False, "error": "application not found"}
        listing = session.get(Listing, app.listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if listing.employer_id != actor_id:
            return {
                "ok": False,
                "error": "only the listing employer may transition applications",
            }

    service = ApplicationService(app)
    try:
        if action == "mark_reviewed":
            service.review(actor)
        elif action == "shortlist":
            service.shortlist(actor)
        elif action == "reject":
            service.reject(actor)
        elif action == "hire":
            service.hire(actor)
        elif action == "reopen":
            service.reopen(actor)

        return {
            "ok": True,
            "application": app.model_dump(),
            "changed": True,
        }
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"invalid action: {str(e)}"}
