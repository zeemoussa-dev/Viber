import os
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

MIGRATIONS_DIRECTORY = Path(__file__).parent / "migrations"
MIGRATION_ADVISORY_LOCK_ID = 7_261_001

_connection_pool: ConnectionPool | None = None


class DryRunRollback(Exception):
    """Raised to roll a transaction back after a dry run has computed its counts."""


def connection_pool() -> ConnectionPool:
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool(
            os.environ["VIBER_DATABASE_URL"],
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _connection_pool


def close_pool() -> None:
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.close()
        _connection_pool = None


@contextmanager
def transaction():
    with connection_pool().connection() as connection:
        yield connection


def run_migrations() -> list[str]:
    applied_now: list[str] = []
    with transaction() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,))
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        already_applied = {row["name"] for row in connection.execute("SELECT name FROM schema_migration")}
        for migration_file in sorted(MIGRATIONS_DIRECTORY.glob("*.sql")):
            if migration_file.name in already_applied:
                continue
            connection.execute(migration_file.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migration (name) VALUES (%s)", (migration_file.name,))
            applied_now.append(migration_file.name)
    return applied_now


def to_database_value(value):
    return Jsonb(value) if isinstance(value, (dict, list)) else value


def insert_idempotent(connection, table: str, values: dict) -> tuple[str | None, bool]:
    """Insert a row; any unique-key collision (source_ref or key) means 'already there'."""
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))
    statement = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING RETURNING id"
    )
    row = connection.execute(statement, [to_database_value(values[column]) for column in columns]).fetchone()
    return (str(row["id"]), True) if row else (None, False)


def record_audit(connection, actor: str, action: str, entity: str, entity_id: str | None, project_id, detail: dict | None = None):
    connection.execute(
        "INSERT INTO audit (actor, action, entity, entity_id, project_id, detail) VALUES (%s,%s,%s,%s,%s,%s)",
        (actor, action, entity, entity_id, project_id, Jsonb(detail or {})),
    )
