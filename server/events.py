"""事件记录：谁在什么时候分享、观看、离开、被拒绝，存进 SQLite 给后台查看。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

MAX_EVENTS = 20_000  # 只保留最近这么多条，够看几个月
PRUNE_EVERY = 500
COLUMNS = ("ts", "kind", "room", "name", "ip", "detail")


class EventLog:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 只在事件循环线程里访问，但创建时可能在别的线程（比如测试客户端）
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,"
            " room TEXT, name TEXT, ip TEXT, detail TEXT)"
        )
        self.db.commit()
        self._writes = 0

    def add(self, kind: str, *, room: str = "", name: str = "", ip: str = "", detail: str = "") -> None:
        self.db.execute(
            "INSERT INTO events (ts, kind, room, name, ip, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), kind, room, name, ip, detail),
        )
        self._writes += 1
        if self._writes % PRUNE_EVERY == 0:
            self.db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (MAX_EVENTS,))
        self.db.commit()

    def recent(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts, kind, room, name, ip, detail FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip(COLUMNS, row)) for row in rows]

    def close(self) -> None:
        self.db.close()


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"
