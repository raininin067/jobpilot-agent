# -*- coding: utf-8 -*-
"""
JobPilot - 工作流组装（LangGraph 状态图）

- build_graph(deps)：注入依赖 → 组装 5 节点 + 条件路由的有向图
- build_default_app(settings, thread_id)：零配置入口，接线真实 LLM / 搜索 /
  RAG（惰性）/ SQLite 存储 / Webhook 通知，并挂上持久化 checkpointer

记忆机制（本轮新增）：
  SqliteSaver 把每轮对话的 messages 落盘到 data/jobpilot.db。
  同一 thread_id 下的多次调用共享对话历史 —— 你可以追问
  “上次是哪个岗位最高分？”而无需重新粘贴大段上下文。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from jobpilot import agents, storage as storage_mod
from jobpilot.agents import Deps
from jobpilot.config import Settings
from jobpilot.state import AgentState

logger = logging.getLogger(__name__)

NODE_ORDER = ["supervisor", "scout", "tailor", "matcher", "scheduler"]


@dataclass
class RunInput:
    """一次求职分析的输入。"""

    query: str
    resume_text: str = ""
    thread_id: str = "default"


def build_graph(deps: Deps, *, checkpointer=None):
    """
    组装状态机。checkpointer 传入即启用持久化记忆：
    - SqliteSaver(db_path) → 跨进程/跨重启记忆
    - MemorySaver()      → 仅进程内记忆（测试常用）
    """
    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", agents.make_supervisor_node(deps))
    workflow.add_node("scout", agents.make_scout_node(deps))
    workflow.add_node("tailor", agents.make_tailor_node(deps))
    workflow.add_node("matcher", agents.make_matcher_node(deps))
    workflow.add_node("scheduler", agents.make_scheduler_node(deps))

    workflow.set_entry_point("supervisor")
    # 条件路由：主管按状态缺口动态调度，任务完成后回到主管 → 再查缺口
    workflow.add_conditional_edges(
        "supervisor",
        agents.route_supervisor,
        {"scout": "scout", "tailor": "tailor", "matcher": "matcher", "scheduler": "scheduler", END: END},
    )
    for node in ["scout", "tailor", "matcher", "scheduler"]:
        workflow.add_edge(node, "supervisor")

    return workflow.compile(checkpointer=checkpointer)


def _make_llm(settings: Settings, api_key: str | None = None):
    """ChatOpenAI 兼容 DeepSeek；显式传 key/base_url，不依赖隐式环境变量。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.deepseek_model,
        temperature=settings.deepseek_temperature,
        api_key=api_key or settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


def _make_searcher(settings: Settings):
    from jobpilot.search import TavilySearcher

    return TavilySearcher(api_key=settings.tavily_api_key)


def _make_rag_factory(settings: Settings):
    """惰性 RAG 工厂：返回可调用对象，首次调用才加载 Embedding 模型。"""
    def factory():
        from jobpilot.rag import build_rag  # 延迟 import，避免拖慢启动

        return build_rag(settings)

    return factory


def build_default_app(
    settings: Settings,
    *,
    api_key: str | None = None,
    thread_id: str = "default",
    checkpointer=None,
):
    """
    零配置入口：按 Settings 接好所有真实依赖并返回 (compiled_app, storage)。
    带 checkpointer（默认 SQLite 持久化），同一 thread_id 不丢记忆。
    """
    llm = _make_llm(settings, api_key)
    searcher = _make_searcher(settings)
    rag_factory = _make_rag_factory(settings)
    storage = storage_mod.Storage(settings.db_path)
    from jobpilot.notify import WebhookNotifier

    notifier = WebhookNotifier(settings.webhook_url)

    if checkpointer is None:
        checkpointer = _make_checkpointer(settings)

    deps = Deps(
        llm=llm,
        searcher=searcher,
        rag_factory=rag_factory,
        storage=storage,
        notifier=notifier,
        match_threshold=settings.match_threshold,
    )
    app = build_graph(deps, checkpointer=checkpointer)
    return app, storage


def _make_checkpointer(settings: Settings):
    """优先 SQLite 持久化，装不上则退化为进程内 MemorySaver。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver(conn=storage_mod.open_connection(settings.db_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite checkpointer 不可用，降级为 MemorySaver：%s", exc)
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


def run_analysis(
    app,
    *,
    query: str,
    resume_text: str = "",
    thread_id: str = "default",
    storage=None,
    on_step=None,
) -> dict:
    """
    执行一轮完整分析（主管 → 侦察 → 裁缝 → 评估 → 管家 → 结束）。

    :param on_step: 回调 (node_name, update) → None，UI 用它渲染实时进度
    :return: 最终状态白板
    """
    inputs = {
        "messages": [HumanMessage(content=query)],
        "resume_text": resume_text or "（用户未上传简历）",
        # ---- 每轮重置分析产物（关键！）----
        # checkpointer 会在同一线程里保留上一轮填满的白板；如果不在这里用 None
        # 覆盖，路由看到字段齐全会直接 END，第二轮起什么都干不了。
        # 重置放在输入层而不是主管节点：主管位于循环内部（干完活要回主管复查），
        # 若在主管里重置会形成“重置→重跑→再重置”的死循环。
        "job_requirements": None,
        "resume_suggestions": None,
        "match_score": None,
        "action_plan": None,
        "job_sources": None,
        "rag_results": None,
        "web_results": None,
    }
    config = {"configurable": {"thread_id": thread_id}}
    final_state: dict = {}
    try:
        for step in app.stream(inputs, config=config, stream_mode="updates"):
            for node_name, update in step.items():
                if on_step:
                    on_step(node_name, update or {})
                if update:
                    final_state.update(update)
    except Exception as exc:  # noqa: BLE001 —— UI/CLI 都不该被裸异常打断
        final_state["_error"] = str(exc)

    if storage is not None and final_state.get("match_score") is not None:
        storage.save_analysis(
            thread_id,
            query,
            int(final_state["match_score"]),
            final_state.get("action_plan", ""),
        )
    return final_state


def format_report(result: dict, query: str, *, app_name: str = "JobPilot") -> str:
    """把状态白板渲染成 Markdown 求职报告（UI 导出 / CLI 输出共用）。"""
    from datetime import datetime

    return (
        f"# {app_name} 求职分析报告\n\n"
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"- 求职意向：{query}\n"
        f"- 匹配度：{result.get('match_score', '-')} 分\n\n"
        f"## 岗位情报\n\n{result.get('job_requirements', '暂无')}\n\n"
        f"## 简历修改建议\n\n{result.get('resume_suggestions', '暂无')}\n\n"
        f"## 行动计划\n\n{result.get('action_plan', '暂无')}\n"
    )