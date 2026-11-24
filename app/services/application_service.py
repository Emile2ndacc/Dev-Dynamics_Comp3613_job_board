from app.services.states import (
    ApplicationState,
    HiredState,
    RejectedState,
    ReviewedState,
    ShortlistedState,
    SubmittedState,
)
from app.models.application import Application
from sqlmodel import Session
from app.database import engine


class ApplicationService:
    def __init__(self, application: Application):
        self.application = application
        self.state = self._state_for_status(application.status)

    def _state_for_status(self, status: str) -> ApplicationState:
        mapping = {
            "submitted": SubmittedState(),
            "reviewed": ReviewedState(),
            "shortlisted": ShortlistedState(),
            "rejected": RejectedState(),
            "hired": HiredState(),
        }
        return mapping.get(status, SubmittedState())

    def review(self, user):
        self.state.review(self.application, user)
        self._persist()
        self.state = self._state_for_status(self.application.status)

    def shortlist(self, user):
        self.state.shortlist(self.application, user)
        self._persist()
        self.state = self._state_for_status(self.application.status)

    def reject(self, user):
        self.state.reject(self.application, user)
        self._persist()
        self.state = self._state_for_status(self.application.status)

    def hire(self, user):
        self.state.hire(self.application, user)
        self._persist()
        self.state = self._state_for_status(self.application.status)

    def reopen(self, user):
        raise Exception("Cannot reopen a terminal application.")

    def _persist(self):
        with Session(engine) as session:
            self.application = session.merge(self.application)
            session.commit()
            session.refresh(self.application)
