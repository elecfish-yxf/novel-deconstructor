import pytest
from sqlalchemy.exc import OperationalError

from novel_deconstructor import database


def _operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("temporary database startup failure"))


def test_mysql_init_db_retries_operational_error(monkeypatch):
    attempts = 0
    sleeps: list[float] = []

    def flaky_init() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _operational_error()

    monkeypatch.setattr(database.settings, "app_database_url", "mysql+pymysql://user:pass@example/db")
    monkeypatch.setattr(database, "_MYSQL_INIT_RETRY_DELAYS", (1.0, 2.0, 4.0))
    monkeypatch.setattr(database, "_init_db_once", flaky_init)

    database._run_init_db_with_retries(sleeps.append)

    assert attempts == 3
    assert sleeps == [1.0, 2.0]


def test_sqlite_init_db_does_not_retry_operational_error(monkeypatch):
    attempts = 0
    sleeps: list[float] = []

    def failing_init() -> None:
        nonlocal attempts
        attempts += 1
        raise _operational_error()

    monkeypatch.setattr(database.settings, "app_database_url", "sqlite:///example.db")
    monkeypatch.setattr(database, "_init_db_once", failing_init)

    with pytest.raises(OperationalError):
        database._run_init_db_with_retries(sleeps.append)

    assert attempts == 1
    assert sleeps == []
