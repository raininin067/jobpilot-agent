# -*- coding: utf-8 -*-
"""JobPilot - 实时岗位搜索服务（Tavily 封装，带超时 / 重试 / 优雅降级）。"""
from __future__ import annotations

import time
from typing import Protocol

from jobpilot.models import JobSource


class SearchUnavailable(RuntimeError):
    """搜索服务不可用（未配置 Key / 网络异常 / 超时）。"""


class Searcher(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[JobSource]: ...


class TavilySearcher:
    """Tavily 实时搜索：面向 LLM 优化的结构化检索（标题 / 链接 / 摘要）。"""

    def __init__(self, api_key: str = "", *, timeout: float = 8.0, max_retries: int = 2):
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = None  # 惰性初始化，避免 import 阶段就联网

    # -------- 惰性建连 --------
    def _get_client(self):
        if self._client is None:
            from tavily import TavilyClient  # 延迟导入：无 Key 时连包都不用加载

            self._client = TavilyClient(api_key=self._api_key)
        return self._client

    def search(self, query: str, top_k: int = 3) -> list[JobSource]:
        if not self._api_key:
            raise SearchUnavailable("未配置 TAVILY_API_KEY，跳过实时搜索（降级为本地知识库）")

        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._get_client().search(
                    query=f"{query} 招聘 职位描述",
                    search_depth="basic",
                    max_results=top_k,
                )
                results = []
                for r in resp.get("results", []):
                    title = (r.get("title") or "").strip()
                    if not title:
                        continue
                    results.append(
                        JobSource(
                            title=title[:120],
                            company="",
                            city="",
                            url=(r.get("url") or "").strip(),
                            digest=(r.get("content") or "").strip()[:400],
                            source="web",
                        )
                    )
                if results:
                    return results
                raise SearchUnavailable("Tavily 返回空结果")
            except SearchUnavailable:
                raise
            except Exception as exc:  # 网络抖动/超时 → 重试
                last_err = exc
                if attempt < self._max_retries:
                    time.sleep(0.8 * (attempt + 1))
        raise SearchUnavailable(f"Tavily 搜索失败且重试 {self._max_retries} 次仍不可用: {last_err}") from last_err


class NullSearcher:
    """测试 / 离线场景用的空实现。"""

    def search(self, query: str, top_k: int = 3) -> list[JobSource]:
        raise SearchUnavailable("NullSearcher: 未接入任何搜索服务")