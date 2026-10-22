"""服务器资源监控：CPU、内存、磁盘、网卡带宽（含 TURN 中继流量，前提是用 host 网络运行）。"""

from __future__ import annotations

import asyncio
import os
import time

import psutil

# 这些网卡不是真实的进出流量：回环、docker 网桥和容器虚拟网卡
VIRTUAL_NIC_PREFIXES = ("lo", "docker", "br-", "veth", "virbr")
SAMPLE_INTERVAL = 2.0


def _external_bytes() -> tuple[int, int]:
    sent = recv = 0
    for nic, counters in psutil.net_io_counters(pernic=True).items():
        if nic.lower().startswith(VIRTUAL_NIC_PREFIXES) or "loopback" in nic.lower():
            continue
        sent += counters.bytes_sent
        recv += counters.bytes_recv
    return sent, recv


class SystemMetrics:
    """后台定时采样，带宽和 CPU 都是最近一个采样周期的值，不会因为很久没人打开后台而被平均掉。"""

    def __init__(self) -> None:
        psutil.cpu_percent(None)  # 第一次调用只是建立基准
        self._sample = (time.monotonic(), *_external_bytes())
        self._rate = (0.0, 0.0)
        self._cpu = 0.0

    def sample(self) -> None:
        now = time.monotonic()
        sent, recv = _external_bytes()
        last_time, last_sent, last_recv = self._sample
        elapsed = now - last_time
        if elapsed > 0:
            self._rate = ((sent - last_sent) * 8 / elapsed, (recv - last_recv) * 8 / elapsed)
        self._sample = (now, sent, recv)
        self._cpu = psutil.cpu_percent(None)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE_INTERVAL)
            self.sample()

    def snapshot(self) -> dict:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        return {
            "cpu_percent": self._cpu,
            "cpu_count": psutil.cpu_count(),
            "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "mem_used": memory.total - memory.available,
            "mem_total": memory.total,
            "disk_used": disk.used,
            "disk_total": disk.total,
            "net_tx_bps": self._rate[0],
            "net_rx_bps": self._rate[1],
            "boot_time": psutil.boot_time(),
        }
