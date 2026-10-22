import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from server.app import Settings, create_app

ADMIN = ("admin", "pw")
UUID = b"machine-uuid-1"


@pytest.fixture
def hbbs_db(tmp_path):
    # 模拟 hbbs 的设备库：只有注册过的设备才能上报
    path = tmp_path / "db_v2.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE peer (id TEXT, uuid BLOB)")
        db.execute("INSERT INTO peer VALUES (?, ?)", ("123456789", UUID))
    return path


@pytest.fixture
def client(tmp_path, hbbs_db):
    settings = Settings(admin_password="pw", data_dir=str(tmp_path / "data"), rustdesk_db=str(hbbs_db))
    with TestClient(create_app(settings)) as c:
        yield c


def device(**extra):
    return {"id": "123456789", "uuid": base64.b64encode(UUID).decode(), **extra}


def rustdesk_overview(client):
    return client.get("/admin/api/overview", auth=ADMIN).json()["rustdesk"]


def test_device_reports_show_up_in_admin(client):
    # 第一次心跳没有设备信息，要求客户端补传
    assert client.post("/api/heartbeat", json=device(ver=1005000)).json() == {"sysinfo": True}
    info = {"hostname": "小明的电脑", "os": "Windows 11", "cpu": "i7", "memory": "32GB", "version": "1.5.0"}
    assert client.post("/api/sysinfo", json=device(**info)).text == "SYSINFO_UPDATED"
    assert client.post("/api/heartbeat", json=device(ver=1005000)).json() == {}

    overview = rustdesk_overview(client)
    assert overview["online"] == 1
    assert overview["devices"][0]["hostname"] == "小明的电脑"
    assert overview["devices"][0]["online"] is True


def test_connection_lifecycle(client):
    client.post("/api/sysinfo", json=device(hostname="小明的电脑"))
    client.post("/api/audit/conn", json=device(action="new", ip="1.2.3.4", conn_id=7, session_id=1))
    client.post("/api/audit/conn", json=device(peer=["987654321", "小红"], type=0, conn_id=7))
    client.post("/api/heartbeat", json=device(conns=[7]))

    [session] = rustdesk_overview(client)["sessions"]
    assert session["controller_name"] == "小红"
    assert session["type"] == "远程控制"
    assert session["device_name"] == "小明的电脑"

    # 客户端崩溃时收不到 close，心跳里不再有这个连接就算结束
    client.post("/api/heartbeat", json=device(conns=[]))
    assert rustdesk_overview(client)["sessions"] == []
    kinds = [e["kind"] for e in client.get("/admin/api/overview", auth=ADMIN).json()["events"]]
    assert kinds[:3] == ["rd-close", "rd-auth", "rd-connect"]


def test_unregistered_device_is_ignored(client):
    fake = {"id": "123456789", "uuid": base64.b64encode(b"someone-else").decode(), "hostname": "冒充"}
    assert client.post("/api/sysinfo", json=fake).text == "ID_NOT_FOUND"
    assert rustdesk_overview(client)["devices"] == []


def test_api_port_only_serves_api(tmp_path, hbbs_db):
    # 测试客户端的 server 端口是 80，把它当成明文上报端口
    settings = Settings(admin_password="pw", data_dir=str(tmp_path), rustdesk_db=str(hbbs_db), api_port=80)
    with TestClient(create_app(settings)) as c:
        assert c.get("/admin", auth=ADMIN).status_code == 404
        assert c.get("/").status_code == 404
        assert c.post("/api/heartbeat", json=device()).status_code == 200
