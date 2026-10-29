# -*- coding: utf-8 -*-
import os
import re
import operator
import sqlite3
import requests
from typing import Annotated, NotRequired, Sequence, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from tavily import TavilyClient

# ==========================================
# 1. 基础配置 (请替换为你真实的 Key)
# ==========================================
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")  # 去 tavily.com 免费注册获取，通过环境变量设置
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # Server酱/飞书/钉钉 Webhook，留空则跳过推送

os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"

# 初始化大模型和搜索引擎
llm = ChatOpenAI(model="deepseek-chat", temperature=0)
tavily = TavilyClient(api_key=TAVILY_API_KEY)


# ==========================================
# 2. 状态白板
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    resume_text: NotRequired[str]  # 接收前端传来的 PDF 文本
    job_requirements: NotRequired[str]
    resume_suggestions: NotRequired[str]
    match_score: NotRequired[int]
    action_plan: NotRequired[str]


# ==========================================
# 3. 真实数据库初始化（防重复投递）
# ==========================================
def init_db():
    conn = sqlite3.connect('job_history.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS apply_records 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, job_title TEXT UNIQUE, score INTEGER)''')
    conn.commit()
    conn.close()


def is_duplicate_job(job_title: str) -> bool:
    conn = sqlite3.connect('job_history.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM apply_records WHERE job_title = ?", (job_title,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_job_record(job_title: str, score: int):
    conn = sqlite3.connect('job_history.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO apply_records (job_title, score) VALUES (?, ?)", (job_title, score))
    conn.commit()
    conn.close()


# ==========================================
# 4. 真实工具：手机推送
# ==========================================
def send_real_webhook(title: str, content: str):
    if not WEBHOOK_URL:
        print("   [通知] 未配置 Webhook，跳过真实推送。")
        return
    print("   [通知] 正在发送推送到你的手机...")
    try:
        payload = {"msgtype": "text", "text": {"content": f"🚨【秋招AI助手】\n{title}\n\n{content}"}}
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"   [通知] 发送失败: {e}")


# ==========================================
# 5. 五大节点逻辑
# ==========================================
def scout_agent_node(state: AgentState) -> dict:
    user_input = state["messages"][-1].content
    print("\n🔍 [侦察兵] 正在接入 Tavily 进行全网真实岗位搜索...")

    context = ""
    try:
        # 给搜索加上超时和异常捕获
        search_res = tavily.search(query=f"{user_input} 招聘 职位描述", search_depth="basic", max_results=2)
        for r in search_res.get("results", []):
            context += f"标题: {r['title']}\n链接: {r['url']}\n摘要: {r['content']}\n---\n"
        print("   => 成功从互联网抓取到真实岗位信息！")
    except Exception as e:
        print(f"   [网络异常] Tavily 搜索失败: {e}")
        context = "网络搜索超时，未能获取最新岗位。请基于通用岗位要求进行分析。"

    return {"job_requirements": context, "messages": [AIMessage(content="已搜索到真实岗位")]}


def tailor_agent_node(state: AgentState) -> dict:
    print("\n✂️ [裁缝] 正在分析网页上传的 PDF 简历...")
    req = state.get("job_requirements") or ""
    resume = state.get("resume_text") or "未提供简历"

    prompt = f"真实岗位要求：\n{req}\n\n我的简历：\n{resume}\n\n请给出一条硬核的简历修改建议。"
    response = llm.invoke([HumanMessage(content=prompt)])
    print("   => 简历建议已生成。")
    return {"resume_suggestions": response.content, "messages": [response]}


def matcher_agent_node(state: AgentState) -> dict:
    print("\n⚖️ [评估员] 正在进行匹配度打分...")
    req = state.get("job_requirements") or ""
    resume = state.get("resume_text") or "未提供简历"

    prompt = f"岗位：{req}\n简历：{resume}\n\n请给出0-100的匹配分数，只输出数字，不要废话。"
    response = llm.invoke([HumanMessage(content=prompt)])
    match = re.search(r'\d+', response.content)
    score = int(match.group()) if match else 60
    print(f"   => 真实匹配分数: {score}")
    return {"match_score": score, "messages": [response]}


# 👇 就是这里，修改了低分时的策略
def scheduler_agent_node(state: AgentState) -> dict:
    print("\n🤖 [管家] 正在执行投递策略与跟进计划...")
    score = state["match_score"]
    req = state.get("job_requirements") or ""

    job_title = "未知岗位"
    if "标题: " in req:
        job_title = req.split("标题: ")[1].split("\n")[0]

    if is_duplicate_job(job_title):
        plan = f"⚠️ 岗位【{job_title}】已经在库中，已拦截重复投递！"
        print(f"   => {plan}")
    elif score >= 80:
        save_job_record(job_title, score)
        plan = f"🔥 **匹配度极高 ({score}分)！** 系统已自动为你记录【{job_title}】，建议立即投递！"
        print(f"   => {plan}")
        send_real_webhook(f"发现高匹配岗位：{job_title}",
                          f"匹配分数：{score}分\n建议：{state.get('resume_suggestions', '')[:50]}...")
    else:
        # 低分不再拦截，而是转化为“教练模式”
        plan = f"⚖️ **当前匹配度 ({score}分) 未达 80 分安全线。** 这个岗位可能竞争非常激烈。\n\n**策略建议**：不要气馁！这恰好是个好机会。请重点参考下方的【简历修改建议】补齐技术栈差距。你也可以先收藏该岗位，等准备好后再投递。"
        print(f"   => {plan}")

    return {"action_plan": plan, "messages": [AIMessage(content=plan)]}


def supervisor_node(state: AgentState) -> dict:
    return {}


def route_supervisor(state: AgentState) -> str:
    if not state.get("job_requirements"): return "scout"
    if not state.get("resume_suggestions"): return "tailor"
    if state.get("match_score") is None: return "matcher"
    if not state.get("action_plan"): return "scheduler"
    return END


# ==========================================
# 6. 组装图
# ==========================================
def build_app(api_key: str = None):
    global llm
    if api_key:
        llm = ChatOpenAI(model="deepseek-chat", temperature=0, api_key=api_key)

    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("scout", scout_agent_node)
    workflow.add_node("tailor", tailor_agent_node)
    workflow.add_node("matcher", matcher_agent_node)
    workflow.add_node("scheduler", scheduler_agent_node)

    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges("supervisor", route_supervisor)
    for node in ["scout", "tailor", "matcher", "scheduler"]:
        workflow.add_edge(node, "supervisor")

    return workflow.compile()