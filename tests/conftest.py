# -*- coding: utf-8 -*-
"""
pytest 共享夹具：假 LLM / 假搜索 / 假 RAG / 临时数据库 —— 全流程零联网可测。

FakeLLM 按 prompt 关键词应答：
- 含「0-100」→ 返回 85（评估员分支）
- 含「简历」→ 返回裁缝建议 markdown
- 含「侦察兵」→ 返回岗位归纳 markdown
- 其他 → 通用兜底
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobpilot.config import Settings  # noqa: E402
from jobpilot.models import JobSource  # noqa: E402
from jobpilot.notify import NullNotifier  # noqa: E402
from jobpilot.storage import Storage  # noqa: E402


class FakeLLM:
    def __init__(self, score: str = "85"):
        self.score = score
        self.calls: list[str] = []

    def invoke(self, messages) -> object:
        from langchain_core.messages import AIMessage

        prompt = str(messages[-1].content)
        self.calls.append(prompt[:120])
        if "0-100" in prompt or "匹配分" in prompt:
            return AIMessage(content=self.score)
        if "简历" in prompt:
            return AIMessage(
                content="**三个硬核修改点**：\n1. 突出 RAG 项目\n2. 补充 FastAPI 关键词\n3. 量化成果\n\n**改写示例**：\n- 改前：做过问答系统\n- 改后：基于 ChromaDB 的 RAG 问答，检索延时 <200ms"
            )
        if "侦察兵" in prompt:
            return AIMessage(
                content="**核心岗位要求**：Python + RAG + LangGraph。\n\n**岗位清单**：\n- 【字节跳动】大模型应用开发实习生（上海）\n- 【腾讯】AI Agent 研发工程师（深圳）\n\n**情报缺口**：薪资、投递渠道。"
            )
        return AIMessage(content="收到，已处理。")


class FakeSearcher:
    def __init__(self, results: list[JobSource] | None = None):
        self._results = results or [
            JobSource(
                title="测试岗位-AI 应用实习生",
                company="测一测科技",
                url="https://example.com/job/1",
                digest="负责 AI 应用开发，要求 Python 与 LangGraph。",
                source="web",
            )
        ]

    def search(self, query: str, top_k: int = 3) -> list[JobSource]:
        return self._results[:top_k]


class FakeRAG:
    def __init__(self, results: list[JobSource] | None = None):
        self._results = results or [
            JobSource(
                title="大模型应用开发实习生",
                company="字节跳动",
                city="上海",
                digest="熟悉 Python，掌握 FastAPI，了解 RAG 与 LangGraph。",
                source="rag",
            )
        ]

    def search(self, query: str, top_k: int = 3) -> list[JobSource]:
        return self._results[:top_k]


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def searcher():
    return FakeSearcher()


@pytest.fixture
def rag():
    return FakeRAG()


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "test.db")


@pytest.fixture
def notifier():
    return NullNotifier()


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    (tmp_path / "jobs_data.json").write_text(
        '[{"id":"job_001","company":"字节跳动","title":"大模型应用开发实习生","city":"上海",'
        '"requirements":"熟悉 Python，了解 RAG 与 LangGraph。"}]',
        encoding="utf-8",
    )
    return s