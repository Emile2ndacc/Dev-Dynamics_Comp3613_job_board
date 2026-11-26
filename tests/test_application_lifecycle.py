import pytest

from app.models.application import Application
from app.services.application_service import ApplicationService

APPLICATION_STATES = ("submitted", "reviewed", "shortlisted", "rejected", "hired")
TRANSITION_METHODS = ("review", "shortlist", "reject", "hire", "reopen")
VALID_TRANSITIONS = (
    ("submitted", "review", "reviewed"),
    ("reviewed", "shortlist", "shortlisted"),
    ("shortlisted", "reject", "rejected"),
    ("shortlisted", "hire", "hired"),
)
LEGAL_TRANSITION_PAIRS = {
    (source, action) for source, action, _ in VALID_TRANSITIONS
}
ILLEGAL_TRANSITIONS = tuple(
    (status, action)
    for status in APPLICATION_STATES
    for action in TRANSITION_METHODS
    if (status, action) not in LEGAL_TRANSITION_PAIRS
)
EXPECTED_FLAGS = {
    "submitted": (0, 0, 0, 0),
    "reviewed": (1, 0, 0, 0),
    "shortlisted": (1, 1, 0, 0),
    "rejected": (1, 0, 1, 0),
    "hired": (1, 0, 0, 1),
}
FLAG_FIELDS = (
    "flag_reviewed",
    "flag_shortlisted",
    "flag_rejected",
    "flag_hired",
)


class MockUser:
    def __init__(self, permissions):
        self.permissions = permissions

    def canPerform(self, action, app):
        return action in self.permissions


def make_application(status):
    flags = dict(zip(FLAG_FIELDS, EXPECTED_FLAGS[status]))
    return Application(
        listing_id=1,
        graduate_id=1,
        cover_letter="Cover",
        resume_text="Resume",
        status=status,
        **flags,
    )


def lifecycle_snapshot(application):
    return (
        application.status,
        *(getattr(application, field) for field in FLAG_FIELDS),
    )


@pytest.fixture
def service_for(monkeypatch):
    def create(application):
        service = ApplicationService(application)
        monkeypatch.setattr(service, "_persist", lambda: None)
        return service

    return create


@pytest.mark.parametrize(
    ("initial_status", "action", "expected_status"),
    VALID_TRANSITIONS,
)
def test_legal_transition_updates_status_and_flags(
    service_for, initial_status, action, expected_status
):
    application = make_application(initial_status)
    service = service_for(application)

    getattr(service, action)(MockUser([action]))

    assert lifecycle_snapshot(application) == (
        expected_status,
        *EXPECTED_FLAGS[expected_status],
    )


@pytest.mark.parametrize(
    ("status", "action"),
    ILLEGAL_TRANSITIONS,
)
def test_illegal_transition_leaves_status_and_flags_unchanged(
    service_for, status, action
):
    application = make_application(status)
    service = service_for(application)
    before = lifecycle_snapshot(application)

    with pytest.raises(Exception):  # noqa: B017 - invalid transitions raise base Exception
        getattr(service, action)(MockUser(TRANSITION_METHODS))

    assert lifecycle_snapshot(application) == before


def test_unauthorized_transition_leaves_status_and_flags_unchanged(service_for):
    application = make_application("submitted")
    service = service_for(application)
    before = lifecycle_snapshot(application)

    with pytest.raises(PermissionError):
        service.review(MockUser([]))

    assert lifecycle_snapshot(application) == before
