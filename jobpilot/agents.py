# -*- coding: utf-8 -*-
"""
JobPilot - 多智能体节点实现（侦察兵 / 裁缝 / 评估员 / 管家 / 主管）

铁律（LangGraph 最佳实践，v1 踩过的坑）：
- 节点 = 纯执行单元：只做自己的工作，返回 dict / 空 dict 更新白板
- 路由 = 独立纯函数 route_supervisor()，交给 add_conditional_edges
- 节点内任何外部依赖失败（LLM 超时 / 搜索挂 / RAG 不可用）都不允许让整张图崩溃：
  捕获后写进素材文本，流程继续 → 这就是“优雅降级”

依赖注入：所有节点通过 make_*_node(deps) 工厂闭包创建，测试可注入假 LLM /
假搜索 / 假 RAG / 临时数据库，全流程无需联网即可验证。
"""
from __future__ import annotations

import re
from typing import Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from jobpilot.models import JobSource
from jobpilot.state import AgentState

# ------------------------------------------------------------------
# 依赖集合（依赖注入的唯一入口）
# ------------------------------------------------------------------


class Deps:
    def __init__(
        self,
        *,
        llm,
        searcher=None,
        rag_factory: Callable[[], object] | None = None,
        storage=None,
        notifier=None,
        match_threshold: int = 80,
        max_resume_chars: int = 6000,
    ):
        self.llm = llm
        self.searcher = searcher            # 实现 search(query, top_k) -> list[JobSource]
        self.rag_factory = rag_factory      # () -> JobRAG 或 None（惰性构造，失败即降级）
        self.storage = storage              # Storage 或测试替身
        self.notifier = notifier
        self.match_threshold = match_threshold
        self.max_resume_chars = max_resume_chars


def _last_human_text(state: AgentState) -> str:
    """取最近一条用户消息；空输入返回空串而不是 IndexError。"""
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def _call_llm(deps: Deps, prompt: str) -> str:
    """统一的 LLM 出口：超时报错时抛出，由调用方决定降级文案。"""
    resp = deps.llm.invoke([HumanMessage(content=prompt)])
    if isinstance(resp, BaseMessage):
        return str(resp.content)
    return str(resp)

# ------------------------------------------------------------------
# 1. 侦察兵：本地 RAG + Tavily 实时搜索 → LLM 归纳岗位要求
# ------------------------------------------------------------------


def _rag_search(deps: Deps, intent: str, top_k: int = 3) -> tuple[list[JobSource], str]:
    """离线知识库检索。失败返回 (空列表, 说明文本)，绝不抛出。"""
    if deps.rag_factory is None:
        return [], "（未启用 RAG：跳过本地岗位库检索）"
    try:
        rag = deps.rag_factory()
        hits = rag.search(intent, top_k=top_k)
        if not hits:
            return [], "（RAG 未命中岗位，继续尝试实时搜索）"
        return hits, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"（RAG 检索不可用，已自动降级：{exc}）"


def _web_search(deps: Deps, intent: str, top_k: int = 3) -> tuple[list[JobSource], str]:
    """实时搜索。失败返回 (空列表, 说明文本)，绝不抛出。"""
    if deps.searcher is None:
        return [], "（未接入实时搜索）"
    try:
        hits = deps.searcher.search(intent, top_k=top_k)
        return hits, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"（实时搜索不可用，已自动降级：{exc}）"


def make_scout_node(deps: Deps):
    def scout_agent_node(state: AgentState) -> dict:
        intent = _last_human_text(state) or "（用户没有描述具体意向）"
        print("\n🔍 [侦察兵] 正在收集岗位情报（RAG 语义检索 + 实时搜索）...")

        rag_hits, rag_note = _rag_search(deps, intent)
        web_hits, web_note = _web_search(deps, intent)

        sources: list[JobSource] = list(rag_hits) + list(web_hits)

        # ---- 素材文本：RAG 与 Web 各自节选，交给 LLM 归纳 ----
        rag_text = rag_note or "（本地知识库无命中）"
        if rag_hits:
            rag_text = "\n".join(
                f"- 【{s.company} - {s.title} ({s.city})】{s.digest[:(400 if s.digest else 120)]}"
                for s in rag_hits
            )
        web_text = web_note or "（实时搜索无命中）"
        if web_hits:
            web_text = "\n".join(
                f"- 标题: {s.title}\n  链接: {s.url}\n  摘要: {s.digest[:220]}" for s in web_hits
            )

        prompt = (
            "你是求职侦察兵。用户求职意向：{intent}\n\n"
            "【本地岗位库命中（RAG）】\n{rag_text}\n\n"
            "【实时检索命中（Tavily）】\n{web_text}\n\n"
            "请输出三部分（markdown）：\n"
            "1. **核心岗位要求**：一句话归纳这类岗位最硬的 3-5 个要求（技术栈/城市/方向）；\n"
            "2. **岗位清单**：把上面命中里与你意向最相关的岗位列出来，每行格式"
            "『- 【公司】岗位（城市）』，最多 6 个；无命中就写『暂无高度匹配岗位』；\n"
            "3. **情报缺口**：当前还缺什么信息（比如具体薪资、投递渠道）。"
        ).format(intent=intent[:1000], rag_text=rag_text[:3000], web_text=web_text[:2500])

        try:
            analysis = _call_llm(deps, prompt)
        except Exception as exc:  # noqa: BLE001 —— LLM 挂了就用素材凑合
            analysis = (rag_text + "\n" + web_text)[:1200] or f"（情报归纳失败：{exc}）"

        return {
            "user_intent": intent[:2000],
            "job_sources": [s.to_dict() for s in sources][:12],
            "job_requirements": analysis,
            "rag_results": rag_text,
            "web_results": web_text,
            "messages": [AIMessage(content=f"🔍 侦察完毕：命中 {len(rag_hits)} 个本地岗位、{len(web_hits)} 条实时信息。")],
        }

    return scout_agent_node

