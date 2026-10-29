# 🧭 JobPilot-Agent — 基于 LangGraph 的多智能体秋招护航系统

> 多 Agent 协作的智能求职助手：简历优化 → 岗位匹配 → 求职规划 → 自动投递追踪，一站式秋招护航。

## ✨ 特性

- **多智能体协作**：LangGraph 编排多个专家 Agent（简历分析师、岗位搜索官、职业规划师）
- **RAG 岗位检索**：基于 ChromaDB 的语义岗位搜索
- **实时搜索**：Tavily 搜索引擎获取最新岗位信息
- **防重复投递**：SQLite 本地记录投递历史
- **精美 UI**：Streamlit 动态渐变星空背景 + 毛玻璃卡片
- **报告导出**：支持导出 Markdown 求职报告

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| Agent 编排 | LangGraph（StateGraph） |
| 大模型 | DeepSeek（ChatOpenAI 兼容接口）|
| RAG 引擎 | ChromaDB + BGE-Small-ZH 向量模型 |
| 搜索 | Tavily API |
| 前端 | Streamlit |
| 数据库 | SQLite（投递记录）|

## 📂 项目结构

```
JobPilot-Agent/
├── .streamlit/
│   └── config.toml    # Streamlit 主题配置
├── job_agent.py       # 核心：多 Agent 编排（LangGraph）
├── rag_engine.py      # RAG 岗位检索引擎
├── app_ui.py          # Streamlit 前端
├── resume.txt         # 示例简历
├── jobs_data.json     # 岗位数据（RAG 用）
├── .gitignore
└── .env.example       # 环境变量模板
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install langgraph langchain-openai langchain-core \
    streamlit chromadb sentence-transformers \
    tavily-python pypdf requests
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`：

```env
# DeepSeek API Key（必填）
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# Tavily 搜索 API Key（可选，去 tavily.com 免费注册）
TAVILY_API_KEY=tvly-your-key-here

# Server酱推送 Webhook（可选，留空跳过）
WEBHOOK_URL=
```

### 3. 启动

```bash
streamlit run app_ui.py
```

### 4. 使用流程

1. 📄 **上传简历** — 上传 PDF 或粘贴文本
2. 🔍 **智能分析** — Agent 自动评估简历并给出优化建议
3. 💼 **岗位匹配** — RAG 搜索 + 实时爬取匹配的岗位
4. 📋 **生成计划** — 输出一份完整的求职行动计划

## 🏗 Agent 工作流

```
简历输入 → [简历分析Agent] → 优化建议
                              ↓
                        [岗位搜索Agent] → 匹配岗位列表
                              ↓
                        [规划Agent] → 求职行动计划
                              ↓
                        [投递Agent] → 记录投递历史
```

###5.📸 效果截图
<img width="2559" height="1337" alt="image" src="https://github.com/user-attachments/assets/f2855c8b-1cdc-45ad-b49f-062d1909b783" />

