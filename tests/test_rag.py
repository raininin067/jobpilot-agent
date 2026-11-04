# -*- coding: utf-8 -*-
"""RAG 引擎测试（注入假 embedder，不依赖真实模型 / 网络）。"""
import json

import pytest

from jobpilot.models import JobSource
from jobpilot.rag import JobRAG


class DummyEmbedder:
    """假向量模型：按公司名确定性返回向量，便于断言检索顺序。"""

    def encode(self, texts):
        out = []
        for t in texts:
            if "字节" in t:
                out.append([1.0, 0.0, 0.0])
            elif "腾讯" in t:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out


def _write_jobs(path):
    jobs = [
        {"id": "job_001", "company": "字节跳动", "title": "大模型应用开发实习生", "city": "上海",
         "requirements": "熟悉 Python，掌握 FastAPI，了解 RAG 与 LangGraph。"},
        {"id": "job_002", "company": "腾讯", "title": "AI Agent 研发工程师", "city": "深圳",
         "requirements": "精通 Python，理解 Function Calling。"},
    ]
    path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")


def test_seed_and_search(tmp_path):
    data = tmp_path / "jobs.json"
    _write_jobs(data)
    rag = JobRAG(data, embedder=DummyEmbedder(), persist_dir=str(tmp_path / "chroma"))
    assert rag._collection.count() == 2

    hits = rag.search("字节大模型岗位", top_k=1)
    assert len(hits) == 1
    assert hits[0].company == "字节跳动"
    assert hits[0].source == "rag"
    assert isinstance(hits[0], JobSource)


def test_seed_is_idempotent(tmp_path):
    data = tmp_path / "jobs.json"
    _write_jobs(data)
    rag = JobRAG(data, embedder=DummyEmbedder(), persist_dir=str(tmp_path / "chroma"))
    count_1 = rag._collection.count()
    rag2 = JobRAG(data, embedder=DummyEmbedder(), persist_dir=str(tmp_path / "chroma"))
    assert rag2._collection.count() == count_1 == 2


def test_reseeds_after_data_grows(tmp_path):
    data = tmp_path / "jobs.json"
    _write_jobs(data)
    rag = JobRAG(data, embedder=DummyEmbedder(), persist_dir=str(tmp_path / "chroma"))
    # 数据变成 3 条 → 集合数量不匹配 → 自动重建
    jobs = json.loads(data.read_text(encoding="utf-8"))
    jobs.append({"id": "job_003", "company": "阿里云", "title": "后端", "city": "杭州", "requirements": "Go"})
    data.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    rag2 = JobRAG(data, embedder=DummyEmbedder(), persist_dir=str(tmp_path / "chroma"))
    assert rag2._collection.count() == 3


def test_empty_returned_when_no_data(tmp_path):
    rag = JobRAG(tmp_path / "missing.json", embedder=DummyEmbedder())
    assert rag.search("anything") == []
    assert rag._collection.count() == 0


def test_missing_embedder_raises_helpful_error(tmp_path, monkeypatch):
    """没有装 sentence-transformers 时给出可操作提示（CI 环境无 [rag] extra）。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match=r"pip install -e '\.\[rag\]'"):
        JobRAG(tmp_path / "x.json", embed_model="BAAI/bge-small-zh-v1.5")