# ------------------------------------------------------------------
# 2. 裁缝：简历 vs 岗位 → 精准修改建议
# ------------------------------------------------------------------


def make_tailor_node(deps: Deps):
    def tailor_agent_node(state: AgentState) -> dict:
        req = state.get("job_requirements") or "（岗位要求缺失，请先补充）"
        resume = (state.get("resume_text") or "").strip() or "（用户未上传简历，请基于通用情况给出建议，并提醒上传 PDF）"
        resume = resume[: deps.max_resume_chars]

        print("\n✂️ [裁缝] 正在逐条比对简历与岗位要求...")
        prompt = (
            "你是资深求职教练。岗位情报：\n{req}\n\n我的简历：\n{resume}\n\n"
            "请给出（markdown）：\n"
            "1. **三个硬核修改点**：针对该岗位要求，简历最该改/补的三处（技术栈、措辞、项目表述）；\n"
            "2. **一句话改写示例**：任选一条项目经历给出改写前后对照。"
        ).format(req=req[:3000], resume=resume[: deps.max_resume_chars])
        try:
            suggestion = _call_llm(deps, prompt)
        except Exception as exc:  # noqa: BLE001
            suggestion = f"（简历诊断暂不可用：{exc}）建议：突出与岗位要求直接相关的项目与技能。"

        return {
            "resume_suggestions": suggestion,
            "messages": [AIMessage(content="✂️ 简历诊断完成。")],
        }

    return tailor_agent_node

# ------------------------------------------------------------------
# 3. 评估员：匹配度量化打分（0-100）
# ------------------------------------------------------------------


def make_matcher_node(deps: Deps):
    def matcher_agent_node(state: AgentState) -> dict:
        req = state.get("job_requirements") or ""
        resume = (state.get("resume_text") or "").strip() or "（未上传简历）"
        resume = resume[: deps.max_resume_chars]

        print("\n⚖️ [评估员] 正在计算人岗匹配度...")
        prompt = (
            "你是招聘评估专家。岗位情报：{req}\n\n候选人简历：{resume}\n\n"
            "请只输出一个 0-100 的整数匹配分（不要任何解释、不要 markdown），"
            "评分依据：技术栈重合度 40%、项目经验匹配 30%、城市与方向 20%、其他加分 10%。"
        ).format(req=req[:3000], resume=resume)
        score = 60  # 默认分：解析失败时兜底，流程不中断
        try:
            text = _call_llm(deps, prompt)
            match = re.search(r"\d{1,3}", text)
            if match:
                score = max(0, min(100, int(match.group())))
        except Exception as exc:  # noqa: BLE001
            print(f"   [警告] 打分失败，使用默认分 {score}：{exc}")

        print(f"   => 匹配度：{score} 分")
        return {
            "match_score": score,
            "messages": [AIMessage(content=f"⚖️ 匹配度评分完成：{score}/100。")],
        }

    return matcher_agent_node

# ------------------------------------------------------------------
# 4. 管家：防重复投递 + 高匹配自动通知 + 教练模式
# ------------------------------------------------------------------


def _first_job_title(state: AgentState) -> str:
    for s in state.get("job_sources") or []:
        if s.get("title"):
            return s["title"][:80]
    return "自定义意向岗位"


def _first_job_company(state: AgentState) -> str:
    for s in state.get("job_sources") or []:
        if s.get("company"):
            return s["company"]
    return ""


