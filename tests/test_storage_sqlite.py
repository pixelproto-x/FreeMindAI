import sqlite3

import pytest

from freemind.storage import _configure_sqlite_connection, _resolve_database_url


class FakeCursor:
    def __init__(self, fail_delete=False):
        self.statements = []
        self.fail_delete = fail_delete
        self.closed = False

    def execute(self, statement):
        self.statements.append(statement)
        if statement == "PRAGMA journal_mode=WAL":
            raise sqlite3.OperationalError("disk I/O error")
        if statement == "PRAGMA journal_mode=DELETE" and self.fail_delete:
            raise sqlite3.OperationalError("database is read-only")

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, fail_delete=False):
        self.fake_cursor = FakeCursor(fail_delete=fail_delete)

    def cursor(self):
        return self.fake_cursor


def test_relative_sqlite_database_url_is_resolved_from_project_root():
    resolved = _resolve_database_url("sqlite:///./data/freemind.db")
    assert resolved.startswith("sqlite:///")
    assert resolved.endswith("/data/freemind.db")


def test_sqlite_wal_failure_falls_back_to_delete_journal(capsys):
    connection = FakeConnection()
    _configure_sqlite_connection(connection)

    assert "PRAGMA journal_mode=WAL" in connection.fake_cursor.statements
    assert "PRAGMA journal_mode=DELETE" in connection.fake_cursor.statements
    assert connection.fake_cursor.closed
    assert "DELETE journal mode" in capsys.readouterr().out


def test_sqlite_reports_both_journal_errors_when_fallback_fails():
    connection = FakeConnection(fail_delete=True)

    with pytest.raises(RuntimeError, match="WAL: disk I/O error; DELETE: database is read-only"):
        _configure_sqlite_connection(connection)

    assert connection.fake_cursor.closed
