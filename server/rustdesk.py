"""RustDesk 客户端的上报接口（和 RustDesk Pro 的 /api/heartbeat、/api/sysinfo、/api/audit/conn 兼容）。

客户端没配 api-server 时会自动向 http://<ID服务器>:21114 上报：每 15 秒心跳（带当前连接）、设备信息、
每个连接的建立 / 授权 / 断开。这里把它们整理成后台能看的“设备 + 正在进行的连接”。

开源版客户端上报时不带登录 token，所以拿 hbbs 数据库核对 id + uuid，防止别人冒充设备乱报。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from server.events import EventLog, format_duration

log = logging.getLogger("screen_mirroring")

ONLINE_SECONDS = 45  # 心跳 15 秒一次，连着错过两次算离线
MAX_BODY_BYTES = 64 * 1024
SYSINFO_FIELDS = ("hostname", "username", "os", "cpu", "memory", "version")
CONN_TYPES = {0: "远程控制", 1: "文件传输", 2: "端口转发", 3: "查看摄像头", 4: "终端"}


@dataclass
class Session:
    device_id: str
    conn_id: int
    ip: str
    started_at: float
    controller_id: str = ""
    controller_name: str = ""
    conn_type: int | None = None

    def snapshot(self) -> dict:
        return {
            "device_id": self.device_id,
            "conn_id": self.conn_id,
            "ip": self.ip,
            "since": self.started_at,
            "controller_id": self.controller_id,
            "controller_name": self.controller_name,
            "type": CONN_TYPES.get(self.conn_type, "连接中") if self.conn_type is not None else "等待验证",
        }


@dataclass
class Device:
    id: str
    ip: str = ""
    last_seen: float = 0.0
    info: dict = field(default_factory=dict)

    def snapshot(self, now: float) -> dict:
        return {
            "id": self.id,
            "ip": self.ip,
            "last_seen": self.last_seen,
            "online": now - self.last_seen < ONLINE_SECONDS,
            **{key: self.info.get(key, "") for key in SYSINFO_FIELDS},
        }


class HbbsPeers:
    """只读查询 hbbs 的设备库，确认上报的 id 和 uuid 是真实注册过的设备。"""

    def __init__(self, path: str) -> None:
        self.path = path

    def verify(self, device_id: str, uuid_b64: str) -> bool:
        if not self.path:
            return True  # 本机调试没有 hbbs 数据库时不校验
        try:
            uuid = base64.b64decode(uuid_b64, validate=True)
        except (binascii.Error, ValueError):
            return False
        try:
            with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=1) as db:
                row = db.execute("SELECT uuid FROM peer WHERE id = ?", (device_id,)).fetchone()
        except sqlite3.Error:
            log.warning("cannot read hbbs database %s", self.path, exc_info=True)
            return False
        return row is not None and bytes(row[0]) == uuid


class RustDeskRegistry:
    def __init__(self, events: EventLog, peers: HbbsPeers) -> None:
        self.events = events
        self.peers = peers
        self.devices: dict[str, Device] = {}
        self.sessions: dict[tuple[str, int], Session] = {}
        self.events.db.execute(
            "CREATE TABLE IF NOT EXISTS rustdesk_devices (id TEXT PRIMARY KEY, ip TEXT, last_seen REAL, info TEXT)"
        )
        for device_id, ip, last_seen, info in self.events.db.execute(
            "SELECT id, ip, last_seen, info FROM rustdesk_devices"
        ):
            self.devices[device_id] = Device(id=device_id, ip=ip or "", last_seen=last_seen or 0, info=json.loads(info))

    def _device(self, body: dict, ip: str) -> Device | None:
        device_id, uuid = body.get("id"), body.get("uuid")
        if not isinstance(device_id, str) or not isinstance(uuid, str) or not self.peers.verify(device_id, uuid):
            return None
        device = self.devices.setdefault(device_id, Device(id=device_id))
        device.ip = ip
        device.last_seen = time.time()
        return device

    def _save(self, device: Device) -> None:
        self.events.db.execute(
            "INSERT OR REPLACE INTO rustdesk_devices (id, ip, last_seen, info) VALUES (?, ?, ?, ?)",
            (device.id, device.ip, device.last_seen, json.dumps(device.info, ensure_ascii=False)),
        )
        self.events.db.commit()

    def heartbeat(self, body: dict, ip: str) -> dict:
        device = self._device(body, ip)
        if device is None:
            return {}
        conns = {c for c in body.get("conns") or [] if isinstance(c, int)}
        # 客户端异常退出时收不到 close，以心跳里的连接列表为准清理
        for key in [k for k in self.sessions if k[0] == device.id and k[1] not in conns]:
            self._close(self.sessions.pop(key), "连接已不在心跳列表里")
        self._save(device)
        return {} if device.info else {"sysinfo": True}  # 还没有设备信息就让客户端补传

    def sysinfo(self, body: dict, ip: str) -> str:
        device = self._device(body, ip)
        if device is None:
            return "ID_NOT_FOUND"
        device.info = {key: str(body.get(key, ""))[:200] for key in SYSINFO_FIELDS}
        self._save(device)
        return "SYSINFO_UPDATED"

    def audit_conn(self, body: dict, ip: str) -> None:
        device = self._device(body, ip)
        conn_id = body.get("conn_id")
        if device is None or not isinstance(conn_id, int):
            return
        key = (device.id, conn_id)
        action = body.get("action")
        if action == "new":
            peer_ip = str(body.get("ip", ""))[:64]
            self.sessions[key] = Session(device_id=device.id, conn_id=conn_id, ip=peer_ip, started_at=time.time())
            self.events.add("rd-connect", room=device.id, ip=peer_ip, detail=device.info.get("hostname", ""))
        elif action == "close":
            session = self.sessions.pop(key, None)
            if session is not None:
                self._close(session, "")
        elif "peer" in body and key in self.sessions:
            session = self.sessions[key]
            peer = body.get("peer")
            if isinstance(peer, list) and len(peer) == 2:
                session.controller_id, session.controller_name = (str(x)[:64] for x in peer)
            conn_type = body.get("type")
            session.conn_type = conn_type if isinstance(conn_type, int) else None
            self.events.add(
                "rd-auth",
                room=device.id,
                name=session.controller_name or session.controller_id,
                ip=session.ip,
                detail=f"{CONN_TYPES.get(session.conn_type, '连接')}（控制方 ID {session.controller_id}）",
            )

    def _close(self, session: Session, reason: str) -> None:
        detail = f"持续 {format_duration(time.time() - session.started_at)}"
        self.events.add(
            "rd-close",
            room=session.device_id,
            name=session.controller_name or session.controller_id,
            ip=session.ip,
            detail=f"{detail}，{reason}" if reason else detail,
        )

    def overview(self) -> dict:
        now = time.time()
        devices = sorted((d.snapshot(now) for d in self.devices.values()), key=lambda d: (not d["online"], d["id"]))
        sessions = sorted((s.snapshot() for s in self.sessions.values()), key=lambda s: s["since"])
        for session in sessions:
            device = self.devices.get(session["device_id"])
            session["device_name"] = device.info.get("hostname", "") if device else ""
        return {
            "devices": devices,
            "sessions": sessions,
            "online": sum(1 for d in devices if d["online"]),
        }


def create_router(registry: RustDeskRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def read_json(request: Request) -> dict:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return {}
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    @router.post("/heartbeat")
    async def heartbeat(request: Request) -> JSONResponse:
        return JSONResponse(registry.heartbeat(await read_json(request), client_ip(request)))

    @router.post("/sysinfo")
    async def sysinfo(request: Request) -> PlainTextResponse:
        return PlainTextResponse(registry.sysinfo(await read_json(request), client_ip(request)))

    @router.post("/audit/conn")
    async def audit_conn(request: Request) -> PlainTextResponse:
        registry.audit_conn(await read_json(request), client_ip(request))
        return PlainTextResponse("")

    @router.post("/audit/{kind}")
    async def audit_other(kind: str) -> PlainTextResponse:
        return PlainTextResponse("")  # 文件传输、告警等记录暂时不需要

    return router
