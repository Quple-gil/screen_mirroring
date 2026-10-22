"""后台服务：后台管理页 + RustDesk 客户端的上报接口。

RustDesk 客户端的连接、打洞和中继由同一台服务器上的 hbbs / hbbr 负责；
这里只收集客户端上报的设备和连接信息，加上服务器资源情况，给后台页面展示。
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from server.events import EventLog
from server.metrics import SystemMetrics
from server.rustdesk import HbbsPeers, RustDeskRegistry, create_router

log = logging.getLogger("screen_mirroring")

VERSION = "0.3.0"
ADMIN_PAGE = Path(__file__).resolve().parent / "admin.html"


@dataclass(frozen=True)
class Settings:
    admin_user: str = "admin"
    admin_password: str = ""  # 留空则关闭后台
    data_dir: str = "data"
    tls_cert: str = ""  # 只用于在后台显示证书指纹
    rustdesk_db: str = ""  # hbbs 的设备库，用来核对 RustDesk 客户端上报的身份；留空不校验
    api_port: int = 0  # 给 RustDesk 客户端上报用的明文 HTTP 端口，这个端口上只开放 /api/

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            admin_user=env.get("ADMIN_USER", "admin"),
            admin_password=env.get("ADMIN_PASSWORD", ""),
            data_dir=env.get("DATA_DIR", "data"),
            tls_cert=env.get("TLS_CERT", ""),
            rustdesk_db=env.get("RUSTDESK_DB", ""),
            api_port=int(env.get("RUSTDESK_API_PORT", "0")),
        )


class FailureLimiter:
    """同一个 IP 短时间内输错密码太多次就暂时拒绝，防止被暴力猜密码。"""

    def __init__(self, limit: int = 10, window: float = 600) -> None:
        self.limit = limit
        self.window = window
        self.failures: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self.failures.get(ip, []) if now - t < self.window]
        if recent:
            self.failures[ip] = recent
        else:
            self.failures.pop(ip, None)
        return len(recent) >= self.limit

    def fail(self, ip: str) -> None:
        self.failures.setdefault(ip, []).append(time.monotonic())


class ApiPortOnly:
    """明文的 RustDesk 上报端口只放行 /api/，后台页面只能走 HTTPS 端口。"""

    def __init__(self, app, port: int) -> None:
        self.app = app
        self.port = port

    async def __call__(self, scope, receive, send) -> None:
        server = scope.get("server") or (None, None)
        if (
            self.port
            and scope["type"] in ("http", "websocket")
            and server[1] == self.port
            and not scope["path"].startswith("/api/")
        ):
            if scope["type"] == "http":
                await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.admin_password:
        log.warning("ADMIN_PASSWORD 没有设置，后台管理页已关闭")

    events = EventLog(Path(settings.data_dir) / "events.db")
    limiter = FailureLimiter()
    rustdesk = RustDeskRegistry(events, HbbsPeers(settings.rustdesk_db))
    metrics = SystemMetrics()
    started_at = time.time()
    tls_fingerprint = ""
    if settings.tls_cert:
        from server.tls import fingerprint

        tls_fingerprint = fingerprint(settings.tls_cert)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        sampler = asyncio.create_task(metrics.run())
        try:
            yield
        finally:
            sampler.cancel()

    app = FastAPI(title="screen_mirroring", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(ApiPortOnly, port=settings.api_port)
    app.include_router(create_router(rustdesk))
    basic = HTTPBasic(auto_error=False)

    def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
        if not settings.admin_password:
            raise HTTPException(status_code=404)
        ip = request.client.host if request.client else ""
        if limiter.blocked(ip):
            raise HTTPException(status_code=429, detail="尝试次数太多，请 10 分钟后再试")
        if credentials is not None:
            user_ok = hmac.compare_digest(credentials.username.encode(), settings.admin_user.encode())
            password_ok = hmac.compare_digest(credentials.password.encode(), settings.admin_password.encode())
            if user_ok and password_ok:
                return
            limiter.fail(ip)  # 浏览器第一次不带账号的请求不算失败
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="admin", charset="UTF-8"'})

    @app.get("/")
    async def index() -> RedirectResponse:
        return RedirectResponse("/admin")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin_page() -> FileResponse:
        return FileResponse(ADMIN_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/admin/api/overview", dependencies=[Depends(require_admin)])
    async def admin_overview() -> dict:
        return {
            "server": {
                "version": VERSION,
                "started_at": started_at,
                "now": time.time(),
                "tls_fingerprint": tls_fingerprint,
            },
            "system": metrics.snapshot(),
            "rustdesk": rustdesk.overview(),
            "events": events.recent(100),
        }

    return app
