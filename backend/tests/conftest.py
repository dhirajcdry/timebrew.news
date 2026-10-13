"""All tests are offline: never contact AWS, an AI provider, or send email."""
import os
import socket

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def block_external_connections(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is disabled in the offline test suite")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
