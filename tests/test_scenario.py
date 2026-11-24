"""Shallow scenario smoke tests — intentionally weak."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.seed import seed
from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.models.user import User


def setup_module() -> None:
    seed(reset=True)


client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["scenario"] == "job-board"


def test_api_login_seed_admin():
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-dev"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"


def test_jobs_endpoint_returns_list():
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json()["jobs"], list)
    assert len(r.json()["jobs"]) >= 1


def login_user(email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": (
                "admin-dev"
                if email == "admin@example.com"
                else "employer-dev"
                if email.startswith("employer")
                else "grad-dev"
            ),
        },
    )
    assert response.status_code == 200
    return response.json()["user"]


def get_seeded_application() -> Application:
    with Session(engine) as session:
        application = session.exec(select(Application)).first()
        if application is not None:
            return application

        graduate = session.exec(
            select(User).where(User.email == "grad.dcit@example.com")
        ).one()
        listing = session.exec(
            select(Listing).where(Listing.status == "published")
        ).first()
        application = Application(
            listing_id=listing.id,
            graduate_id=graduate.id,
            cover_letter="Integration test cover letter",
            resume_text="Integration test resume",
            status="submitted",
            flag_reviewed=0,
            flag_shortlisted=0,
            flag_rejected=0,
            flag_hired=0,
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return application


def reset_application(application_id: int, status: str = "submitted") -> None:
    with Session(engine) as session:
        application = session.get(Application, application_id)
        application.status = status
        application.flag_reviewed = int(
            status in {"reviewed", "shortlisted", "rejected", "hired"}
        )
        application.flag_shortlisted = int(status == "shortlisted")
        application.flag_rejected = int(status == "rejected")
        application.flag_hired = int(status == "hired")
        session.add(application)
        session.commit()


def test_owner_can_run_full_application_lifecycle():
    application = get_seeded_application()
    reset_application(application.id)
    employer = login_user("employer@example.com")

    reviewed = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "mark_reviewed"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["application"]["status"] == "reviewed"

    shortlisted = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "shortlist"},
    )
    assert shortlisted.status_code == 200
    assert shortlisted.json()["application"]["status"] == "shortlisted"

    hired = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "hire"},
    )
    assert hired.status_code == 200
    assert hired.json()["application"]["status"] == "hired"


def test_another_employer_cannot_transition_application():
    application = get_seeded_application()
    reset_application(application.id)
    employer2 = login_user("employer2@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer2["id"], "action": "mark_reviewed"},
    )

    assert response.status_code == 400
    assert "listing employer" in response.json()["detail"]


def test_admin_cannot_transition_application():
    application = get_seeded_application()
    reset_application(application.id)
    admin = login_user("admin@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": admin["id"], "action": "mark_reviewed"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "forbidden"


def test_invalid_jump_is_rejected():
    application = get_seeded_application()
    reset_application(application.id)
    employer = login_user("employer@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "hire"},
    )

    assert response.status_code == 400
    assert "Cannot hire" in response.json()["detail"]


def test_rejection_is_rejected_before_shortlisting():
    application = get_seeded_application()
    reset_application(application.id)
    employer = login_user("employer@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "reject"},
    )

    assert response.status_code == 400
    assert "Cannot reject" in response.json()["detail"]


def test_owner_can_reject_shortlisted_application():
    application = get_seeded_application()
    reset_application(application.id, status="shortlisted")
    employer = login_user("employer@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "reject"},
    )

    assert response.status_code == 200
    assert response.json()["application"]["status"] == "rejected"
    assert response.json()["application"]["flag_rejected"] == 1
    assert response.json()["application"]["flag_shortlisted"] == 0


def test_hired_application_is_terminal():
    application = get_seeded_application()
    reset_application(application.id, status="hired")
    employer = login_user("employer@example.com")

    response = client.post(
        f"/api/applications/{application.id}/transition",
        json={"actor_id": employer["id"], "action": "reopen"},
    )

    assert response.status_code == 400


def test_non_dcit_graduate_cannot_apply():
    graduate = login_user("grad.other@example.com")

    with Session(engine) as session:
        listing_row = session.exec(
            select(Listing).where(Listing.status == "published")
        ).first()

    response = client.post(
        "/api/graduates/applications",
        json={
            "actor_id": graduate["id"],
            "listing_id": listing_row.id,
            "cover_letter": "Cover letter",
            "resume_text": "Resume",
        },
    )

    assert response.status_code == 400
    assert "DCIT" in response.json()["detail"]


def test_external_listing_cannot_collect_on_platform_application():
    graduate = login_user("grad.dcit@example.com")

    with Session(engine) as session:
        employer = session.exec(
            select(User).where(User.email == "employer@example.com")
        ).one()
        listing = Listing(
            employer_id=employer.id,
            title="External Test Role",
            company="External Co",
            description="Apply externally",
            apply_mode="external",
            external_url="https://example.com/jobs/1",
            deadline="2099-12-31",
            status="published",
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)
        listing_id = listing.id

    response = client.post(
        "/api/graduates/applications",
        json={
            "actor_id": graduate["id"],
            "listing_id": listing_id,
            "cover_letter": "Cover letter",
            "resume_text": "Resume",
        },
    )

    assert response.status_code == 400
    assert "external" in response.json()["detail"].lower()


def test_other_employer_cannot_view_listing_applicants():
    application = get_seeded_application()
    employer2 = login_user("employer2@example.com")

    with Session(engine) as session:
        listing = session.get(Listing, application.listing_id)
        listing_id = listing.id

    response = client.get(
        f"/api/listings/{listing_id}/applicants",
        params={"actor_id": employer2["id"]},
    )

    assert response.status_code == 403
    assert "listing employer" in response.json()["detail"]
