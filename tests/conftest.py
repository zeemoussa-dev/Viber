import os
import uuid

import psycopg
import pytest


def recreate_test_database() -> None:
    admin_url = os.environ["VIBER_ADMIN_DATABASE_URL"]
    test_database = os.environ["VIBER_DATABASE_URL"].rsplit("/", 1)[1]
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE)')
        connection.execute(f'CREATE DATABASE "{test_database}"')


@pytest.fixture(scope="session")
def client():
    recreate_test_database()
    from fastapi.testclient import TestClient
    from viber.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project_key(client):
    key = f"p{uuid.uuid4().hex[:8]}"
    response = client.post("/v1/projects", json={"key": key, "name": f"Project {key}"})
    assert response.status_code == 201, response.text
    return key
