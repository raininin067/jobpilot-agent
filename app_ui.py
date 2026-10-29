# -*- coding: utf-8 -*-
"""
JobPilot 智能秋招护航 —— Streamlit 前端（美化版）

运行：
    streamlit run app_ui.py

改动说明：
    - 动态渐变星空背景 + 毛玻璃卡片，纯 CSS 实现，不依赖任何图片资源
    - 结果写进 session_state，改侧边栏配置 / 重新运行不会把结果刷掉
    - 抓到的岗位按「标题 / 链接 / 摘要」解析成卡片，不再是一大坨文本框
    - 支持导出 Markdown 报告
"""

import io
import os
import re
from datetime import datetime

# ⚠️ 必须在 import job_agent 之前设置：
# job_agent.py 在模块顶层就构造了 ChatOpenAI，没有 key 会直接抛 OpenAIError，
# 导致页面还没渲染就崩了。这里先放一个占位符，真正调用时 build_app(api_key=...) 会重建。
os.environ.setdefault("OPENAI_API_KEY", os.getenv("DEEPSEEK_API_KEY") or "sk-placeholder-not-used")

import streamlit as st
from langchain_core.messages import HumanMessage
from pypdf import PdfReader

from job_agent import build_app, init_db

# ==========================================
# 1. 页面配置
# ==========================================
st.set_page_config(
    page_title="JobPilot · 智能秋招护航",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

AGENTS = [
    ("🔍", "侦察兵", "全网检索真实岗位"),
    ("✂️", "裁缝", "对比诊断你的简历"),
    ("⚖️", "评估员", "匹配度量化打分"),
    ("🤖", "管家", "投递与跟进计划"),
]

NODE_STATUS = {
    "scout":     ("🔍", "侦察兵正在全网检索真实岗位…"),
    "tailor":    ("✂️", "裁缝正在逐条对比你的简历…"),
    "matcher":   ("⚖️", "评估员正在计算匹配度…"),
    "scheduler": ("🤖", "管家正在排投递与跟进节奏…"),
}

# ==========================================
# 2. 样式：动态渐变背景 + 毛玻璃
# ==========================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700;900&display=swap');

/* 覆盖主题变量，浅色主题下也不会黑底黑字 */
:root, .stApp {
  --primary-color: #A78BFA;
  --background-color: #070B16;
  --secondary-background-color: #101733;
  --text-color: #E6ECFB;
}

html, body, [class*="css"], .stApp {
  font-family: 'Noto Sans SC', -apple-system, 'Segoe UI', sans-serif;
}

/* ---------- 背景：三层径向光 + 深色底，固定不随滚动 ---------- */
.stApp {
  background:
    radial-gradient(900px 520px at 6% -8%,  rgba(124,108,246,.55), transparent 62%),
    radial-gradient(820px 500px at 98% 2%,  rgba(34,211,238,.42), transparent 60%),
    radial-gradient(780px 620px at 52% 110%, rgba(236,72,153,.36), transparent 64%),
    linear-gradient(155deg, #070B16 0%, #0F1630 42%, #080D1A 100%);
  background-attachment: fixed;
}

/* 背景网格：缓慢漂移 */
.stApp::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 54px 54px;
  mask-image: radial-gradient(circle at 50% 22%, #000 0%, transparent 76%);
  -webkit-mask-image: radial-gradient(circle at 50% 22%, #000 0%, transparent 76%);
  animation: jp-drift 28s linear infinite;
}
@keyframes jp-drift { from { background-position: 0 0, 0 0; } to { background-position: 54px 54px, 54px 54px; } }

/* 右下角呼吸光斑 */
.stApp::after {
  content: "";
  position: fixed; z-index: 0; pointer-events: none;
  width: 46vw; height: 46vw; right: -12vw; bottom: -16vw;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(124,108,246,.34), transparent 66%);
  filter: blur(46px);
  animation: jp-breathe 14s ease-in-out infinite alternate;
}
@keyframes jp-breathe { from { transform: scale(1); opacity: .75; } to { transform: scale(1.16); opacity: 1; } }

/* 内容浮在背景之上 */
.main .block-container { position: relative; z-index: 1; padding-top: 2.2rem; max-width: 1180px; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

/* 正文颜色（浅色主题兜底） */
[data-testid="stAppViewContainer"] { color: #E6ECFB; }
.stMarkdown p, .stMarkdown li, .stMarkdown h1, .stMarkdown h2,
.stMarkdown h3, .stMarkdown h4, .stMarkdown strong { color: #E6ECFB; }
[data-testid="stCaptionContainer"], .stCaption, small { color: #8E9BBB !important; }
label, [data-testid="stWidgetLabel"] p { color: #C7D0E8 !important; }

/* ---------- 侧边栏 ---------- */
section[data-testid="stSidebar"] {
  background: rgba(9,13,26,.84);
  backdrop-filter: blur(22px) saturate(140%);
  border-right: 1px solid rgba(255,255,255,.08);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.1); }

/* ---------- 通用毛玻璃卡片 ---------- */
.jp-card {
  background: rgba(255,255,255,.055);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 22px;
  padding: 20px 24px;
  backdrop-filter: blur(18px) saturate(150%);
  box-shadow: 0 18px 48px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.14);
  margin-bottom: 14px;
}
.jp-card h3 { margin: 0 0 10px 0; font-size: 1.02rem; color: #E9EFFD; letter-spacing: .3px; }
.jp-card p  { margin: 0; color: #A7B3D1; font-size: .88rem; line-height: 1.7; }

/* ---------- 顶部 Hero ---------- */
.jp-hero {
  position: relative; overflow: hidden;
  padding: 34px 38px 30px;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(124,108,246,.22), rgba(34,211,238,.14) 55%, rgba(236,72,153,.16));
  border: 1px solid rgba(255,255,255,.14);
  box-shadow: 0 26px 70px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.18);
  backdrop-filter: blur(18px);
  margin-bottom: 22px;
}
.jp-hero::before {
  content: ""; position: absolute; width: 320px; height: 320px; right: -90px; top: -140px;
  background: radial-gradient(circle, rgba(34,211,238,.55), transparent 68%);
  filter: blur(30px);
}
.jp-badge {
  display: inline-block; padding: 5px 14px; margin-bottom: 14px;
  border-radius: 999px; font-size: .72rem; letter-spacing: 1.6px; text-transform: uppercase;
  color: #C9D4FF; background: rgba(124,108,246,.22); border: 1px solid rgba(167,139,250,.45);
}
.jp-hero h1 {
  margin: 0; font-size: clamp(30px, 4vw, 50px); font-weight: 900; line-height: 1.15; letter-spacing: -.5px;
  background: linear-gradient(96deg, #C4B5FD 0%, #22D3EE 52%, #F472B6 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.jp-hero p { margin: 12px 0 0; color: #AEBBD9; font-size: .96rem; max-width: 760px; line-height: 1.75; }

/* ---------- Agent 卡片条 ---------- */
.jp-agent {
  border-radius: 18px; padding: 16px 18px; height: 100%;
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.11);
  backdrop-filter: blur(14px);
  transition: transform .22s ease, border-color .22s ease;
}
.jp-agent:hover { transform: translateY(-4px); border-color: rgba(167,139,250,.55); }
.jp-agent .ico  { font-size: 1.35rem; }
.jp-agent .name { margin-top: 8px; font-weight: 700; color: #EDF2FF; font-size: .95rem; }
.jp-agent .desc { margin-top: 4px; color: #8E9BBB; font-size: .78rem; }

/* ---------- 指标 ---------- */
[data-testid="stMetric"] {
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 22px; padding: 20px 22px;
  backdrop-filter: blur(16px);
  box-shadow: 0 16px 40px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.12);
}
[data-testid="stMetricValue"] {
  font-size: 3rem !important; font-weight: 900 !important; line-height: 1.05;
  background: linear-gradient(120deg, #22D3EE, #A78BFA 70%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
[data-testid="stMetricLabel"] { color: #A9B4D0 !important; letter-spacing: .4px; }

/* ---------- 输入框 / 按钮 ---------- */
.stTextInput input, .stTextArea textarea {
  background: rgba(255,255,255,.06) !important;
  border: 1px solid rgba(255,255,255,.14) !important;
  border-radius: 14px !important;
  color: #E8EEFC !important;
}
[data-testid="stChatInput"] {
  border-radius: 20px !important;
  background: rgba(255,255,255,.07) !important;
  border: 1px solid rgba(255,255,255,.16) !important;
  box-shadow: 0 14px 40px rgba(0,0,0,.45), 0 0 0 1px rgba(124,108,246,.18);
  backdrop-filter: blur(14px);
}
[data-testid="stChatInput"] textarea { color: #EAF0FF !important; }
[data-testid="stChatInput"] textarea::placeholder { color: #7C89AB !important; }

.stButton > button, .stDownloadButton > button {
  border-radius: 14px !important;
  border: none !important;
  padding: .55rem 1.1rem !important;
  font-weight: 700 !important;
  color: #08101F !important;
  background: linear-gradient(120deg, #A78BFA, #22D3EE) !important;
  box-shadow: 0 12px 28px rgba(124,108,246,.32);
  transition: transform .18s ease, filter .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-2px); filter: brightness(1.08); }

/* ---------- 展开面板 ---------- */
div[data-testid="stExpander"] {
  border-radius: 18px !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  background: rgba(255,255,255,.045);
  backdrop-filter: blur(12px);
}
div[data-testid="stExpander"] summary { color: #DCE4FA; font-weight: 600; }

/* ---------- 进度条 ---------- */
.stProgress > div > div > div > div {
  background: linear-gradient(90deg, #7C6CF6, #22D3EE);
  border-radius: 999px;
}

/* ---------- 聊天气泡 ---------- */
[data-testid="stChatMessage"] {
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 20px;
  padding: 14px 18px;
  backdrop-filter: blur(12px);
}

/* ---------- 提示框改成半透明 ---------- */
div[data-testid="stAlert"] {
  border-radius: 16px;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,.14);
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ==========================================
# 3. 小组件
# ==========================================
def hero() -> None:
    st.markdown(
        """
        <div class="jp-hero">
          <div class="jp-badge">LangGraph · Multi-Agent · DeepSeek</div>
          <h1>智能秋招护航系统</h1>
          <p>四个 Agent 接力干活：侦察兵全网扒岗位 → 裁缝逐条对简历 → 评估员量化打分 → 管家排投递节奏。
             你只需要说清楚想找什么。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def agent_ribbon() -> None:
    cols = st.columns(4)
    for col, (icon, name, desc) in zip(cols, AGENTS):
        with col:
            st.markdown(
                f'<div class="jp-agent"><div class="ico">{icon}</div>'
                f'<div class="name">{name}</div><div class="desc">{desc}</div></div>',
                unsafe_allow_html=True,
            )


def parse_pdf(uploaded) -> str:
    """把上传的 PDF 解析成文本，失败返回空串。"""
    try:
        reader = PdfReader(io.BytesIO(uploaded.read()))
        text = "".join((page.extract_text() or "") for page in reader.pages)
        return text[:2000].strip()
    except Exception as exc:                                   # noqa: BLE001
        st.error(f"解析失败：{exc}")
        return ""


def parse_jobs(raw: str) -> list[dict]:
    """把侦察兵返回的 `标题/链接/摘要` 文本切成结构化岗位列表。"""
    jobs = []
    for block in raw.split("---"):
        block = block.strip()
        if not block:
            continue
        title = re.search(r"标题[:：]\s*(.+)", block)
        url = re.search(r"链接[:：]\s*(\S+)", block)
        digest = re.search(r"摘要[:：]\s*([\s\S]+)", block)
        if title or url:
            jobs.append({
                "title": (title.group(1).strip() if title else "未命名岗位")[:80],
                "url": url.group(1).strip() if url else "",
                "digest": (digest.group(1).strip() if digest else "")[:360],
            })
    return jobs


def build_report(result: dict, query: str) -> str:
    return (
        f"# JobPilot 求职分析报告\n\n"
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"- 求职意向：{query}\n"
        f"- 匹配度：{result.get('match_score', '-')} 分\n\n"
        f"## 抓取到的岗位\n\n{result.get('job_requirements', '暂无')}\n\n"
        f"## 行动计划\n\n{result.get('action_plan', '暂无')}\n\n"
        f"## 简历修改建议\n\n{result.get('resume_suggestions', '暂无')}\n"
    )


# ==========================================
# 4. 侧边栏：配置与文件上传
# ==========================================
with st.sidebar:
    st.markdown("### 🎓 JobPilot")
    st.caption("LangGraph 多智能体 · 求职护航")

    st.markdown("---")
    st.markdown("#### 🔑 API 配置")
    api_key_input = st.text_input(
        "DeepSeek API Key", type="password", placeholder="sk-...",
        help="只在本次会话内存中使用，不会写进源码。",
    )
    if api_key_input:
        st.success("已就绪", icon="✅")
    else:
        st.caption("未配置 → 无法调用模型")

    st.markdown("---")
    st.markdown("#### 📄 个人简历（可选）")
    uploaded_file = st.file_uploader("上传 PDF 简历以获得精准建议", type=["pdf"])
    resume_text = ""
    if uploaded_file is not None:
        resume_text = parse_pdf(uploaded_file)
        if resume_text:
            st.success(f"简历已就绪（{len(resume_text)} 字）", icon="📎")
        else:
            st.warning("没读到文字，可能是扫描件")

    st.markdown("---")
    st.markdown("#### 💡 试试这些")
    examples = [
        "我想找上海的大模型实习",
        "北京 · 后端开发 · Go",
        "深圳 · 数据分析实习",
    ]
    for i, text in enumerate(examples):
        if st.button(text, key=f"ex_{i}", use_container_width=True):
            st.session_state["pending_query"] = text

    st.markdown("---")
    st.caption("侦察兵走 Tavily 实时检索；无网络时自动降级为模型归纳。")


# ==========================================
# 5. 主界面
# ==========================================
hero()
agent_ribbon()
st.write("")

pending = st.session_state.pop("pending_query", None)
user_query = st.chat_input("输入你的求职意向，例如：我想找上海的大模型实习…") or pending

if not api_key_input and not user_query:
    st.info("👈 请先在左侧配置 DeepSeek API Key，然后在下方开始对话。")

if user_query:
    if not api_key_input:
        st.error("⚠️ 请先在左侧输入 API Key！")
    else:
        os.environ["DEEPSEEK_API_KEY"] = api_key_input
        with st.chat_message("user"):
            st.write(user_query)

        with st.chat_message("assistant"):
            app = build_app(api_key=api_key_input)
            inputs = {
                "messages": [HumanMessage(content=user_query)],
                "resume_text": resume_text or "用户暂未上传简历，请基于通用情况给出建议，并提醒用户上传PDF以获得更精准的分析。",
            }

            status_line = st.empty()
            progress_bar = st.progress(0)
            final_state: dict = {}
            step_count = 0

            try:
                with st.status("Agent 团队开始工作…", expanded=False) as status:
                    for step in app.stream(inputs, config={"recursion_limit": 15}):
                        for node_name, update in step.items():
                            step_count += 1
                            if node_name in NODE_STATUS:
                                icon, text = NODE_STATUS[node_name]
                                status_line.markdown(f"**{icon} {text}**")
                                status.write(f"{icon} {node_name} 完成")
                            if update:
                                final_state.update(update)
                            progress_bar.progress(min(step_count * 11, 100))
                    status.update(label="分析完成 ✅", state="complete")
                status_line.empty()
                progress_bar.empty()
            except Exception as exc:                            # noqa: BLE001
                status_line.empty()
                progress_bar.empty()
                st.error(f"运行失败：{exc}")
                st.stop()

            st.session_state["result"] = final_state
            st.session_state["query"] = user_query

result = st.session_state.get("result")
query = st.session_state.get("query", "")

if result:
    score = int(result.get("match_score") or 0)
    st.markdown("---")

    col1, col2 = st.columns([1, 2], gap="large")
    with col1:
        st.metric(label="🎯 岗位综合匹配度", value=f"{score} 分")
        if score >= 80:
            st.success("🔥 极度匹配，建议直接投递！")
            st.balloons()
        elif score >= 60:
            st.warning("⚖️ 匹配度中等，需优化简历。")
        else:
            st.error("❌ 匹配度较低，请重点补强。")

    with col2:
        st.markdown('<div class="jp-card"><h3>🤖 管家行动计划</h3>', unsafe_allow_html=True)
        st.markdown(result.get("action_plan") or "暂无计划")
        st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    with st.expander("📝 简历修改建议（求职教练）", expanded=True):
        st.markdown(result.get("resume_suggestions") or "暂无建议")

    raw_jobs = result.get("job_requirements") or ""
    jobs = parse_jobs(raw_jobs)
    with st.expander(f"💼 为你抓到的真实岗位（{len(jobs)}）", expanded=False):
        if jobs:
            for job in jobs:
                link = f"[{job['title']}]({job['url']})" if job["url"] else job["title"]
                st.markdown(f'<div class="jp-card"><p><strong>{link}</strong></p>'
                            f'<p>{job["digest"] or "（无摘要）"}</p></div>', unsafe_allow_html=True)
            st.caption("链接来自实时检索结果，点击前请自行甄别真伪。")
        else:
            st.text_area("岗位详情", value=raw_jobs, height=220, disabled=True)

    st.write("")
    d1, d2 = st.columns([1, 3])
    with d1:
        st.download_button(
            "⬇️ 导出 Markdown 报告",
            data=build_report(result, query),
            file_name=f"jobpilot_{datetime.now():%Y%m%d_%H%M}.md",
            mime="text/markdown",
            use_container_width=True,
        )
