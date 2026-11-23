import pytest

from app.models.application import Application
from app.services.application_service import ApplicationService


class MockUser:
    def __init__(self, permissions):
        self.permissions = permissions

    def canPerform(self, action, app):
        return action in self.permissions


def make_application(status):
    return Application(
        listing_id=1,
        graduate_id=1,
        cover_letter="Cover",
        resume_text="Resume",
        status=status,
    )


@pytest.fixture
def new_application():
    application = make_application("submitted")
    service = ApplicationService(application)
    service._persist = lambda: None
    return application, service


def test_review_valid_transition(new_application):
    application, service = new_application

    service.review(MockUser(["review"]))

    assert application.status == "reviewed"
    assert application.flag_reviewed == 1


def test_review_unauthorized(new_application):
    application, service = new_application

    with pytest.raises(PermissionError):
        service.review(MockUser([]))


def test_shortlist_valid_transition():
    application = make_application("reviewed")
    application.flag_reviewed = 1
    service = ApplicationService(application)
    service._persist = lambda: None

    service.shortlist(MockUser(["shortlist"]))

    assert application.status == "shortlisted"
    assert application.flag_reviewed == 1
    assert application.flag_shortlisted == 1


def test_shortlist_invalid_from_submitted():
    application, service = make_application("submitted"), None
    service = ApplicationService(application)
    service._persist = lambda: None

    with pytest.raises(Exception):
        service.shortlist(MockUser(["shortlist"]))


def test_reject_valid_from_shortlisted():
    application = make_application("shortlisted")
    application.flag_reviewed = 1
    application.flag_shortlisted = 1
    service = ApplicationService(application)
    service._persist = lambda: None

    service.reject(MockUser(["reject"]))

    assert application.status == "rejected"
    assert application.flag_rejected == 1
    assert application.flag_reviewed == 1
    assert application.flag_shortlisted == 0
    assert application.flag_hired == 0


@pytest.mark.parametrize("status", ["submitted", "reviewed"])
def test_reject_invalid_before_shortlisting(status):
    application = make_application(status)
    if status == "reviewed":
        application.flag_reviewed = 1
    service = ApplicationService(application)
    service._persist = lambda: None

    with pytest.raises(Exception):
        service.reject(MockUser(["reject"]))


def test_hire_invalid_from_submitted():
    application = make_application("submitted")
    service = ApplicationService(application)
    service._persist = lambda: None

    with pytest.raises(Exception):
        service.hire(MockUser(["hire"]))


def test_hire_valid_from_shortlisted():
    application = make_application("shortlisted")
    application.flag_reviewed = 1
    application.flag_shortlisted = 1
    service = ApplicationService(application)
    service._persist = lambda: None

    service.hire(MockUser(["hire"]))

    assert application.status == "hired"
    assert application.flag_hired == 1
    assert application.flag_rejected == 0


@pytest.mark.parametrize("status", ["rejected", "hired"])
def test_terminal_states_cannot_be_reopened(status):
    application = make_application(status)
    service = ApplicationService(application)
    service._persist = lambda: None

    with pytest.raises(Exception):
        service.reopen(MockUser(["reopen"]))
