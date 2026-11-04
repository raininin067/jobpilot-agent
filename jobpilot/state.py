# -*- coding: utf-8 -*-
"""
JobPilot - AgentState（多 Agent 共享的“状态白板”）

设计要点
--------
- messages 用 Annotated[... , operator.add] 声明**追加合并**策略：
  多个 Agent（或同一 Agent 多轮）都可能往 messages 里写内容，
  覆盖会丢信息，追加才能积累成完整对话历史。
- 其余业务字段都是普通字段：默认**覆盖**策略。
  每轮“求职分析”都从零重新产出 job_requirements / resume_suggestions /
  match_score / action_plan，后轮覆盖前轮，保证结果始终对应当前轮输入；
  而 messages 会带着历史一起累积，形成多轮记忆。
"""
from typing import Annotated, NotRequired, Sequence, TypedDict

import operator

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ---- 对话层 ----
    messages: Annotated[Sequence[BaseMessage], operator.add]

    # ---- 输入层 ----
    user_intent: NotRequired[str]        # 用户本轮求职意向（主管提炼）
    resume_text: NotRequired[str]        # 简历文本（前端上传 PDF / 粘贴）

    # ---- 侦察兵产出 ----
    job_sources: NotRequired[list[dict]]  # 结构化岗位列表（UI 直接渲染卡片）
    job_requirements: NotRequired[str]   # 岗位要求分析文本（LLM 归纳）
    rag_results: NotRequired[str]        # 本地知识库命中的原始素材
    web_results: NotRequired[str]        # Tavily 实时搜索的原始素材

    # ---- 裁缝产出 ----
    resume_suggestions: NotRequired[str]  # 简历修改建议（markdown）

    # ---- 评估员产出 ----
    match_score: NotRequired[int]        # 0-100 匹配度

    # ---- 管家产出 ----
    action_plan: NotRequired[str]        # 投递策略 / 跟进计划