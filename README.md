# AgentMall · 可恢复的 Agent 工作流与事务电商

AgentMall 将**模型建议、可恢复工作流和确定性交易**分开：Agent 可以检索商品、组合方案、处理售后意图并准备提案；只有用户独立确认后，服务端才重新校验权限、商品版本和库存，提交业务事务。

**FastAPI · Python 3.12 · LangGraph · PostgreSQL 17 / pgvector · React / TypeScript · MCP**

**V2.14 产品已合并 main，Ubuntu 24.04 x86_64 离线 CI 全部通过。** 产品基线为 [`59f84ebb…`](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/commit/59f84ebbfdfb1d87287ad6c4ae83a1748183d30c)；[main CI / Attempt 1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42770031624) 的 Backend、Frontend 和 Release Gate 均为 success。这不是生产部署或真实 LLM 可靠性认证。本轮发布文档更新仍是待审核的本地提交；`v2.14.0` 只是建议版本号，尚无正式 Tag / GitHub Release。

[一页式介绍](docs/PORTFOLIO_ONE_PAGE.md) · [无Key Demo](docs/PORTFOLIO_DEMO.md) · [架构](docs/ARCHITECTURE.md) · [面试深挖](docs/PORTFOLIO_INTERVIEW.md) · [main CI原件核验](docs/evidence/v214-r4/report.md) · [Release Notes草稿](docs/RELEASE_NOTES_v2.14.0.md)

## 工程能力

| 能力 | 实现与边界 |
|---|---|
| Single / Multi-Agent | LangGraph Supervisor 按实际目标路由 Shopping、Order、AfterSales；服务端验证任务依赖、当前意图、工具批次和实体引用。Multi 不保证优于 Single。 |
| 交易与 HITL | 不可变 Proposal → 独立 Confirmation → Resume；多 SKU 订单、全部库存预留、确认消费和幂等回执同事务提交。批准购买不授权付款或退款。 |
| 多轮 Bundle | 13品类 / 120个合成SKU；2–5品类组合、整数分总预算、版本化候选及增量重规划。旧方案须重新核价验库存。 |
| Durable Worker | Legacy Sync 与显式 Durable Async 并存；PostgreSQL任务、Thread advisory lock、Epoch Fence、Journal和官方Checkpoint协调恢复。不是通用Exactly-Once。 |
| SSE进度 | fetch流读取已提交RunEvent，按seq补读/去重；JWT在内存和Authorization头中，重连不会重新下单或自动批准。 |
| 商家运营 | 本店订单/售后、合成资料导入、草稿审核发布和显式索引状态；Copilot只读分析，不代替商家执行操作。 |
| Hybrid RAG | Jieba + PostgreSQL `ts_rank_cd`全文检索、固定本地BGE / pgvector、RRF；可选CPU Cross-Encoder默认关闭。不是BM25。 |
| MCP与评测 | 9个角色受限工具，复用领域服务；唯一写扩展仅商品草稿。Evaluation Studio区分Fixture、真实检索与历史Live来源。 |

## 架构

```mermaid
flowchart LR
  UI["用户 / React"] --> API["FastAPI：身份 / Store / 版本"]
  API -->|"Legacy Sync"| G["LangGraph：Single / Supervisor + Specialists"]
  API -->|"Durable Async：202"| Q[("PostgreSQL agent_jobs")]
  W["独立 Worker：锁 + Epoch Fence"] --> Q
  W --> G
  G --> V["工具白名单 / Schema / 固定预算"]
  V --> R["Hybrid Retrieval：全文 + BGE + RRF"]
  V --> D["Domain Services：提案 / 确认 / 事务 / 幂等"]
  UI -->|"独立批准 / Resume"| API
  D --> PG[("PostgreSQL / pgvector")]
  R --> PG
  G <--> CP[("Checkpoint / Journal / Thread Context")]
  CP --> PG
  PG --> E["脱敏 RunEvent / SSE / 评测投影"]
  E --> UI
  C["独立 MCP Client"] --> M["MCP Gateway：本地工具鉴权"]
  M --> D
```

MCP是外部工具接口，不是内部Agent工具的必经链路。Checkpoint回答“执行到哪”，领域事务和持久回执决定“实际写入什么”。[职责与代码入口](docs/ARCHITECTURE.md)。

## Quick Start：默认无Key演示

需要Docker和支持`!override`的Compose v2；构建会下载锁定依赖，不下载模型权重。镜像固定Python **3.12.10**、Node **24.21.0**、uv **0.9.18** 和PG17/pgvector；宿主走Docker路线不必另装Python/Node。Mac例子使用Docker Desktop，Linux用户将显式Context换成已核对的引擎。

