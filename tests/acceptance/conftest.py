"""Acceptance fixtures and a hard outbound-network guard."""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "acceptance"
SOURCE_DOCS = FIXTURES / "source_docs"
JOB_RECORDS = FIXTURES / "job_records"
GOLDEN = ROOT / "tests" / "golden"


@pytest.fixture(scope="session")
def acceptance_fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def acceptance_source_docs() -> Path:
    return SOURCE_DOCS


@pytest.fixture(scope="session")
def acceptance_job_records() -> Path:
    return JOB_RECORDS


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN


def _loopback(host: object) -> bool:
    if host in {None, "", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Normal acceptance tests may use loopback only, never a hosted service."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_connect(sock, address)

    def guarded_create(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_create(address, *args, **kwargs)

    def guarded_connect_ex(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
