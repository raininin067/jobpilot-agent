# -*- coding: utf-8 -*-
"""
工作流测试：多智能体全流程（零联网）。
覆盖：路由分支、完整流水线、防重拦截、收藏升级、教练模式、优雅降级、多轮记忆、异常兜底。
"""
import sqlite3

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END
from langchain_core.messages import AIMessage, HumanMessage

from jobpilot.agents import Deps, route_supervisor
from jobpilot.search import SearchUnavailable
from jobpilot.storage import make_job_key
from jobpilot.workflow import build_graph, run_analysis


def _app(llm, searcher, rag, storage, notifier, threshold=80):
    deps = Deps(
        llm=llm,
        searcher=searcher,
        rag_factory=(lambda: rag),
        storage=storage,
        notifier=notifier,
        match_threshold=threshold,
    )
    return build_graph(deps, checkpointer=MemorySaver())


def _run(app, storage, query, thread="t1", **kw):
    return run_analysis(app, query=query, thread_id=thread, storage=storage, **kw)


# ------------------------------------------------------------------
# 路由纯函数
# ------------------------------------------------------------------

def test_route_branches():
    assert route_supervisor({}) == "scout"
    assert route_supervisor({"job_requirements": "x"}) == "tailor"
    assert route_supervisor({"job_requirements": "x", "resume_suggestions": "y"}) == "matcher"
    assert route_supervisor(
        {"job_requirements": "x", "resume_suggestions": "y", "match_score": 80}
    ) == "scheduler"
    assert route_supervisor(
        {"job_requirements": "x", "resume_suggestions": "y", "match_score": 80, "action_plan": "z"}
    ) == END


# ------------------------------------------------------------------
# 完整流水线
# ------------------------------------------------------------------

def test_full_pipeline(llm, searcher, rag, storage, notifier):
    app = _app(llm, searcher, rag, storage, notifier)
    result = _run(app, storage, "我想找上海的大模型实习")

    assert result["user_intent"] == "我想找上海的大模型实习"
    assert "大模型" in result["job_requirements"]          # 侦察兵：LLM 归纳
    assert "硬核修改点" in result["resume_suggestions"]      # 裁缝
    assert result["match_score"] == 85                       # 评估员
    assert "匹配度极高" in result["action_plan"]             # 管家：高匹配
    assert len(result["job_sources"]) == 2                   # RAG 1 + Web 1

    records = storage.list_applications()
    assert len(records) == 1 and records[0]["status"] == "applied"
    assert len(notifier.calls) == 1                          # 高匹配自动推送
    assert len(storage.list_history("t1")) == 1              # 历史落库


def test_scout_fills_metadata(llm, searcher, rag, storage, notifier):
    app = _app(llm, searcher, rag, storage, notifier)
    result = _run(app, storage, "找个实习")
    assert "字节跳动" in result["rag_results"]
    assert "example.com" in result["web_results"]
    sources = result["job_sources"]
    assert {s["source"] for s in sources} == {"rag", "web"}


# ------------------------------------------------------------------
# 防重复投递
# ------------------------------------------------------------------

def test_duplicate_interception(llm, searcher, rag, storage, notifier):
    app = _app(llm, searcher, rag, storage, notifier)
    _run(app, storage, "上海大模型实习", thread="t1")
    assert len(notifier.calls) == 1

    # 同一线程重跑同一意向 → 同岗位 → 管家拦截，不重复入库/推送
    result2 = _run(app, storage, "上海大模型实习", thread="t1")
    assert "拦截" in result2["action_plan"]
    assert len(storage.list_applications()) == 1
    assert len(notifier.calls) == 1


def test_watchlist_upgrade_when_score_reaches_threshold(llm, searcher, rag, storage, notifier):
    # 第一轮：低分 → 收藏在看板
    app = _app(FakeLLM(score="55"), searcher, rag, storage, notifier)
    result1 = _run(app, storage, "上海大模型实习", thread="t1")
    assert "教练模式" in result1["action_plan"]
    assert storage.list_applications()[0]["status"] == "watchlist"

    # 第二轮：简历改好了，分数达标 → 自动升级为投递并推送
    app2 = _app(llm, searcher, rag, storage, notifier)
    result2 = _run(app2, storage, "上海大模型实习", thread="t1")
    assert "升级" in result2["action_plan"]
    assert storage.list_applications()[0]["status"] == "applied"
    assert len(notifier.calls) == 1


# ------------------------------------------------------------------
# 教练模式（低分）
# ------------------------------------------------------------------

def test_low_score_coach_mode(llm, searcher, rag, storage, notifier):
    app = _app(FakeLLM(score="42"), searcher, rag, storage, notifier)
    result = _run(app, storage, "北京后端")
    assert "教练模式" in result["action_plan"]
    assert storage.list_applications()[0]["status"] == "watchlist"
    assert notifier.calls == []                              # 低分不推送


