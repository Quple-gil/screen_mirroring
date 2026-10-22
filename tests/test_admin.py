import pytest
from fastapi.testclient import TestClient

from server.app import Settings, create_app

ADMIN = ("admin", "pw")


def make_client(tmp_path, **overrides):
    return TestClient(create_app(Settings(admin_password="pw", data_dir=str(tmp_path), **overrides)))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def test_admin_requires_password(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin/api/overview", auth=("admin", "wrong")).status_code == 401
    assert client.get("/admin", auth=ADMIN).status_code == 200


def test_root_redirects_to_admin(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/admin"


def test_admin_disabled_without_password(tmp_path):
    with TestClient(create_app(Settings(data_dir=str(tmp_path)))) as c:
        assert c.get("/admin").status_code == 404


def test_too_many_wrong_passwords_block_ip(client):
    for _ in range(10):
        assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    # 密码对了也要等冷却
    assert client.get("/admin", auth=ADMIN).status_code == 429


def test_overview_has_server_and_system_info(client):
    data = client.get("/admin/api/overview", auth=ADMIN).json()
    assert data["system"]["mem_total"] > 0
    assert data["rustdesk"] == {"devices": [], "sessions": [], "online": 0}


def test_metrics_rate_covers_only_last_sample_period(monkeypatch):
    from server import metrics

    counters = iter([(0, 0), (8_000_000, 1_000_000), (8_000_000, 1_000_000)])
    clock = iter([100.0, 1100.0, 1102.0])  # 第一次采样前隔了很久，第二次只隔 2 秒
    monkeypatch.setattr(metrics, "_external_bytes", lambda: next(counters))
    monkeypatch.setattr(metrics.time, "monotonic", lambda: next(clock))
    sampler = metrics.SystemMetrics()
    sampler.sample()
    sampler.sample()
    snapshot = sampler.snapshot()
    assert snapshot["net_tx_bps"] == 0  # 最近 2 秒没有流量，不应该被很久以前的流量摊出数值
    assert snapshot["net_rx_bps"] == 0


def test_self_signed_certificate_is_reused(tmp_path):
    from server.tls import ensure_self_signed, fingerprint

    cert, _ = ensure_self_signed(tmp_path, "203.0.113.10")
    first = fingerprint(cert)
    ensure_self_signed(tmp_path, "203.0.113.10")
    assert fingerprint(cert) == first
    assert len(first.split(":")) == 32
