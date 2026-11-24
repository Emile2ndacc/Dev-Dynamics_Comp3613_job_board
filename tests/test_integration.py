import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import database
from app.config import get_settings
from app.main import app
from app.models.application import Application
from app.models.listing import Listing
from app.models.user import User
from app.repositories.user import UserRepository
from app.services import application_service, applications, board_auth
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utilities.security import create_access_token, verify_password


@pytest.fixture
def transition_api(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(application_service, "engine", test_engine)
    monkeypatch.setattr(applications, "engine", test_engine)
    monkeypatch.setattr(board_auth, "engine", test_engine)

    def get_test_session():
        with Session(test_engine) as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[database.get_session] = get_test_session
    client = TestClient(app)

    with Session(test_engine) as session:
        users = {
            "owner": User(
                username="owner",
                email="owner@example.com",
                password="unused",
                role="employer",
            ),
            "other_employer": User(
                username="other-employer",
                email="other@example.com",
                password="unused",
                role="employer",
            ),
            "graduate": User(
                username="graduate",
                email="graduate@example.com",
                password="unused",
                role="graduate",
            ),
            "admin": User(
                username="admin",
                email="admin@example.com",
                password="unused",
                role="admin",
            ),
        }
        session.add_all(users.values())
        session.commit()
        for user in users.values():
            session.refresh(user)

        listing = Listing(
            employer_id=users["owner"].id,
            title="Quality Engineer",
            company="Example Co",
            description="Test listing",
            apply_mode="collect",
            deadline="2099-12-31",
            status="published",
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)

        application = Application(
            listing_id=listing.id,
            graduate_id=users["graduate"].id,
            cover_letter="Test application",
            resume_text="Test resume",
            status="submitted",
        )
        session.add(application)
        session.commit()
        session.refresh(application)

        test_data = {
            "listing_id": listing.id,
            "application_id": application.id,
            "users": {name: user.id for name, user in users.items()},
            "engine": test_engine,
        }

    try:
        yield client, test_data
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        SQLModel.metadata.drop_all(test_engine)
        test_engine.dispose()


def _authenticate_as(client: TestClient, user_id: int) -> None:
    client.cookies.set(
        "access_token",
        create_access_token({"sub": str(user_id), "role": "test"}),
    )


def _application_status(engine, application_id: int) -> str:
    with Session(engine) as session:
        application = session.get(Application, application_id)
        assert application is not None
        return application.status


def test_listing_owner_can_transition_and_change_is_persisted(transition_api):
    client, data = transition_api
    _authenticate_as(client, data["users"]["owner"])

    response = client.post(
        f"/api/applications/{data['application_id']}/transition",
        json={"action": "mark_reviewed"},
    )

    assert response.status_code == 200
    assert response.json()["application"]["status"] == "reviewed"
    assert _application_status(data["engine"], data["application_id"]) == "reviewed"


@pytest.mark.parametrize("role", ["other_employer", "graduate", "admin"])
def test_non_owner_or_non_employer_cannot_transition(transition_api, role):
    client, data = transition_api
    _authenticate_as(client, data["users"][role])

    response = client.post(
        f"/api/applications/{data['application_id']}/transition",
        json={
            "action": "mark_reviewed",
            "actor_id": data["users"]["owner"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"
    assert _application_status(data["engine"], data["application_id"]) == "submitted"


def test_unauthenticated_user_cannot_transition(transition_api):
    client, data = transition_api

    response = client.post(
        f"/api/applications/{data['application_id']}/transition",
        json={
            "action": "mark_reviewed",
            "actor_id": data["users"]["owner"],
        },
    )

    assert response.status_code == 401
    assert _application_status(data["engine"], data["application_id"]) == "submitted"


def test_listing_owner_can_access_applicants(transition_api):
    client, data = transition_api
    _authenticate_as(client, data["users"]["owner"])

    response = client.get(
        f"/api/listings/{data['listing_id']}/applicants",
    )

    assert response.status_code == 200
    applicants = response.json()["applicants"]
    assert len(applicants) == 1
    assert applicants[0]["cover_letter"] == "Test application"
    assert applicants[0]["resume_text"] == "Test resume"


@pytest.mark.parametrize("role", ["other_employer", "graduate", "admin"])
def test_non_owner_or_non_employer_cannot_access_applicants(
    transition_api, role
):
    client, data = transition_api
    _authenticate_as(client, data["users"][role])

    response = client.get(
        f"/api/listings/{data['listing_id']}/applicants",
        params={"actor_id": data["users"]["owner"]},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_unauthenticated_user_cannot_access_applicants(transition_api):
    client, data = transition_api

    response = client.get(
        f"/api/listings/{data['listing_id']}/applicants",
        params={"actor_id": data["users"]["owner"]},
    )

    assert response.status_code == 401
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_graduate_can_only_access_their_own_applications(transition_api):
    client, data = transition_api
    graduate_id = data["users"]["graduate"]
    _authenticate_as(client, graduate_id)

    response = client.get(
        "/api/graduates/applications",
        params={"actor_id": data["users"]["admin"]},
    )

    assert response.status_code == 200
    user_applications = response.json()["applications"]
    assert len(user_applications) == 1
    assert user_applications[0]["graduate_id"] == graduate_id
    assert user_applications[0]["resume_text"] == "Test resume"


@pytest.mark.parametrize("role", ["owner", "other_employer", "admin"])
def test_non_graduate_cannot_access_graduate_applications(transition_api, role):
    client, data = transition_api
    _authenticate_as(client, data["users"][role])

    response = client.get(
        "/api/graduates/applications",
        params={"actor_id": data["users"]["graduate"]},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_unauthenticated_user_cannot_access_graduate_applications(transition_api):
    client, data = transition_api

    response = client.get(
        "/api/graduates/applications",
        params={"actor_id": data["users"]["graduate"]},
    )

    assert response.status_code == 401
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_admin_can_export_applicants(transition_api):
    client, data = transition_api
    _authenticate_as(client, data["users"]["admin"])

    response = client.get(
        f"/api/admin/listings/{data['listing_id']}/export",
        params={"actor_id": data["users"]["owner"]},
    )

    assert response.status_code == 200
    package = response.json()["package"]
    assert len(package) == 1
    assert package[0]["resume_text"] == "Test resume"


@pytest.mark.parametrize("role", ["owner", "other_employer", "graduate"])
def test_non_admin_cannot_export_applicants(transition_api, role):
    client, data = transition_api
    _authenticate_as(client, data["users"][role])

    response = client.get(
        f"/api/admin/listings/{data['listing_id']}/export",
        params={"actor_id": data["users"]["admin"]},
    )

    assert response.status_code == 403
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_unauthenticated_user_cannot_export_applicants(transition_api):
    client, data = transition_api

    response = client.get(
        f"/api/admin/listings/{data['listing_id']}/export",
        params={"actor_id": data["users"]["admin"]},
    )

    assert response.status_code == 401
    assert "Test application" not in response.text
    assert "Test resume" not in response.text


def test_save_password(test_session):
    repository = UserRepository(test_session)
    service = AuthService(repository)

    created = service.register_user("alice", "alice@example.com", "secret")
    saved = repository.get_by_username("alice")

    assert saved is not None
    assert created.id == saved.id
    assert saved.username == "alice"
    assert saved.email == "alice@example.com"
    assert saved.role == "regular_user"
    assert saved.password != "secret"
    assert verify_password("secret", saved.password)


def test_login(test_session):
    repository = UserRepository(test_session)
    service = AuthService(repository)
    service.register_user("alice", "alice@example.com", "secret")

    token = service.authenticate_user("alice", "secret")
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )

    assert payload["sub"] == str(repository.get_by_username("alice").id)
    assert payload["role"] == "regular_user"


def test_register_user(test_session):
    repository = UserRepository(test_session)
    auth_service = AuthService(repository)
    auth_service.register_user("alice", "alice@example.com", "secret")

    users = UserService(repository).get_all_users()

    assert len(users) == 1
    assert users[0].username == "alice"
    assert users[0].email == "alice@example.com"
