"""
Unit and Integration Tests for CodePilot Local Runtime.
"""

import pytest
from fastapi.testclient import TestClient
from runtime.server import runtime_app
from runtime.auth import pairing_manager

client = TestClient(runtime_app)


def setup_function():
    """Reset pairing state before each test."""
    pairing_manager.revoke_all_sessions()


def test_runtime_health():
    """Test public health endpoint."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "docker_available" in data
    assert "version" in data


def test_runtime_version():
    """Test version endpoint."""
    res = client.get("/version")
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == "1.0.0"
    assert "python" in data["supported_languages"]


def test_cors_and_private_network_access():
    """Test that allowed origins and Private Network Access headers are returned."""
    # 1. Preflight from production Vercel frontend
    headers = {
        "Origin": "https://codepilot-frontend.vercel.app",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true",
    }
    res = client.options("/execute", headers=headers)
    assert res.status_code == 204
    assert res.headers.get("access-control-allow-origin") == "https://codepilot-frontend.vercel.app"
    assert res.headers.get("access-control-allow-private-network") == "true"

    # 2. Preflight from unauthorized origin
    evil_headers = {
        "Origin": "https://malicious-site.com",
        "Access-Control-Request-Method": "POST",
    }
    res_evil = client.options("/execute", headers=evil_headers)
    assert res_evil.headers.get("access-control-allow-origin") is None


def test_dns_rebinding_protection():
    """Test that non-localhost Host header is rejected."""
    headers = {"Host": "attacker-dns-rebind.com"}
    res = client.get("/health", headers=headers)
    assert res.status_code == 400
    assert "Invalid Host" in res.text


def test_pairing_workflow_and_authentication():
    """Test end-to-end pairing code generation, confirmation, and session verification."""
    # 1. Request pairing code
    pair_res = client.post("/pair/request")
    assert pair_res.status_code == 200
    pair_data = pair_res.json()
    code = pair_data["pairing_code"]
    assert len(code) == 6

    # 2. Attempt confirm with wrong code
    wrong_res = client.post("/pair/confirm", json={"pairing_code": "000000"})
    assert wrong_res.status_code == 401

    # 3. Confirm with valid code
    confirm_res = client.post("/pair/confirm", json={"pairing_code": code})
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["status"] == "paired"
    token = confirm_data["session_token"]
    assert token.startswith("cp_rt_")

    # 4. Access protected execute endpoint with valid token
    exec_payload = {
        "language": "python",
        "code": "print('LOCAL RUNTIME TEST OK')",
        "stdin": "",
    }
    auth_headers = {"Authorization": f"Bearer {token}"}
    exec_res = client.post("/execute", json=exec_payload, headers=auth_headers)
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["status"] == "success"
    assert "LOCAL RUNTIME TEST OK" in exec_data["stdout"]

    # 5. Access protected endpoint with invalid token
    bad_res = client.post("/execute", json=exec_payload, headers={"Authorization": "Bearer invalid_token"})
    assert bad_res.status_code == 401


def test_execution_python_stdin():
    """Test Python execution with standard input."""
    # Pair first
    pair_res = client.post("/pair/request")
    code = pair_res.json()["pairing_code"]
    token = client.post("/pair/confirm", json={"pairing_code": code}).json()["session_token"]

    payload = {
        "language": "python",
        "code": "import sys\nname = sys.stdin.read().strip()\nprint(f'Hello {name}!')",
        "stdin": "CodePilotUser",
    }
    res = client.post("/execute", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "Hello CodePilotUser!" in data["stdout"]


def test_execution_cpp():
    """Test C++ compilation and execution."""
    pair_res = client.post("/pair/request")
    code = pair_res.json()["pairing_code"]
    token = client.post("/pair/confirm", json={"pairing_code": code}).json()["session_token"]

    payload = {
        "language": "cpp",
        "code": "#include <iostream>\nint main() { std::cout << \"CPP RUNTIME OK\" << std::endl; return 0; }",
        "stdin": "",
    }
    res = client.post("/execute", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "CPP RUNTIME OK" in data["stdout"]


def test_execution_java():
    """Test Java compilation and execution."""
    pair_res = client.post("/pair/request")
    code = pair_res.json()["pairing_code"]
    token = client.post("/pair/confirm", json={"pairing_code": code}).json()["session_token"]

    payload = {
        "language": "java",
        "code": "public class Solution { public static void main(String[] args) { System.out.println(\"JAVA RUNTIME OK\"); } }",
        "stdin": "",
    }
    res = client.post("/execute", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "JAVA RUNTIME OK" in data["stdout"]


def test_execution_timeout():
    """Test execution timeout enforcement."""
    pair_res = client.post("/pair/request")
    code = pair_res.json()["pairing_code"]
    token = client.post("/pair/confirm", json={"pairing_code": code}).json()["session_token"]

    payload = {
        "language": "python",
        "code": "import time\ntime.sleep(5)",
        "stdin": "",
        "custom_timeout": 1,
    }
    res = client.post("/execute", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "timeout"

