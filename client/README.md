# 定制版 RustDesk 客户端

原生 Windows 客户端，基于 RustDesk 1.5.0（Rust 核心 + Flutter 界面，不依赖浏览器内核）。
源码在 `../rustdesk`，我们的改动都在它的 `custom` 分支上。

## 相对 RustDesk 1.5.0 的改动

| 功能 | 说明 | 主要文件 |
|---|---|---|
| 内置服务器（可选） | 编译时设置了 `RD_HOST` / `RD_KEY` / `RD_API` 就写进客户端，不用改文件名也不用手动设置。不设置则是通用版，在设置里填写服务器 | `src/custom_server.rs`、`src/platform/windows.rs` |
| 传输分辨率 | 控制端可选：原始（默认）、自动（根据网络）、或按对方屏幕宽高比生成的 1440p / 1080p / 900p / 720p / 540p。**只缩放编码前的画面，不改对方显示器的实际分辨率** | `src/server/stream_scale.rs`、`src/server/video_service.rs`、`libs/scrap/src/common/convert.rs` |
| 帧率 | 跟随对方屏幕刷新率（自动读取，最高 240），或固定帧率。原版默认只有 30 帧，且自定义帧率要先把画质设成“自定义” | `src/server/stream_scale.rs`、`src/server/video_qos.rs` |
| 自动调整时优先 | 优先刷新率：网络紧张时先降分辨率保帧率；优先分辨率：先降帧率，帧率低于 10 才降分辨率。档位变化至少间隔 10 秒 | `src/server/stream_scale.rs` |
| 刷新率上报 | 被控端把屏幕当前刷新率发给控制端，用来生成帧率列表 | `src/server/display_service.rs`、`libs/base/protos/message.proto` |
| 缩放时的显示与坐标 | 控制端按"屏幕尺寸"建解码器和纹理，所以传输分辨率变化时，被控端发一条屏幕尺寸变化通知（中途加入的观看者也会补发），并在鼠标坐标、指针位置上做原始尺寸和缩放尺寸的双向换算 | `src/server/stream_scale.rs`、`src/server/video_service.rs`、`src/server/input_service.rs` |
| 控制端帧率上限 | 原版控制端会按"自定义帧率"（默认 30，最高 120）反复覆盖被控端的帧率；改为跟随"帧率"菜单，上限放宽到 240，仍不超过本机解码能力 | `src/client.rs`、`src/client/io_loop.rs` |
| 本地鼠标优先 | 被控端的人一动自己的鼠标，就忽略控制方的鼠标操作，停手 0.8 秒后恢复；松开按键的事件始终放行。原版这个功能被禁用了，这里改用低级鼠标钩子区分真实输入和远程注入 | `src/server/local_mouse.rs`、`src/server/input_service.rs` |
| 一键复制与连接 | 被控端一次性密码旁边的复制按钮，把 ID、一次性密码和 `rustdesk://<ID>?password=<密码>` 链接复制成一段文字。控制端把这段文字粘贴到输入框就直接连接，不用再输密码；装了客户端的也可以直接点链接 | `flutter/lib/common/widgets/connect_invite.dart`、`flutter/lib/desktop/pages/desktop_home_page.dart`、`flutter/lib/desktop/pages/connection_page.dart` |
| 检查更新 | 更新源从 rustdesk.com 换成本仓库的 GitHub Releases（最新发布的标签和编译时写入的 `SM_VERSION` 比较），沿用原版的更新提示、一键更新和“自动更新”开关。下载文件名为 `rustdesk-<标签>-x86_64.exe`，由发布流水线生成 | `src/custom_update.rs`、`src/common.rs` |
| 直连方式默认开启 | UDP 打洞、IPv6 直连、WebRTC 直连默认开启（原版对自建服务器默认关闭，在设置里手动关闭仍然有效） | `src/common.rs` |

协议新增字段都从 1001 开始编号（`DisplayInfo.refresh_rate`、`OptionMessage.stream_resolution / stream_priority / stream_fps`），
官方客户端连进来时不会发这些字段，被控端行为和原版一致。

## 获取源码

`rustdesk/` 不在本仓库里，我们的全部改动保存在 `client/rustdesk-1.5.0-custom.patch`。在项目根目录执行：

```bash
git clone --depth 1 --branch 1.5.0 --recurse-submodules --shallow-submodules https://github.com/rustdesk/rustdesk.git rustdesk
cd rustdesk
git checkout -b custom
git apply ../client/rustdesk-1.5.0-custom.patch
```

改了 `rustdesk/` 之后，在 `rustdesk/` 里提交，再用 `git diff 1.5.0 HEAD > ../client/rustdesk-1.5.0-custom.patch` 更新补丁。

## 编译环境（已在本机搭好，位于 `D:\rustdesk-build`）

| 组件 | 版本 | 位置 |
|---|---|---|
| VS 2022 生成工具（C++） | MSVC 14.44 + Windows SDK 10.0.26100 | 系统已有 |
| Rust | 1.75（rustup） | `~/.rustup` |
| LLVM | 15.0.6 | `D:\rustdesk-build\llvm` |
| Flutter | 3.24.5 + RustDesk 定制引擎 + 下拉菜单补丁 | `D:\rustdesk-build\flutter` |
| vcpkg | 9e593bb1，依赖装在 `installed\x64-windows-static` | `D:\rustdesk-build\vcpkg` |
| flutter_rust_bridge_codegen | 1.80.1，另有 cargo-expand 1.0.95 | `~/.cargo/bin` |

## 编译

```bash
powershell -ExecutionPolicy Bypass -File client\build.ps1
```

- 只改了 Flutter 界面：加 `-SkipCargo`。
- 没改 `src/flutter_ffi.rs`：加 `-SkipBridge`，省去生成桥接代码的时间。
- 换服务器：`-ServerHost`、`-ServerKey`（服务器 `deploy/data/rustdesk/id_ed25519.pub` 的内容）、`-ApiServer`。

产物在 `rustdesk\flutter\build\windows\x64\runner\Release`。
