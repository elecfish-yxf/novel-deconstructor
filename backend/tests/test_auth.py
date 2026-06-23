from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.models import Base, Project, User, WorkspaceMember
from novel_deconstructor.services.auth import (
    authenticate_user,
    create_session,
    create_user_with_workspace,
    hash_password,
    user_from_token,
    verify_password,
    workspace_for_user,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_password_hash_verification_round_trip():
    encoded = hash_password("correct-password")

    assert verify_password("correct-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_register_creates_private_workspace_and_membership():
    db = _session()

    user, workspace = create_user_with_workspace(db, email="User@Example.com", password="correct-password", username="user1")

    assert user.email == "user@example.com"
    assert workspace.owner_user_id == user.id
    assert workspace_for_user(db, user) == workspace.id
    assert db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id).one()


def test_session_token_resolves_user_and_isolated_workspace_query():
    db = _session()
    user_a, workspace_a = create_user_with_workspace(db, email="a@example.com", password="correct-password")
    user_b, workspace_b = create_user_with_workspace(db, email="b@example.com", password="correct-password")
    db.add(Project(name="A Project", description="", workspace_id=workspace_a.id))
    db.add(Project(name="B Project", description="", workspace_id=workspace_b.id))
    db.commit()

    auth_session = create_session(db, user_a, days=1)
    resolved = user_from_token(db, auth_session.token)

    assert resolved and resolved.id == user_a.id
    assert authenticate_user(db, "a@example.com", "correct-password").id == user_a.id
    visible = db.query(Project).filter(Project.workspace_id == workspace_for_user(db, resolved)).all()
    assert [project.name for project in visible] == ["A Project"]
