# Screen Mirroring

基于 RustDesk 的自托管远程桌面方案，包含服务端部署、管理后台和定制版 Windows 客户端。

- **远程控制与屏幕共享**：跨网络连接，能打洞时点对点直连，打不通时经服务器中继。
- **定制客户端**：可选传输分辨率（只缩放编码画面，不改对方显示器设置）、帧率跟随屏幕刷新率（最高 240 Hz）、按网络状况自适应、被控方本地鼠标优先。
- **管理后台**：查看在线设备、当前连接（谁在控制哪台设备）、连接记录，以及服务器 CPU、内存、带宽。

## 目录

- [架构](#架构)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [配置](#配置)
- [客户端](#客户端)
- [运维](#运维)
- [启用域名 HTTPS](#启用域名-https)
- [安全说明](#安全说明)
- [开发](#开发)
- [许可证](#许可证)

## 架构

```
 控制端（RustDesk 客户端）                          被控端（RustDesk 客户端）
   解码显示、键鼠 ──────── 直连（打洞成功时）────────→ 屏幕采集、硬件编码、执行键鼠
                     │ 打洞失败时
                     ▼
              hbbr 中继（21117/TCP）

        ↕ 注册、打洞信令                              ↕
     hbbs（21115-21116/TCP、21116/UDP）

        ↓ 心跳、设备信息、连接记录（http://<服务器>:21114/api/）
     后台服务 server/（Python FastAPI）── 管理后台 https://<服务器>/admin
```

| 组件 | 说明 |
|---|---|
| hbbs / hbbr | RustDesk 官方服务端（1.1.16），负责设备注册、打洞和中继。以 `-k _` 启动，只接受内置了本服务器公钥的客户端 |
| 后台服务 | 接收客户端上报，提供管理后台。上报端口只开放 `/api/`，后台页面只走 HTTPS |
| 定制客户端 | RustDesk 1.5.0 + 本仓库补丁，编译时写入服务器地址 |

## 仓库结构

| 路径 | 内容 |
|---|---|
| `server/` | 后台服务与管理后台页面 |
| `deploy/` | docker compose、RustDesk 服务端镜像、部署脚本、`.env.example` |
| `client/` | 定制客户端的补丁（`rustdesk-1.5.0-custom.patch`）、编译脚本和说明 |
| `tests/` | 后台服务测试 |

以下内容不在仓库中，由 `.gitignore` 排除：

| 路径 | 内容 |
|---|---|
| `deploy/.env`、`client/.env` | 服务器地址、后台账号密码等本地配置 |
| `*.local.md` | 具体部署信息的本地记录 |
| `deploy/rustdesk/bin/` | hbbs / hbbr 程序，从官方发布页下载 |
| `rustdesk/` | RustDesk 源码，按 `client/README.md` 拉取并打补丁 |
| `release/` | 编译出的客户端安装包 |

## 快速开始

**要求**：一台有公网 IP 的 Linux 服务器（已装 Docker 和 docker compose 插件）；本地 Windows，装有 OpenSSH 客户端。

1. **准备服务端程序**：从 [rustdesk-server 1.1.16](https://github.com/rustdesk/rustdesk-server/releases/tag/1.1.16) 下载 `rustdesk-server-linux-amd64.zip`，把其中的 `hbbs`、`hbbr` 放到 `deploy/rustdesk/bin/`。
2. **填写配置**：把 `deploy/.env.example` 复制为 `deploy/.env` 并填写，见[配置](#配置)。
3. **安装部署密钥**（只需一次，运行时需要输入服务器密码）：

   ```bash
   ssh-keygen -t ed25519 -f %USERPROFILE%\.ssh\screen_mirroring_deploy
   powershell -ExecutionPolicy Bypass -File deploy\install-ssh-key.ps1
   ```

4. **部署**：

   ```bash
   powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1
   ```

5. **放行端口**：在云服务器的安全组或防火墙中放行下表端口。

| 端口 | 协议 | 用途 |
|---|---|---|
| 443 | TCP | 管理后台 |
| 21114 | TCP | 客户端上报（只开放 `/api/`） |
| 21115-21117 | TCP | RustDesk 信令、NAT 检测、中继 |
| 21116 | UDP | RustDesk 注册与打洞 |

首次启动时，hbbs 会在服务器的 `deploy/data/rustdesk/` 下生成密钥对，`id_ed25519.pub` 就是客户端需要内置的公钥。

## 配置

`deploy/.env`：

| 变量 | 说明 |
|---|---|
| `ADMIN_USER` / `ADMIN_PASSWORD` | 管理后台账号密码。留空则关闭后台 |
| `PUBLIC_IP` | 服务器公网 IP。用作 hbbs 下发的中继地址、自签名证书的主机名，以及部署脚本默认登录的地址 |
| `HTTPS_PORT` | 管理后台端口，默认 443 |
| `PIP_INDEX_URL` | 构建镜像时使用的 PyPI 源 |

`client/.env`：编译定制客户端时写入的服务器地址、公钥和上报接口，见 `client/.env.example`。

## 客户端

- **定制客户端**：见 [client/README.md](client/README.md)。包括补丁内容、编译环境和编译方法。
- **官方客户端**：把官方 RustDesk 客户端改名为 `rustdesk-host=<服务器地址>,key=<公钥>,.exe`，即可使用本服务器并向后台上报，但没有定制功能。

## 运维

| 操作 | 方法 |
|---|---|
| 更新服务端 | 修改 `server/` 或 `deploy/` 后运行 `deploy\deploy.ps1` |
| 查看日志 | 在服务器上执行 `cd /opt/screen_mirroring/deploy && docker compose logs --tail 50` |
| 数据持久化 | 服务器 `deploy/data/`：事件库、自签名证书、RustDesk 密钥与设备库。重新部署不会丢失 |
| 带宽 | 直连不占服务器带宽；中继按连接限速（hbbr 默认单连接 128 Mbps，长时间大流量降为 32 Mbps） |

## 启用域名 HTTPS

默认情况下，管理后台使用自签名证书。如果有域名，可以用 `deploy/Caddyfile` 改为 Let's Encrypt 正式证书。Caddy 通过 tls-alpn-01 只用 443 端口完成验证，不需要开放 80 端口。

> 中国大陆的服务器使用域名提供网站服务，需要先完成 ICP 备案，否则可能被云服务商拦截。

1. `deploy/.env` 增加 `DOMAIN=<你的域名>`，并把域名的 A 记录解析到服务器。
2. 修改 `deploy/docker-compose.yml`：
   - app 的环境变量改为 `HOST: 127.0.0.1`、`PORT: "8000"`，增加 `RUSTDESK_API_HOST: 0.0.0.0`，删除 `TLS_SELF_SIGNED` 和 `PUBLIC_HOST`。
   - 新增 `caddy` 服务：镜像 `caddy:2.8`，`network_mode: host`，环境变量 `DOMAIN`、`PUBLIC_IP`，挂载 `./Caddyfile:/etc/caddy/Caddyfile:ro` 和 `./data/caddy:/data`。
3. 修改 `deploy/deploy.ps1`：打包列表加入 `deploy/Caddyfile`，`docker compose up` 之后执行 `docker compose restart caddy`。单文件挂载在文件被替换后不会自动更新，需要重启容器。

## 安全说明

- 不要把 `deploy/.env`、`client/.env`、`*.local.md` 以及服务器上的 `deploy/data/` 提交到仓库，也不要公开分享。
- RustDesk 公钥本身可以公开，但服务器地址加上公钥，就能让任何人使用你的服务器做中继。如果仓库公开，请不要在仓库里写出这两项。
- 管理后台使用 HTTP Basic 认证。同一 IP 连续 10 次密码错误后，会被拒绝 10 分钟。
- 上报接口（21114）没有登录凭证，后台会用 hbbs 的设备库核对设备 ID 和 UUID，防止伪造上报。

## 开发

```bash
python -m pip install virtualenv
python -m virtualenv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m server
```

本地运行时，管理后台在 `http://127.0.0.1:8000/admin`，需要通过环境变量 `ADMIN_PASSWORD` 设置密码。

## 许可证

客户端补丁修改自 [RustDesk](https://github.com/rustdesk/rustdesk)（AGPL-3.0）。分发修改后的客户端时，需要按 AGPL-3.0 提供对应源码。本仓库已经包含了全部改动（`client/rustdesk-1.5.0-custom.patch`）。
