# -*- coding: utf-8 -*-
"""
JobPilot - 岗位 RAG 引擎（ChromaDB + bge-small-zh-v1.5）

本地岗位知识库的语义检索：
- 启动时把 data/jobs_data.json 的岗位文本向量化入库（幂等：数量一致就跳过）
- search() 按求职意向做余弦相似度检索，返回结构化岗位
- 与 Tavily 实时搜索互补：RAG 快、离线可用、结果稳定；Tavily 新、覆盖全网

注意：sentence-transformers / torch 体积较大，放在 pyproject 的 [rag] extra 里，
没有安装时本模块的 JobRAG 不可用，但工作流会自动降级为纯 Tavily / 纯 LLM 模式。
测试通过注入 fake embedder 覆盖检索逻辑，不依赖真实模型。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from jobpilot.models import JobSource


class JobRAG:
    def __init__(
        self,
        data_path: Path | str,
        *,
        embed_model: str = "BAAI/bge-small-zh-v1.5",
        top_k: int = 3,
        persist_dir: Path | str | None = None,
        embedder: object | None = None,
        chroma: object | None = None,
        distance: str = "cosine",
    ):
        """
        :param embedder: 测试注入的假 embedding 模型（必须实现 .encode(texts) -> list[list[float]]）
        :param chroma:   测试注入的 chromadb 客户端；不传则按 persist_dir 创建持久/内存客户端
        """
        import chromadb  # 延迟导入：保持包体轻量

        self.top_k = top_k
        self.embedder = embedder or self._load_embedder(embed_model)
        self.client = chroma or (
            chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.EphemeralClient()
        )
        self._collection = self.client.get_or_create_collection(name="jobs", metadata={"hnsw:space": distance})
        self._seed_if_needed(Path(data_path))

    # -------- 初始化 --------
    @staticmethod
    def _load_embedder(model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # 没装 [rag] extra
            raise RuntimeError(
                "未安装 sentence-transformers。请先执行：pip install -e '.[rag]'"
            ) from exc
        return SentenceTransformer(model_name)

    def _seed_if_needed(self, data_path: Path) -> None:
        """幂等入库：集合数量与 JSON 一致则跳过（支持增量后手动删目录重建）。"""
        jobs = self._load_jobs(data_path)
        if self._collection.count() == len(jobs):
            return
        try:
            self.client.delete_collection(name="jobs")
            self._collection = self.client.create_collection(name="jobs", metadata={"hnsw:space": "cosine"})
        except Exception:
            pass
        if not jobs:
            return
        self._collection.add(
            documents=[self._to_doc(j) for j in jobs],
            metadatas=[
                {"company": j["company"], "title": j["title"], "city": j["city"], "id": j["id"]}
                for j in jobs
            ],
            ids=[j["id"] for j in jobs],
        )

    @staticmethod
    def _load_jobs(data_path: Path) -> list[dict]:
        if not data_path.is_file():
            return []
        with data_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _to_doc(job: dict) -> str:
        return f"公司：{job['company']}。岗位：{job['title']}。城市：{job['city']}。要求：{job['requirements']}"

    # -------- 检索 --------
    def search(self, query: str, top_k: int | None = None) -> list[JobSource]:
        k = top_k or self.top_k
        if self._collection.count() == 0:
            return []
        hits = self._collection.query(query_texts=[query], n_results=min(k, self._collection.count()))
        results: list[JobSource] = []
        docs = (hits.get("documents") or [[]])[0]
        metas = (hits.get("metadatas") or [[]])[0]
        distances = (hits.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            results.append(
                JobSource(
                    title=meta.get("title", ""),
                    company=meta.get("company", ""),
                    city=meta.get("city", ""),
                    url="",
                    digest=doc,
                    source="rag",
                )
            )
        return results


_rag_cache: dict[str, JobRAG] = {}


def build_rag(settings) -> JobRAG:
    """线程内单例：Streamlit 多次 rerun / CLI 多次调用时避免反复加载 Embedding 模型。"""
    key = str(settings.chroma_dir)
    if key not in _rag_cache:
        _rag_cache[key] = JobRAG(
            settings.jobs_data_path,
            embed_model=settings.embed_model,
            top_k=settings.rag_top_k,
            persist_dir=settings.chroma_dir,
        )
    return _rag_cache[key]