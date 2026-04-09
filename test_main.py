from fastapi.testclient import TestClient
from main import app, r
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def wipe_redis():
    # Flush redis db to have a clean state before each test
    r.flushdb()
    yield
    r.flushdb()

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_register_resource():
    response = client.post("/register-resource", json={
        "resource_id": "test-vm-1",
        "resource_type": "vm",
        "region": "us-east-1"
    })
    assert response.status_code == 200
    assert response.json()["status"] == "registered"
    assert response.json()["resource_id"] == "test-vm-1"

def test_request_access_not_found():
    response = client.post("/request-access", json={
        "developer_id": "dev01",
        "resource_id": "non_existent",
        "reason": "Fix bug"
    })
    assert response.status_code == 404

def test_request_access_workflow():
    # 1. Register
    client.post("/register-resource", json={
        "resource_id": "test-vm-1",
        "resource_type": "vm"
    })

    # 2. Request
    req_resp = client.post("/request-access", json={
        "developer_id": "dev01",
        "resource_id": "test-vm-1",
        "reason": "Debugging",
        "ttl": 3600
    })
    assert req_resp.status_code == 200
    data = req_resp.json()
    assert data["status"] == "pending"
    req_id = data["request_id"]

    # 3. Status is pending
    stat_resp = client.get(f"/request/{req_id}")
    assert stat_resp.json()["status"] == "pending"

def test_validate_invalid_token():
    resp = client.post("/validate", json={
        "token": "fake_token",
        "resource_id": "test-vm-1"
    })
    assert resp.status_code == 401
