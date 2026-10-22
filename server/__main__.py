"""用 `python -m server` 启动服务。

环境变量：HOST / PORT 监听地址；TLS_CERT + TLS_KEY 指定证书，
或者 TLS_SELF_SIGNED=1 自动在 DATA_DIR/tls 下生成自签名证书（证书主机名取 PUBLIC_HOST）。
RUSTDESK_API_PORT 不为空时，同一个进程再开一个明文 HTTP 端口给 RustDesk 客户端上报（只开放 /api/），
监听地址取 RUSTDESK_API_HOST（默认同 HOST）。
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    # Windows 下输出被重定向时默认是 GBK，统一成 UTF-8 免得日志里的中文乱码
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("screen_mirroring")

    cert, key = os.environ.get("TLS_CERT", ""), os.environ.get("TLS_KEY", "")
    if not cert and os.environ.get("TLS_SELF_SIGNED") == "1":
        from server.tls import ensure_self_signed, fingerprint

        tls_dir = Path(os.environ.get("DATA_DIR", "data")) / "tls"
        cert_path, key_path = ensure_self_signed(tls_dir, os.environ.get("PUBLIC_HOST", "localhost"))
        cert, key = str(cert_path), str(key_path)
        os.environ["TLS_CERT"] = cert  # 让后台页面能显示证书指纹
        log.info("TLS 证书指纹（桌面客户端要填这个）：%s", fingerprint(cert_path))

    from server.app import create_app

    app = create_app()
    host = os.environ.get("HOST", "127.0.0.1")
    configs = [
        uvicorn.Config(
            app,
            host=host,
            port=int(os.environ.get("PORT", "8000")),
            ssl_certfile=cert or None,
            ssl_keyfile=key or None,
        )
    ]
    api_port = int(os.environ.get("RUSTDESK_API_PORT", "0"))
    if api_port:
        # 后台页面可以只对本机开放（由 Caddy 反向代理），上报端口则要对外
        api_host = os.environ.get("RUSTDESK_API_HOST", host)
        configs.append(uvicorn.Config(app, host=api_host, port=api_port, lifespan="off"))
    asyncio.run(_serve_all([uvicorn.Server(config) for config in configs]))


async def _serve_all(servers: list[uvicorn.Server]) -> None:
    # 每个 Server 都会接管退出信号，但只有最后一个能收到；任何一个退出就让其他的一起退出
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for server in servers:
        server.should_exit = True
    await asyncio.gather(*pending)


if __name__ == "__main__":
    main()
