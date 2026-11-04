# JobPilot-Agent 架构详解与面试讲解指南

> 本文回答两个问题：**系统怎么设计的？**（面试官想听的）和 **哪里是真正的技术难点？**（你能讲出细节的）。
> 全文对应 `jobpilot/` 包，每个结论都能在代码里指出来。

---

## 1. 为什么是「多智能体」而不是一个大 Prompt？

| 单 Prompt 大杂烩 | 多智能体流水线 |
|---|---|
| 一个上下文装下所有任务，互相干扰 | 每步职责单一，提示词短、输出稳 |
| 无法复用中间产物（岗位情报/简历诊断/分数） | 白板共享中间产物，可观测、可插拔 |
| 改需求 = 改巨型 prompt | 改需求 = 增删一个节点 |

本项目用 **LangGraph 状态图** 显式建模"哪一步需要什么、谁产出什么"：

- `StateGraph(AgentState)` 定义共享状态白板
- `add_node()` 定义每个 Agent 的行为
- `add_conditional_edges("supervisor", route_supervisor)` 实现**状态驱动的动态调度**
- `add_edge(node, "supervisor")` 保证每个 Agent 干完活都回主管报备

这是一张有向图，不是 if/else 长串：加 Agent 只加节点 + 路由分支，不动其他代码。

## 2. 状态白板：reducers 与「每轮重置」的坑

### operator.add（追加合并）

```python
messages: Annotated[Sequence[BaseMessage], operator.add]
```

`messages` 用 **追加** 策略：多个 Agent 都往 `messages` 里写，覆盖会丢信息，`operator.add` 让它们累积成完整对话历史 —— 这是**多轮记忆**的地基。

### ⚠️ checkpointer 引入后必须「输入层重置」（真实踩坑）

启用 `SqliteSaver` 后，同一线程的第二次调用会看到**上一轮填满的白板** —— 路由发现字段齐全，直接 `END`，第二轮什么都不干。这就是 v1 没有、v2 认真处理的难点。

两个候选方案：
1. ❌ 在主管节点里重置 → 主管位于循环内（`scheduler → supervisor`），重置后路由又去调 scout → **死循环**（实测：卡到 recursion_limit）
2. ✅ 在 `run_analysis()` 的 **inputs 层**用 `None` 覆盖分析字段 → 每一轮必从侦察兵重跑，`messages` 历史保留

```python
inputs = {
    "messages": [HumanMessage(content=query)],
    "job_requirements": None,          # 关键：输入层重置
    "match_score": None,
    ...,
}
```

面试答法：*「记忆在 messages，分析在白板字段；每轮调用时输入层把分析字段重置为 None，强制流水线按本轮意图重跑 —— 主管只负责巡检报备，不持有业务状态。」*

## 3. 路由：主管只读不写

- 节点 = 纯执行单元，只返回更新 dict（v1 曾把路由写在节点里直接 `return "scout"`，被 LangGraph 当成 state 更新抛 `InvalidUpdateError`）
- 路由 = 独立纯函数 `route_supervisor(state) -> str`，按四缺口返回节点名：
  `无岗位情报→scout / 无简历诊断→tailor / 无分数→matcher / 无计划→scheduler / 齐了→END`

## 4. 双通道检索与优雅降级（面试高频）

```
求职意向
   ├─ RAG 通道：ChromaDB + bge-small-zh-v1.5 本地岗位库（离线、秒级、结果稳定）
   └─ Web 通道：Tavily 实时搜索（新、覆盖全网、时效性强）
        ↓ LLM 归纳（岗位要求 / 岗位清单 / 情报缺口）
```

每一环都有兜底，**任何外部依赖失败都不崩图**：

| 故障 | 行为 |
|---|---|
| Tavily 未配置 / 超时 / 空结果 | `SearchUnavailable` → 自动降级为纯 RAG，素材里注明 |
| RAG 模型加载失败 | 捕获 → 跳过本地库，走纯实时 / LLM 归纳 |
| LLM 调用失败（余额/限流） | 侦察兵退回原始素材文本；评估员用默认分 60；流程继续 |
| SQLite 异常 | `run_analysis` 捕获写入 `_error`，UI/CLI 明确提示 |

