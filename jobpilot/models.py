# -*- coding: utf-8 -*-
"""JobPilot - 数据模型（岗位 / 投递记录）。"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class JobSource:
    """一条岗位信息：来自 RAG 本地知识库或 Tavily 实时搜索。"""

    title: str
    company: str = ""
    city: str = ""
    url: str = ""
    digest: str = ""
    source: str = "unknown"  # "rag" | "web"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApplyRecord:
    """一条投递 / 收藏记录（持久化到 SQLite）。"""

    job_key: str
    job_title: str
    company: str
    score: int
    status: str  # "applied" | "watchlist"
    source: str = ""
    created_at: str = ""