```sh
# 仓库根目录；先确认同名项目不存在、8026/5196空闲，否则选新名称/端口。
export COMPOSE_PROJECT_NAME=agentmall-v214-demo
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml config --quiet
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml build runner
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml up -d --wait postgres
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml run --rm --no-deps \
  runner python scripts/demo.py --catalog-profile expanded --seconds 600
```

另开终端，按[场景设置](docs/PORTFOLIO_DEMO.md#场景设置)选择`context-catalog`；打开`http://127.0.0.1:5196`，合成账号`buyer1` / `AgentMall-demo-2026!`，新建 **Single Thread / Legacy Sync**：

1. `推荐300元以内的静音键盘，不要购买。`
2. `我改主意了，要支持无线连接的，预算提高到400元。`
3. `就买刚才推荐的第二款，一件，送演示宿舍。`

审阅快照后独立批准，终态为 **PENDING_PAYMENT，付款0**。自动化操作员标记 **TEST_OPERATOR**。服务端、数据库与Checkpoint真实运行，模型是 **SDK MockTransport / Fixture Embedding**；这不是DeepSeek实况或真实BGE。普通FastAPI默认`MODEL_DISABLED`。不要配置Provider Key或对公网开放测试控制接口。[停止、故障检查与自有资源清理](docs/PORTFOLIO_DEMO.md#停止及清理)。

![历史合成Mock/Fixture订单截图，不是实时DeepSeek](docs/screenshots/portfolio/06-order-detail.jpg)

截图来自历史V1三轮Mock Demo，来源及哈希见[原回执](docs/evidence/portfolio-demo/verification.json)，不是新实时模型演示。**VIDEO_NOT_RECORDED**。

## 验证结果：绑定准确源码

| 最终产品main CI | 实际结果 |
|---|---|
| pytest | **1291 passed / 14 skipped** |
| Vitest | **127 passed** |
| Playwright | **119 passed / 0 retries** |
| Ruff / format / TypeScript / ESLint / build | 全部通过 |
| Backend / Frontend / Release Gate | 全部success |

以上来自 **main `59f84ebbfdfb1d87287ad6c4ae83a1748183d30c` / [Run42770031624 Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42770031624)**，不是本轮重新运行的测试。main日志和三个公开ZIP的身份、大小、SHA已[独立核验](docs/evidence/v214-r4/verification.json)。14项原skip是13项真实权重依赖和1项私有Live原件比较；普通CI为Mock/Fixture，不能据此宣称新真实BGE或LLM验证。

Backend与Frontend各用独立PG并行执行；always Release Gate拒绝失败、取消、缺失或意外跳过的必需检查。首次单Job超时、R2修复、Push / PR / main CI成功均保留于[结果索引](docs/RESULTS.md)。[本轮发布清单与Tag方案](docs/RELEASE_CHECKLIST.md)区分已合并产品与尚未发布的文档、Tag及Release。

## 真实模型与项目限制

- 历史V2.12开发集Pilot为Single5/5、Multi4/5、总9/10，绑定`b5d6a685…`，不是当前版本成功率或独立Holdout。L6的10–11调用完成路径使用MockTransport。
- **同产品源码的L7 B2 Multi仍为PARTIAL / CONTEXT_SCOPE_VIOLATION，未完成第二次购买确认。** [逐版本证据](docs/V214_RELEASE_CANDIDATE.md#真实模型历史)。离线CI成功不证明真实LLM复杂任务的生产可靠性。
- V2.10真实检索是本地Linux aarch64/CPU、固定40条合成查询、单标注者；Reranker有延迟与召回代价，默认关闭。[数据与限制](docs/REAL_RETRIEVAL.md)。
- 没有生产部署、真实付款/退款、真实用户规模、QPS或SLA保证；Worker不是外部模型请求的通用Exactly-Once，历史Journal/资源销毁证据限制不回写。
- MCP仅stdio/localhost，**REMOTE_AUTH_NOT_IMPLEMENTED**；公开合成密码和测试标签不可当作公网认证。模型权重、私有配置与原始Live记录不进Git。

[一页介绍](docs/PORTFOLIO_ONE_PAGE.md) · [中英文项目描述](docs/RESUME_PROJECT_BLURB.md) · [Demo](docs/PORTFOLIO_DEMO.md) · [面试提纲](docs/PORTFOLIO_INTERVIEW.md) · [Release Notes草稿](docs/RELEASE_NOTES_v2.14.0.md)

原创源码、文档及合成素材采用[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；[权利人确认](docs/LICENSE_DECISION.md)、[第三方许可](THIRD_PARTY_NOTICES.md)与[版权边界](COPYRIGHT.md)继续适用，不分发模型权重或依赖二进制。个人贡献按实际参与及AI辅助范围说明，不将代码量或测试数当成独立贡献。
