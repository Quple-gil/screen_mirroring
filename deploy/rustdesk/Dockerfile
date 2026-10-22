# RustDesk 官方服务端：hbbs（ID 注册、打洞信令）+ hbbr（中继）
# 服务器拉不到 Docker Hub 上的官方镜像，改用官方发布的 Linux 程序（bin/，部署脚本会一起上传）自己打包
FROM debian:bookworm-slim

COPY bin/hbbs bin/hbbr /usr/local/bin/
RUN chmod +x /usr/local/bin/hbbs /usr/local/bin/hbbr

# 密钥对和设备数据库都放在 /data，挂载到宿主机，重新部署不会变
WORKDIR /data
