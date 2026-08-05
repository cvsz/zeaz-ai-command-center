import pytest

import zai


class HealthClient:
    def __init__(self, healthy: bool = True):
        self.base_url = "http://127.0.0.1:8765"
        self._healthy = healthy
        self.health_checks = 0

    def healthy(self):
        self.health_checks += 1
        return self._healthy


def test_systemd_readiness_requires_main_pid_to_own_listener(monkeypatch):
    client = HealthClient(True)
    monkeypatch.setattr(zai, "systemd_user_service_state", lambda: (True, 4242))
    monkeypatch.setattr(zai, "pid_listens_on_port", lambda pid, port: False)

    assert zai.systemd_user_service_ready(client) is False
    assert client.health_checks == 0


def test_systemd_readiness_accepts_owned_listener_and_health(monkeypatch):
    client = HealthClient(True)
    observed = []
    monkeypatch.setattr(zai, "systemd_user_service_state", lambda: (True, 4242))
    monkeypatch.setattr(
        zai,
        "pid_listens_on_port",
        lambda pid, port: observed.append((pid, port)) or True,
    )

    assert zai.systemd_user_service_ready(client) is True
    assert observed == [(4242, 8765)]
    assert client.health_checks == 1


def test_pid_listener_ownership_uses_socket_inode_intersection(monkeypatch):
    monkeypatch.setattr(zai, "_pid_socket_inodes", lambda pid: {"101", "202"})
    monkeypatch.setattr(zai, "_listening_socket_inodes", lambda port: {"202", "303"})

    assert zai.pid_listens_on_port(4242, 8765) is True
    assert zai.pid_listens_on_port(0, 8765) is False
    assert zai.pid_listens_on_port(4242, 70000) is False


def test_remote_endpoint_never_starts_local_systemd(monkeypatch):
    client = HealthClient(False)
    client.base_url = "https://panel.example"
    monkeypatch.setattr(
        zai,
        "systemd_user_service_available",
        lambda: pytest.fail("remote endpoints must not probe the local user unit"),
    )

    with pytest.raises(zai.ZaiError, match="only for a local HTTP dashboard"):
        zai.ensure_server(client, auto_start=True)
