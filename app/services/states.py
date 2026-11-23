"""State pattern classes for application lifecycle transitions."""

from __future__ import annotations

from typing import Any


def set_status(app: Any, status: str) -> None:
    if isinstance(app, dict):
        app["status"] = status
    else:
        app.status = status


def set_flags(
    app: Any,
    *,
    reviewed: int = 0,
    shortlisted: int = 0,
    rejected: int = 0,
    hired: int = 0,
) -> None:
    values = {
        "flag_reviewed": reviewed,
        "flag_shortlisted": shortlisted,
        "flag_rejected": rejected,
        "flag_hired": hired,
    }
    for name, value in values.items():
        if isinstance(app, dict):
            app[name] = value
        elif hasattr(app, name):
            setattr(app, name, value)


def can_perform(user: Any, action: str, app: Any) -> bool:
    if user is None:
        return True
    if hasattr(user, "canPerform"):
        return bool(user.canPerform(action, app))
    if isinstance(user, dict):
        return user.get("role") == "employer"
    return False


def permission_error(action: str) -> PermissionError:
    return PermissionError(f"You are not authorized to {action} this application.")


class ApplicationState:
    """Base class for application lifecycle states."""

    name = ""

    def review(self, app: Any, user: Any = None) -> Any:
        raise Exception(f"Cannot review an application in {self.name} status.")

    def shortlist(self, app: Any, user: Any = None) -> Any:
        raise Exception(f"Cannot shortlist an application in {self.name} status.")

    def reject(self, app: Any, user: Any = None) -> Any:
        raise Exception(f"Cannot reject an application in {self.name} status.")

    def hire(self, app: Any, user: Any = None) -> Any:
        raise Exception(f"Cannot hire an application in {self.name} status.")

    def reopen(self, app: Any, user: Any = None) -> Any:
        raise Exception(f"Cannot reopen an application in {self.name} status.")

    def mark_reviewed(self, app: Any, user: Any = None) -> Any:
        return self.review(app, user)


class SubmittedState(ApplicationState):
    name = "submitted"

    def review(self, app: Any, user: Any = None) -> Any:
        if not can_perform(user, "review", app):
            raise permission_error("review")
        set_status(app, "reviewed")
        set_flags(app, reviewed=1)
        return app


class ReviewedState(ApplicationState):
    name = "reviewed"

    def review(self, app: Any, user: Any = None) -> Any:
        raise Exception("Application already reviewed.")

    def shortlist(self, app: Any, user: Any = None) -> Any:
        if not can_perform(user, "shortlist", app):
            raise permission_error("shortlist")
        set_status(app, "shortlisted")
        set_flags(app, reviewed=1, shortlisted=1)
        return app


class ShortlistedState(ApplicationState):
    name = "shortlisted"

    def shortlist(self, app: Any, user: Any = None) -> Any:
        raise Exception("Application already shortlisted.")

    def reject(self, app: Any, user: Any = None) -> Any:
        if not can_perform(user, "reject", app):
            raise permission_error("reject")
        set_status(app, "rejected")
        set_flags(app, reviewed=1, rejected=1)
        return app

    def hire(self, app: Any, user: Any = None) -> Any:
        if not can_perform(user, "hire", app):
            raise permission_error("hire")
        set_status(app, "hired")
        set_flags(app, reviewed=1, hired=1)
        return app


class RejectedState(ApplicationState):
    name = "rejected"


class HiredState(ApplicationState):
    name = "hired"