def make_scheduler_node(deps: Deps):
    def scheduler_agent_node(state: AgentState) -> dict:
        score = int(state.get("match_score") or 0)
        title = _first_job_title(state)
        company = _first_job_company(state)

        print("\n🤖 [管家] 正在执行投递策略与跟进计划...")
        storage = deps.storage

        if storage is None:
            plan = f"💬 **当前匹配度 {score} 分（未接入投递记录库，跳过防重检查）**，建议自行判断是否投递【{title}】。"
            print(f"   => {plan}")
            return {"action_plan": plan, "messages": [AIMessage(content=plan)]}

        job_key = _record_job_key(storage, company, title)
        existing = storage.get_application(job_key) if hasattr(storage, "get_application") else None

        if existing is not None:
            # ---- 去重拦截 ----
            # 特例：之前只是“收藏/看板”，本轮简历改好了分数达标 → 自动升级为投递记录并推送
            if existing["status"] == "watchlist" and score >= deps.match_threshold:
                storage.update_application(job_key, status="applied", score=score)
                plan = (
                    f"📈 **【{title}】之前收藏在案，本轮匹配度已达 {score} 分！**\n\n"
                    "系统已自动把它从看板升级为正式投递记录，加油，现在就是投递窗口！"
                )
                if deps.notifier is not None:
                    deps.notifier.send(
                        f"收藏岗位升级：{title}",
                        f"匹配分数：{score} 分（此前在看板）\n建议：{state.get('resume_suggestions', '')[:50]}...",
                    )
                print(f"   => {plan}")
                return {"action_plan": plan, "messages": [AIMessage(content=plan)]}

            plan = (
                f"⚠️ **岗位【{title}】已在库中（{('已投递' if existing['status'] == 'applied' else '看板')}），"
                f"已拦截重复投递！**\n\n"
                "系统坚持『同一岗位只提醒一次』，避免手滑重复投递。"
                "如果简历有重大更新想重新评估，可以在侧边栏开启新会话，"
                "或到「投递记录」页清理该条记录。"
            )
            print(f"   => {plan}")
            return {"action_plan": plan, "messages": [AIMessage(content=plan)]}

        if score >= deps.match_threshold:
            created = storage.save_application(
                job_key, title, company=company, score=score, status="applied", source="auto"
            )
            plan = (
                f"🔥 **匹配度极高（{score} 分，阈值 {deps.match_threshold}）！**\n\n"
                f"系统已自动为你记录**【{title}】**，可立即投递。\n"
                f"• 简历要点：{state.get('resume_suggestions', '')[:80]}...\n"
                f"• 建议 24h 内完成投递，投递后可回来记录跟进状态。"
            )
            if deps.notifier is not None and created:
                deps.notifier.send(
                    f"发现高匹配岗位：{title}",
                    f"匹配分数：{score} 分\n建议：{state.get('resume_suggestions', '')[:50]}...",
                )
            print(f"   => {plan}")
        else:
            created = storage.save_application(
                job_key, title, company=company, score=score, status="watchlist", source="coach"
            )
            plan = (
                f"⚖️ **当前匹配度（{score} 分）未达 {deps.match_threshold} 分安全线**，"
                f"这个岗位可能竞争激烈。\n\n"
                f"**教练模式**：不要气馁！请重点参考上方【简历修改建议】补齐技能差距，"
                f"也可以先收藏该岗位（已收入看板），等准备好再投递。\n"
                f"> 记住：Agent 只负责建议，投不投由你决定。"
            )
            print(f"   => {plan}")

        return {"action_plan": plan, "messages": [AIMessage(content=plan)]}

    return scheduler_agent_node


def _record_job_key(storage, company: str, title: str) -> str:
    """优先复用存储层 key 生成；避免重复 import。"""
    try:
        from jobpilot.storage import make_job_key

        return make_job_key(company, title)
    except Exception:  # noqa: BLE001 —— 测试替身可能没有该函数
        return title

# ------------------------------------------------------------------
# 5. 主管：状态白板巡检（只读，不执行任务）
# ------------------------------------------------------------------


def make_supervisor_node(deps: Deps):  # noqa: ARG001 —— 保持节点工厂签名统一
    def supervisor_node(state: AgentState) -> dict:
        # 提炼本轮意图（纯字符串搬运，不调 LLM，零成本）。
        # 注意：分析字段的“每轮重置”不做在这里——那会让【调度完→回主管】的
        # 循环里反复清空白板，永远走不到 END。重置发生在 run_analysis() 的
        # 输入层（同一线程第二次调用时用 None 覆盖旧的分析产物），
        # 主管只负责记录意图，保持“只读巡检”的职责边界。
        intent = _last_human_text(state)
        if intent and state.get("user_intent") != intent[:2000]:
            return {"user_intent": intent[:2000]}
        return {}

    return supervisor_node


# ------------------------------------------------------------------
# 6. 路由大脑（纯函数：只读 state，返回目标节点名）
# ------------------------------------------------------------------


def route_supervisor(state: AgentState) -> str:
    from langgraph.graph import END

    if not state.get("job_requirements"):
        return "scout"          # 缺岗位情报 → 侦察兵出动
    if not state.get("resume_suggestions"):
        return "tailor"         # 缺简历诊断 → 裁缝出动
    if state.get("match_score") is None:
        return "matcher"        # 缺量化分 → 评估员出动
    if not state.get("action_plan"):
        return "scheduler"      # 缺行动计划 → 管家出动
    return END                   # 白板齐了 → 收工