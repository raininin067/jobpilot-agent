# -*- coding: utf-8 -*-
"""
JobPilot - SQLite 持久化层

三张表：
- apply_records    投递/收藏记录（job_key 唯一 → 天然去重，防重复投递）
- analysis_history 每轮求职分析的评分快照（供“历史趋势”曲线与分数对比）
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path


def open_connection(db_path: Path | str) -> sqlite3.Connection:
    """打开一个普通 sqlite3 连接（供 LangGraph SqliteSaver 等外部组件接管生命周期）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path), check_same_thread=False)


def make_job_key(company: str, title: str) -> str:
    """同一家公司+同一个岗位 = 同一条记录（SHA1 16 位，避免超长/特殊字符）。"""
    raw = f"{company}|{title}".strip("|")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16] if raw else "unknown"


class Storage:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    # -------- DDL --------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS apply_records (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key    TEXT UNIQUE NOT NULL,
                    job_title  TEXT NOT NULL,
                    company    TEXT DEFAULT '',
                    score      INTEGER DEFAULT 0,
                    status     TEXT NOT NULL CHECK (status IN ('applied', 'watchlist')),
                    source     TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id  TEXT NOT NULL,
                    query      TEXT NOT NULL,
                    score      INTEGER DEFAULT 0,
                    plan       TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
                """
            )

    # -------- 投递记录（去重核心） --------
    def is_duplicate(self, job_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM apply_records WHERE job_key = ?", (job_key,)
            ).fetchone()
            return row is not None

    def save_application(
        self,
        job_key: str,
        job_title: str,
        *,
        company: str = "",
        score: int = 0,
        status: str = "applied",
        source: str = "",
    ) -> bool:
        """插入一条记录；已存在则忽略。返回是否真正插入。"""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO apply_records (job_key, job_title, company, score, status, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job_key, job_title, company, score, status, source),
            )
            return cur.rowcount > 0

    def list_applications(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apply_records ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_application(self, job_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM apply_records WHERE job_key = ?", (job_key,)
            ).fetchone()
            return dict(row) if row else None

    def update_application(self, job_key: str, *, status: str, score: int) -> bool:
        """升级既有记录（如：收藏 → 已投递）。返回是否有行被更新。"""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE apply_records SET status = ?, score = ? WHERE job_key = ?",
                (status, score, job_key),
            )
            return cur.rowcount > 0

    def clear_applications(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM apply_records")
            return cur.rowcount

    # -------- 分析历史（趋势曲线） --------
    def save_analysis(self, thread_id: str, query: str, score: int, plan: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_history (thread_id, query, score, plan) VALUES (?, ?, ?, ?)",
                (thread_id, query[:500], int(score or 0), plan),
            )

    def list_history(self, thread_id: str | None = None, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            if thread_id:
                rows = conn.execute(
                    "SELECT * FROM analysis_history WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                    (thread_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def last_score(self, thread_id: str | None = None) -> int | None:
        """上一轮评分（用于“较上次变化”展示）；无记录返回 None。"""
        with self._connect() as conn:
            if thread_id:
                row = conn.execute(
                    "SELECT score FROM analysis_history WHERE thread_id = ?"
                    " AND score IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (thread_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT score FROM analysis_history WHERE score IS NOT NULL"
                    " ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return int(row["score"]) if row else None

    # -------- 辅助 --------
    @staticmethod
    def now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")