面试答法：*「降级不是 if/else 堆的，是每个节点把外部调用包在 try 里、对外只承诺『返回素材或说明文本』—— 可靠性是设计出来的，不是补丁打出来的。」*

## 5. 防重复投递：SQLite 去重 + 看板升级

- `apply_records.job_key = sha1(公司|岗位)[:16]` 唯一约束 → **持久化去重**（set 只活在内存里，SQLite 重启不丢）
- 高匹配（≥80）→ 自动记为 `applied` + Webhook 推送
- 低匹配 → 记入看板（`watchlist`）+ **教练模式**建议（不否定用户，给成长路径 —— "Agent 建议，人类决策"）
- **升级路径**：看板岗位在后续轮次分数达标 → 自动升级为投递记录并补推送

## 6. 可测试性：依赖注入

所有节点通过工厂闭包 `make_scout_node(deps)` 创建，`Deps` 里全是接口：

```python
Deps(llm=..., searcher=..., rag_factory=..., storage=..., notifier=...)
```

测试注入 `FakeLLM`（按 prompt 关键字应答）/ `FakeSearcher` / `FakeRAG` / 临时 SQLite —— **41 个用例零联网**跑通：路由五分支、完整流水线、重复拦截、看板升级、低分教练、双通道降级、LLM 全挂兜底、多线程记忆隔离。CI（GitHub Actions，3.11/3.12 矩阵）每次 push 自动执行。

## 7. 记忆：SQLite checkpointer

- `SqliteSaver(conn)` 与业务库共用 `data/jobpilot.db`，对话 checkpoints 落盘 → 重启进程也不丢记忆
- 每条会话一个 `thread_id`；Web UI 每次"新会话"换新 ID
- 依赖装不上时自动降级 `MemorySaver`（单进程记忆）

## 8. 常见面试追问与参考回答

**Q1：LangGraph 和 LangChain 什么关系？**
LangChain 是工具箱（`ChatOpenAI`/`HumanMessage`/`AIMessage`），LangGraph 是编排引擎（状态图、条件边、checkpointer）。互补不替代。

**Q2：为什么 Tavily 而不是 Google 搜索 API？**
Tavily 返回结构化摘要（标题/URL/正文摘要），专为 LLM 上下文优化，一行 `client.search()`；Google Custom Search 返回 HTML 链接，还得自己解析爬取。

**Q3：Webhook 推送原理？**
反向 API：不是轮询，是系统主动 POST 到飞书/企业微信/Server酱的机器人地址，`{"msgtype":"text","text":{...}}`，5 行代码，不需要长连接和消息队列。

**Q4：如果多个 Agent 都要改同一个字段怎么办？**
看语义：`messages` 用 `operator.add` 追加（谁都不能覆盖谁的发言）；业务字段（`match_score` 等）语义是"最新一轮覆盖"，按设计每轮由输入层重置。

**Q5：怎么验证系统没写死？**
三个"如果"：如果 Tavily 挂了？（降级纯 RAG）如果 LLM 余额不足？（素材兜底+默认分，见第 4 节表）如果同岗位投两遍？（SQLite 唯一键拦截 + 看板升级逻辑）。

**Q6：项目规模 / 工作量怎么讲？**
v2 一次重构：`jobpilot` 包（配置/状态/五个 Agent/检索/存储/通知/工作流）+ Streamlit UI + CLI 扫描 + Docker + 41 个测试 + CI。核心难点在「checkpointer × 每轮重置」的状态一致性和「全链路优雅降级」。

## 9. 数据流一图流

```
用户输入(意向+简历PDF)
   │  run_analysis(query, resume_text, thread_id)
   ▼
[主管] 提炼 user_intent + 输入层重置白板
   ▼ route_supervisor
[侦察兵] RAG(top_k=3) + Tavily(max_results=3) → LLM 归纳 → job_requirements + job_sources
   ▼
[裁缝] 岗位要求 × 简历 → 三个硬核修改点 + 改写示例
   ▼
[评估员] 0-100 匹配分（技术栈40/项目30/城市方向20/其他10）→ match_score
   ▼
[管家] 查重 → 高匹配: applied+推送 / 低匹配: watchlist+教练模式 / 看板达标: 升级+推送
   ▼
保存 analysis_history → UI/CLI 渲染报告（Markdown 导出 / 趋势曲线 / 看板）
```