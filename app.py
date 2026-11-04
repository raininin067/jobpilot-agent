# -*- coding: utf-8 -*-
"""
JobPilot 智能秋招护航 —— Streamlit 前端

运行：
    streamlit run app.py

功能：
    - 动态渐变星空背景 + 毛玻璃卡片（纯 CSS，零图片依赖）
    - 四 Agent 接力实时进度展示
    - LangGraph SQLite checkpointer：同一会话多轮追问不丢记忆
    - 投递记录看板 + 历史趋势曲线 + Markdown 报告导出
"""
import io
import os
import uuid
from datetime import datetime

import streamlit as st
from langchain_core.messages import HumanMessage

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

from jobpilot.config import Settings  # noqa: E402
from jobpilot.storage import Storage, make_job_key  # noqa: E402
from jobpilot.workflow import build_default_app, format_report, run_analysis  # noqa: E402

# ==========================================
# 1. 页面配置 / 全局设置
# ==========================================
st.set_page_config(
    page_title="JobPilot · 智能秋招护航",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
DEFAULT_THREAD = "web-main"


def _thread_id() -> str:
    return st.session_state.get("thread_id", DEFAULT_THREAD)


AGENTS = [
    ("🔍", "侦察兵", "本地 RAG + 全网实时检索"),
    ("✂️", "裁缝", "逐条对比诊断简历"),
    ("⚖️", "评估员", "匹配度量化打分"),
    ("🤖", "管家", "防重投递 + 跟进计划"),
]

NODE_STATUS = {
    "scout": ("🔍", "侦察兵正在收集岗位情报（RAG 语义检索 + 实时搜索）…"),
    "tailor": ("✂️", "裁缝正在逐条比对简历与岗位…"),
    "matcher": ("⚖️", "评估员正在计算匹配度…"),
    "scheduler": ("🤖", "管家正在排投递与跟进节奏…"),
}

# ==========================================
# 2. 样式（动态渐变背景 + 毛玻璃）
# ==========================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700;900&display=swap');

:root, .stApp {
  --primary-color: #A78BFA;
  --background-color: #070B16;
  --secondary-background-color: #101733;
  --text-color: #E6ECFB;
}

html, body, [class*="css"], .stApp { font-family: 'Noto Sans SC', -apple-system, 'Segoe UI', sans-serif; }

.stApp {
  background:
    radial-gradient(900px 520px at 6% -8%,  rgba(124,108,246,.55), transparent 62%),
    radial-gradient(820px 500px at 98% 2%,  rgba(34,211,238,.42), transparent 60%),
    radial-gradient(780px 620px at 52% 110%, rgba(236,72,153,.36), transparent 64%),
    linear-gradient(155deg, #070B16 0%, #0F1630 42%, #080D1A 100%);
  background-attachment: fixed;
}

.stApp::before {
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 54px 54px;
  mask-image: radial-gradient(circle at 50% 22%, #000 0%, transparent 76%);
  -webkit-mask-image: radial-gradient(circle at 50% 22%, #000 0%, transparent 76%);
  animation: jp-drift 28s linear infinite;
}
@keyframes jp-drift { from { background-position: 0 0, 0 0; } to { background-position: 54px 54px, 54px 54px; } }

.stApp::after {
  content: ""; position: fixed; z-index: 0; pointer-events: none;
  width: 46vw; height: 46vw; right: -12vw; bottom: -16vw;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(124,108,246,.34), transparent 66%);
  filter: blur(46px);
  animation: jp-breathe 14s ease-in-out infinite alternate;
}
@keyframes jp-breathe { from { transform: scale(1); opacity: .75; } to { transform: scale(1.16); opacity: 1; } }

.main .block-container { position: relative; z-index: 1; padding-top: 2.2rem; max-width: 1180px; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

[data-testid="stAppViewContainer"] { color: #E6ECFB; }
.stMarkdown p, .stMarkdown li, .stMarkdown h1, .stMarkdown h2,
.stMarkdown h3, .stMarkdown h4, .stMarkdown strong { color: #E6ECFB; }
[data-testid="stCaptionContainer"], .stCaption, small { color: #8E9BBB !important; }
label, [data-testid="stWidgetLabel"] p { color: #C7D0E8 !important; }

section[data-testid="stSidebar"] {
  background: rgba(9,13,26,.84);
  backdrop-filter: blur(22px) saturate(140%);
  border-right: 1px solid rgba(255,255,255,.08);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.1); }

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

div[data-testid="stExpander"] {
  border-radius: 18px !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  background: rgba(255,255,255,.045);
  backdrop-filter: blur(12px);
}
div[data-testid="stExpander"] summary { color: #DCE4FA; font-weight: 600; }

.stProgress > div > div > div > div {
  background: linear-gradient(90deg, #7C6CF6, #22D3EE);
  border-radius: 999px;
}

[data-testid="stChatMessage"] {
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 20px;
  padding: 14px 18px;
  backdrop-filter: blur(12px);
}

div[data-testid="stAlert"] {
  border-radius: 16px;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,.14);
}

[data-testid="stDataFrame"] { border: 1px solid rgba(255,255,255,.1); border-radius: 16px; overflow: hidden; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 8px; }
[data-testid="stTabs"] [data-baseweb="tab"] {
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 12px !important;
  padding: 6px 18px;
  color: #C7D0E8 !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
  background: linear-gradient(120deg, rgba(124,108,246,.35), rgba(34,211,238,.25)) !important;
  color: #fff !important;
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
          <div class="jp-badge">LangGraph · Multi-Agent · RAG · DeepSeek</div>
          <h1>智能秋招护航系统</h1>
          <p>四个 Agent 接力干活：侦察兵（本地 RAG + 全网实时）扒岗位 → 裁缝逐条对简历 → 评估员量化打分 →
             管家排投递节奏。你说清楚想找什么，剩下的交给团队。</p>
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
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(uploaded.read()))
        text = "".join((page.extract_text() or "") for page in reader.pages)
        return text[:6000].strip()
    except Exception as exc:  # noqa: BLE001
        st.error(f"解析失败：{exc}")
        return ""


def build_report(result: dict, query: str) -> str:
    return format_report(result, query)

# ==========================================
# 4. 侧边栏：配置 / 简历 / 会话控制
# ==========================================
with st.sidebar:
    st.markdown("### 🎓 JobPilot")
    st.caption("LangGraph 多智能体 · 求职护航 v2")

    st.markdown("---")
    st.markdown("#### 🔑 API 配置")
    env_ready = settings.has_llm_key()
    if env_ready:
        st.success("已从 .env 读取 DeepSeek Key", icon="🔐")
        api_key_input = ""
    else:
        api_key_input = st.text_input(
            "DeepSeek API Key", type="password", placeholder="sk-...",
            help="只在本次会话内存中使用，不会写入任何文件。",
        )
        if api_key_input:
            st.success("已就绪", icon="✅")
        else:
            st.caption("未配置 → 无法调用模型；也可在项目根目录 .env 里配置")

    real_key = api_key_input or settings.deepseek_api_key

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
    st.markdown("#### 🧠 会话记忆")
    st.caption(f"当前会话 ID：`{_thread_id()[:12]}…` —— 同一会话内可追问“上次哪个最高分”，记忆不丢。")
    if st.button("🔄 开启新会话", use_container_width=True):
        st.session_state["thread_id"] = f"web-{uuid.uuid4().hex[:8]}"
        st.session_state.pop("result", None)
        st.rerun()

    st.markdown("---")
    st.markdown("#### 💡 试试这些")
    examples = [
        "我想找上海的大模型实习",
        "北京 · 后端开发 · Go",
        "深圳 · AI Agent 方向",
    ]
    for i, text in enumerate(examples):
        if st.button(text, key=f"ex_{i}", use_container_width=True):
            st.session_state["pending_query"] = text

    st.markdown("---")
    st.caption("RAG 离线知识库 + Tavily 实时搜索双通道；任一通道挂掉自动降级，流程不中断。")

# ==========================================
# 5. 主界面
# ==========================================
hero()
agent_ribbon()
st.write("")

tab_analysis, tab_records, tab_trend = st.tabs(["🎯 求职分析", "📁 投递记录", "📈 历史趋势"])

storage = Storage(settings.db_path)
stored = st.session_state.get("result")
stored_query = st.session_state.get("query", "")

# ---------------- Tab 1：求职分析 ----------------
with tab_analysis:
    pending = st.session_state.pop("pending_query", None)
    user_query = st.chat_input("输入你的求职意向，例如：我想找上海的大模型实习…") or pending

    if not real_key and user_query is None:
        st.info("👈 请先在左侧配置 DeepSeek API Key（或配置 .env），然后在下方开始对话。")

    if user_query:
        if not real_key:
            st.error("⚠️ 请先配置 API Key！")
        else:
            with st.chat_message("user"):
                st.write(user_query)

            with st.chat_message("assistant"):
                app, app_storage = build_default_app(
                    settings, api_key=real_key, thread_id=_thread_id()
                )
                st.session_state["storage"] = app_storage

                # 展示记忆：同一会话之前的轮次
                try:
                    snap = app.get_state({"configurable": {"thread_id": _thread_id()}})
                    prior = snap.values.get("messages") or []
                    human_msgs = [m for m in prior if isinstance(m, HumanMessage)] if prior else []
                    if len(human_msgs) > 1:
                        st.caption(f"🧠 已带上会话记忆（此前共 {len(human_msgs) - 1} 轮追问）")
                except Exception:  # noqa: BLE001 —— 记忆展示失败不影响主流程
                    pass

                status_line = st.empty()
                progress_bar = st.progress(0)
                node_count = 0

                def on_step(node_name: str, update: dict) -> None:
                    nonlocal node_count
                    node_count += 1
                    if node_name in NODE_STATUS:
                        icon, text = NODE_STATUS[node_name]
                        status_line.markdown(f"**{icon} {text}**")
                    progress_bar.progress(min(node_count * 11, 100))

                final_state = {}
                try:
                    with st.status("Agent 团队开始工作…", expanded=False) as status:
                        final_state = run_analysis(
                            app,
                            query=user_query,
                            resume_text=resume_text,
                            thread_id=_thread_id(),
                            storage=app_storage,
                            on_step=on_step,
                        )
                        if final_state.get("_error"):
                            status.update(label="运行失败，已降级处理", state="error")
                        else:
                            status.update(label="分析完成 ✅", state="complete")
                except Exception as exc:  # noqa: BLE001
                    status_line.empty()
                    progress_bar.empty()
                    st.error(f"运行失败：{exc}")
                    st.stop()
                status_line.empty()
                progress_bar.empty()

                st.session_state["result"] = final_state
                st.session_state["query"] = user_query
                st.rerun()

    result = st.session_state.get("result")
    if not result:
        st.write("")
        st.caption("输入求职意向后，四个 Agent 会接力产出：岗位情报 → 简历建议 → 匹配分数 → 行动计划。")

    if result:
        if result.get("_error"):
            st.warning(f"流程部分降级：{result['_error']}（结果可能不完整，但未中断）")
        score = int(result.get("match_score") or 0)
        prev = storage.last_score(thread_id=None)  # 上一轮任意会话的分数（用于“较上次”）
        delta = (score - prev) if prev is not None else None

        st.markdown("---")
        col1, col2 = st.columns([1, 2], gap="large")
        with col1:
            if delta is not None:
                st.metric(label="🎯 岗位综合匹配度", value=f"{score} 分", delta=f"{delta:+d} vs 上次")
            else:
                st.metric(label="🎯 岗位综合匹配度", value=f"{score} 分")
            if score >= settings.match_threshold:
                st.success(f"🔥 极度匹配（≥{settings.match_threshold}），建议直接投递！")
                st.balloons()
            elif score >= 60:
                st.warning("⚖️ 匹配度中等，参考裁缝建议优化简历。")
            else:
                st.error("❌ 匹配度较低，请重点补强。")

        with col2:
            st.markdown('<div class="jp-card"><h3>🤖 管家行动计划</h3>', unsafe_allow_html=True)
            st.markdown(result.get("action_plan") or "暂无计划")
            st.markdown("</div>", unsafe_allow_html=True)

        st.write("")
        with st.expander("📝 简历修改建议（求职教练）", expanded=True):
            st.markdown(result.get("resume_suggestions") or "暂无建议")

        jobs = result.get("job_sources") or []
        with st.expander(f"💼 为你匹配的岗位（{len(jobs)}）", expanded=False):
            if jobs:
                for i, job in enumerate(jobs):
                    title = job.get("title") or "未命名岗位"
                    company = job.get("company") or "全网岗位"
                    city = job.get("city") or ""
                    source = job.get("source", "unknown")
                    badge = "📚 本地知识库" if source == "rag" else "🌐 实时搜索" if source == "web" else source
                    link = f"[{title}]({job['url']})" if job.get("url") else title
                    head = f"<p><strong>{link}</strong>　<span style='color:#8E9BBB;font-size:.8rem'>{company} {city} · {badge}</span></p>"
                    st.markdown(f'<div class="jp-card">{head}<p>{job.get("digest") or "（暂无摘要）"}</p></div>',
                                unsafe_allow_html=True)
                    job_key = make_job_key(company, title)
                    if not storage.is_duplicate(job_key):
                        if st.button("📌 收藏到看板", key=f"fav_{i}_{job_key}"):
                            storage.save_application(
                                job_key, title, company=company,
                                score=score, status="watchlist", source="manual",
                            )
                            st.success("已收藏，可在「投递记录」页查看", icon="✅")
                st.caption("链接来自实时检索结果，点击前请自行甄别真伪。")
            else:
                st.text_area("岗位情报原文", value=result.get("job_requirements") or "暂无", height=220, disabled=True)

        st.write("")
        d1, d2 = st.columns([1, 3])
        with d1:
            st.download_button(
                "⬇️ 导出 Markdown 报告",
                data=build_report(result, stored_query or user_query or ""),
                file_name=f"jobpilot_{datetime.now():%Y%m%d_%H%M}.md",
                mime="text/markdown",
                use_container_width=True,
            )

# ---------------- Tab 2：投递记录 ----------------
with tab_records:
    rows = storage.list_applications()
    st.markdown(f"#### 📁 投递 / 收藏记录（{len(rows)} 条）")
    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)[["created_at", "status", "job_title", "company", "score", "source"]]
        df.columns = ["时间", "状态", "岗位", "公司", "匹配分", "来源"]
        df["状态"] = df["状态"].map({"applied": "🔥 已投递", "watchlist": "📌 看板"})
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        c1, c2 = st.columns([1, 3])
        with c1:
            st.download_button("⬇️ 导出 CSV", data=csv, file_name="jobpilot_records.csv", mime="text/csv")
        with c2:
            if st.button("🗑 清空记录", use_container_width=True):
                storage.clear_applications()
                st.rerun()
    else:
        st.info("暂无记录 —— 高匹配岗位会自动入库；也可以手动收藏岗位。")

# ---------------- Tab 3：历史趋势 ----------------
with tab_trend:
    hist = storage.list_history(limit=100)
    st.markdown("#### 📈 每轮分析的匹配度曲线")
    if hist:
        scores = [h["score"] for h in reversed(hist)]
        queries = [h["query"][:20] for h in reversed(hist)]
        st.line_chart({"匹配度": scores})
        with st.expander("🗒 明细", expanded=False):
            import pandas as pd

            hdf = pd.DataFrame(reversed(hist))[["created_at", "query", "score"]]
            hdf.columns = ["时间", "意向", "匹配分"]
            st.dataframe(hdf, use_container_width=True, hide_index=True)
        st.caption(f"最近一次：{hist[0]['created_at']} · “{hist[0]['query'][:30]}” · {hist[0]['score']} 分")
    else:
        st.info("暂无历史 —— 跑一轮分析后这里会出现评分曲线。")