def test_score_parse_fallback_to_default(llm, searcher, rag, storage, notifier):
    app = _app(FakeLLM(score="完全没数字"), searcher, rag, storage, notifier)
    result = _run(app, storage, "随便看看")
    assert result["match_score"] == 60                       # 默认分兜底，流程不中断


# ------------------------------------------------------------------
# 优雅降级
# ------------------------------------------------------------------

def test_degraded_when_search_and_rag_fail(llm, rag, storage, notifier):
    class BrokenSearcher:
        def search(self, query, top_k=3):
            raise SearchUnavailable("Tavily 挂掉了")

    def broken_rag_factory():
        raise RuntimeError("Embedding 模型加载失败")

    deps = Deps(llm=llm, searcher=BrokenSearcher(), rag_factory=broken_rag_factory,
                storage=storage, notifier=notifier)
    app = build_graph(deps, checkpointer=MemorySaver())
    result = _run(app, storage, "上海大模型实习")

    assert "_error" not in result                         # 流程没崩
    assert "降级" in result["rag_results"]                # RAG 降级说明
    assert "降级" in result["web_results"]                # 搜索降级说明
    assert result["match_score"] == 85                    # 其余 Agent 照常工作


def test_llm_failure_falls_back_to_raw_material(searcher, rag, storage, notifier):
    class BrokenLLM:
        def invoke(self, messages):
            raise RuntimeError("模型超时")

    deps = Deps(llm=BrokenLLM(), searcher=searcher, rag_factory=(lambda: rag),
                storage=storage, notifier=notifier)
    app = build_graph(deps, checkpointer=MemorySaver())
    result = _run(app, storage, "找实习")

    assert "_error" not in result
    assert "字节跳动" in result["job_requirements"]       # 退化为原始素材文本
    assert result["match_score"] == 60                    # 默认分
    assert result["action_plan"]                          # 教练计划仍生成


def test_storage_failure_reports_error(searcher, rag):
    class BrokenStorage:
        def list_applications(self, limit=100):
            return []

        def get_application(self, job_key):
            return None

        def is_duplicate(self, job_key):
            raise sqlite3.OperationalError("db locked")

    class N:
        calls = []

        def send(self, *a, **k):
            return True

    deps = Deps(llm=FakeLLM(), searcher=searcher, rag_factory=(lambda: rag),
                storage=BrokenStorage(), notifier=N())
    app = build_graph(deps, checkpointer=MemorySaver())
    result = run_analysis(app, query="找实习", thread_id="t1", storage=None)
    assert "_error" in result                             # 异常被捕获并上报，不裸崩


# ------------------------------------------------------------------
# 多轮记忆（checkpointer）
# ------------------------------------------------------------------

def test_same_thread_keeps_memory(llm, searcher, rag, storage, notifier):
    app = _app(llm, searcher, rag, storage, notifier)
    _run(app, storage, "上海大模型实习", thread="m1")
    result2 = _run(app, storage, "那深圳的 AI Agent 呢", thread="m1")

    # 主管识别到的是最新意图；messages 里累积了历史对话
    assert result2["user_intent"] == "那深圳的 AI Agent 呢"
    snap = app.get_state({"configurable": {"thread_id": "m1"}})
    msgs = snap.values.get("messages") or []
    assert len(msgs) >= 8                                  # 2 轮 × (1 用户 + 4 Agent)
    assert any(isinstance(m, HumanMessage) and "上海大模型实习" in str(m.content) for m in msgs)


def test_different_threads_isolated(llm, searcher, rag, storage, notifier):
    app = _app(llm, searcher, rag, storage, notifier)
    _run(app, storage, "问题一", thread="a1")
    result = _run(app, storage, "问题二", thread="a2")
    assert result["user_intent"] == "问题二"
    snap = app.get_state({"configurable": {"thread_id": "a2"}})
    assert len((snap.values.get("messages") or [])) == 5   # 全新线程：只有本轮 5 条


# ------------------------------------------------------------------
# 本地 FakeLLM（含可控分数）
# ------------------------------------------------------------------

class FakeLLM:
    def __init__(self, score: str = "85"):
        self.score = score

    def invoke(self, messages):
        prompt = str(messages[-1].content)
        if "0-100" in prompt or "匹配分" in prompt:
            return AIMessage(content=self.score)
        if "简历" in prompt:
            return AIMessage(content="**三个硬核修改点**：\n1. 突出 RAG 项目\n2. 量化成果\n\n**改写示例**：改前/改后对照。")
        if "侦察兵" in prompt:
            return AIMessage(content="**核心岗位要求**：Python + RAG + LangGraph。\n\n**岗位清单**：\n- 【字节跳动】大模型应用开发实习生（上海）\n\n**情报缺口**：薪资。")
        return AIMessage(content="收到。")