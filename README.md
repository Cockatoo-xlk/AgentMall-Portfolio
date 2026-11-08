# AgentMall · 可恢复的购物 Agent 与事务电商

**FastAPI + PostgreSQL + LangGraph + Hybrid RAG + React / TypeScript**。将自然语言购物拆为商品检索、偏好更新、购买提案、独立确认与确定性订单事务，让“Agent建议了什么”和“系统实际执行了什么”能够分别核对。

用户可以在同一个Thread中说“300元以内静音键盘”，下一轮改为“400元、支持无线”，再选择**当前名单第二款**。服务端保存版本化偏好与候选绑定，重新核验商品后只准备提案；独立批准并Resume后才创建订单。

**[V2 演示路线](docs/PORTFOLIO_DEMO.md#v2-rc-三至五分钟演示) · [评测工作台](docs/EVALUATION_STUDIO.md) · [运行三轮Demo](docs/PORTFOLIO_DEMO.md) · [面试技术说明](docs/PORTFOLIO_INTERVIEW.md) · [架构细节](docs/ARCHITECTURE.md) · [RC集成结果](docs/evidence/v2-rc/verification.json)**

| 模式 | 可以证明什么 |
|---|---|
| 无Key作品集Demo | 页面明确显示 **SDK MockTransport**；Fixture Embedding、合成商品/账户，真实FastAPI、PostgreSQL、工具与Checkpoint。不是DeepSeek实况。 |
| 普通FastAPI | 默认 **MODEL_DISABLED**；启动API不等于启用模型。 |
| Live Playground | 已有ChatDeepSeek接入、工具协议与持久预算门禁；必须独立环境、授权、Key安全加载。当前T16真实多轮Pilot **NOT_RUN**。 |

![MockTransport与Fixture Embedding演示：TEST_OPERATOR确认的合成待支付订单](docs/screenshots/portfolio/06-order-detail.jpg)

截图为合成业务演示：**MockTransport + Fixture Embedding，确认操作者TEST_OPERATOR，未付款**。

## V2.11 商家AI运营助手

商家通过自然语言选择本店订单、售后、库存与索引只读工具；独立LangGraph执行受控计划、确定性统计、证据验证及审核说明草稿。每条建议显示业务ID、状态、版本和读取时间，分页截断如实标注；草稿只能填入原审核表单，仍需商家独立执行。默认API为MODEL_DISABLED，本地演示明确为SDK MockTransport，实际工具使用PostgreSQL。[操作、权限、MCP复用及演示](docs/MERCHANT_COPILOT.md) · [A—N及本地回归](docs/evidence/v211/report.md)。没有真实LLM能力或远程发布结论。

## V2.10 真实本地检索质量

新增固定BGE512维、CPU Cross-Encoder与四条同数据Pipeline对比；Expanded40查询保留分级标签、候选召回上限、无答案失败及真实延迟。新只读页面 `/engineering/evals/retrieval` 显示模型Revision、源码内容SHA和Top5差异。**重排默认关闭**：本次小型单标注者实验排序略有收益、召回下降且CPU延迟明显增加，不宣称生产或真实LLM优势。[模型、复现与证据边界](docs/REAL_RETRIEVAL.md) · [实际结果](docs/evidence/v210/report.md)。原Agent、Bundle和购买安全路径不变；真实Provider请求0。

## V2.9 多轮组合重规划

同一Thread可保留SKU、替换为更便宜商品、按品类修改规格、增删品类、调整整套预算与数量。只有受影响品类重新检索，其他SKU重读当前事实；展示新旧价格和方案差异，失败保留缺口与重检义务。购买仍需最新方案和一份独立Confirmation，不继承旧授权。[七种差分、增量检索与可复现演示](docs/BUNDLE_REPLANNING.md)。

## V2.8 MCP Tool Gateway

官方MCP Python SDK2.3.0提供标准stdio及localhost Streamable HTTP入口，独立客户端可发现并调用9个角色受限工具，查询商品、本人订单、售后资格、公开政策与本店商家资料。唯一写扩展只创建幂等DRAFT，不能批准、发布或执行交易。实际验证2026-07-28无协议会话请求、stdio旧版兼容及原领域数据一致性；不替换LangGraph内部工具。[连接指南、权限矩阵与独立客户端回执](docs/MCP_GATEWAY.md)。仅限本地：**REMOTE_AUTH_NOT_IMPLEMENTED**，没有真实Provider请求。

## V2.7 商家动态商品运营

商家在工作台导入CSV/JSON或创建草稿，查看带原文依据的规格建议，明确审核后独立发布。商品变更有版本与库存基线校验；检索索引单独执行、显示真实状态并有界重试。新品继续通过原商品、购物车、Single/Multi及Bundle购买链路。[操作指南与安全边界](docs/CATALOG_OPERATIONS.md)。本轮辅助为MockTransport、向量为Fixture，普通API默认禁用模型，未进行真实LLM评测或远程发布。

## V2.6 组合购物

同一Thread按2–5个品类独立检索，以整套预算生成有来源的组合。用户后续明确选择、数量与地址后，Order只准备一份多SKU提案；独立批准才通过原事务创建一笔订单。任一商品变化或缺货停止整套购买，支持刷新、SSE与幂等恢复。[组合演示、算法与安全边界](docs/BUNDLE_SHOPPING.md)。当前演示为MockTransport + Fixture Embedding，真实Live尚未验收。

## V2.5 多品类目录

扩展Profile提供 **13品类、120 SKU**，保留原12件及其UUID。手机、笔记本、显示器、摄影、骑行、健身和生活家电等都有独立规格及原创类别插画。Legacy仍是测试/历史评测的默认数据；普通Demo选择Expanded。详见[数据版本、启动与重建](docs/EXPANDED_CATALOG.md)。本轮验证单独记录于[结果索引](docs/RESULTS.md)，不套用旧RC或Live成绩。

## 核心能力

- **Multi-Agent**：Supervisor路由；Shopping检索商品，Order核验事实并准备购买，AfterSales处理资格、政策引用、售后与人工工单。保留Single模式，不假定Multi一定更优。
- **意图感知编排**：仅推荐时完成 Shopping 即可结束。退货加推荐先独立确认退货，再推荐替代品；明确替代购买需要另一份确认。交接前校验当前轮购买意图、数量、地址、候选与写工具范围。
- **实时进度**：React 在启动 POST 返回前用原 request_id 读取已持久化 Run，通过带内存认证头的 SSE 接收 RunEvent；按 seq 补读、去重并恢复。断流不会重启业务，原 GET 仍可查历史。
- **Evaluation Studio**：公开只读页面 `/engineering/evals` 比较配对成功率、P50/P95、调用数和安全诊断；复用原 metrics 与 Oracle，显示计划分母、未运行项和数据来源。
- **Thread上下文**：结构化SET / REPLACE / CLEAR、context_version；候选保存名单ID、稳定rank、Product ID与Catalog Version。偏好变化使旧名单失效，购买授权不跨Run继承。
- **Hybrid RAG**：PostgreSQL词法检索 + 固定BGE / pgvector向量召回 + RRF；店铺、价格、库存、状态与属性过滤在LIMIT前应用，工具重新读取当前事实。
- **HITL与恢复**：不可变Proposal → 独立Confirmation → 原Run Resume。官方PostgreSQL Checkpointer、RunEvent、节点Journal与Epoch Fence支持等待和恢复；JWT只存浏览器内存。
- **交易闭环**：购物车 → 确认下单 → 库存预留 → 订单详情独立确认模拟付款。购物车来源/版本由服务端绑定，创建订单时同事务安全消费；变化后的购物车保守保留，Agent直接下单不清理同SKU购物车。
- **商家运营工作台**：商家在 `/merchant` 处理本店订单和售后；模拟退款须核对快照，分别批准提案并执行。[操作与验证步骤](docs/MERCHANT_WORKBENCH.md)。
- **失败处理**：稳定request_id、action身份及幂等回执；响应未知先GET核对原结果。PARTIAL保留已完成业务，不用新随机请求盲目重做。

## 系统架构

```mermaid
flowchart LR
  U["用户 / React"] --> API["FastAPI：认证、Actor / Store校验"]
  API --> G["LangGraph StateGraph / Supervisor"]
  G --> S["Shopping"]
  G --> O["Order"]
  G --> A["AfterSales"]
  S --> R["Hybrid RAG：全文 + pgvector + RRF"]
  O --> T["受校验的业务工具 / Proposal"]
  A --> R
  A --> T
  R --> DB[("PostgreSQL：目录、政策、业务数据")]
  T --> W["WAITING_INPUT / 不执行交易"]
  W --> H["用户审阅快照并独立Confirmation"]
  H --> API
  API --> X["Resume：确定性领域事务"]
  X --> DB
  G <--> CP[("官方Checkpoint / Thread Context / RunEvent")]
  CP --> DB
  DB --> ES["只读 RunEvent / SSE"]
  ES --> U
  U --> M["商家工作台 / 本店订单与售后"]
  M --> API
  E["版本化脱敏评测 JSON"] --> ST["Evaluation Studio"]
  ST --> U
```

模型只能调用白名单工具，不能自行批准购买、付款或退款。事务边界位于领域服务，Checkpoint保存图进度，不代替订单事务。详细实现：[工具及参数](backend/src/agentmall/agents/specialist_tools.py)、[持久图](backend/src/agentmall/agents/durable_graph.py)、[Run协调](backend/src/agentmall/agents/run_service.py)、[Thread Memory](backend/src/agentmall/agents/memory.py)、[交易服务](backend/src/agentmall/orders/service.py)。

## 本地运行：无Key三轮购物

需要Docker及支持`!override`的Docker Compose v2，仅使用新建、归属明确的项目。以下命令面向Mac Docker Desktop；其他引擎应替换为自己已确认的Context。先确认8026/5196空闲且没有同名旧项目，不停止未知服务、不复用历史数据库。

```sh
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml config --quiet
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml build runner
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml up -d --wait postgres
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml run --rm --no-deps \
  runner python scripts/demo.py --catalog-profile expanded --seconds 900
```

另开终端，按[健康检查与场景选择](docs/PORTFOLIO_DEMO.md#启动)启用已有`context-catalog` **MockTransport**场景。登录[网页](http://127.0.0.1:5196)，合成账号`buyer1` / `AgentMall-demo-2026!` → “工作流” → 创建Multi Thread，依次输入：

1. `推荐300元以内的静音键盘，不要购买。`
2. `我改主意了，要支持无线连接的，预算提高到400元。`
3. `就买刚才推荐的第二款，一件，送演示宿舍。`

查看提案后独立批准；自动化演示点击明确标记 **TEST_OPERATOR**。本场景仅生成待支付订单、付款0；完整[操作、截图、缓存构建备选与清理说明](docs/PORTFOLIO_DEMO.md)均已提供。数据库不发布宿主端口，测试控制API只能留在独占localhost演示中。不要配置Provider Key。

订单详情另有“模拟付款”，需要新的支付Proposal与Confirmation，与购买确认分开；所有资金均为合成数据，不发生真实扣款。普通购物车与Agent订单共用同一详情页。刷新后需重新登录，再用原Thread ID恢复，不能把浏览器导航引用当作权限。

## V2 RC 历史集成验收（6062c899）

本地 RC 从 `d6b418a0aadb7b598595560a0df4c42dc79cce39` 整合四项 V2 功能。完整离线回归、实际源码内容绑定、失败与修复、平台及日志哈希见[RC 回执](docs/evidence/v2-rc/verification.json)和[结果索引](docs/RESULTS.md)。演示采用 MockTransport / Fixture，真实 Provider 请求为 0。当前 RC 的 Ubuntu amd64 远程 CI 为 `NOT_RUN`。

| 验证 | 结果与范围 |
|---|---|
| V2 RC 本地完整回归 | pytest 866 passed / 14 skipped；Vitest 92 passed；Playwright 105 passed、0 retries。Linux aarch64、独占 PostgreSQL 17 / pgvector、官方 Checkpoint、Chromium |
| [历史 R8 Run41972687787 / Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/41972687787) | pytest 834 passed / 14 skipped、Vitest 85、Playwright 96；CI提交 `e60ee792…`、冻结产品 `77b21587…`，Ubuntu24.04 x86_64 |
| 同一历史 Run Stage B | 固定 BGE、512维CPU、14项检索、三轮Mock及独立Oracle通过；适用范围仍绑定其历史源码 |
| Evaluation Studio 随附批次 | 9任务 × Single/Multi，共18个开发集Fixture Episode；运行源码 `8cb788de…`，两架构各9/9，详见页面Evidence |

离线核心沿用原14项skip边界，即13项真实BGE权重依赖和1项私有Live原件比较。历史真实BGE验收与当前Fixture回归分别记录。旧OOM、时钟与中断失败保留在[工程案例](docs/ENGINEERING_CASES.md)及各阶段报告。

## 已知限制与后续工作

- MockTransport决定路由和工具请求，不能证明真实模型的多轮理解。当前T16真实多轮Live仍未运行；后续需独立环境、价格快照、持久费用预算和明确授权。
- T15-B1仅在旧提交`617cdf29`做过一个真实购物Smoke：7次Provider调用、50条事件、独立确认后唯一待支付订单、付款0；平台实际账单UNKNOWN。不能将其当作当前版本验收。[历史公开摘要](docs/evidence/t15-c/b1-public-summary.json)
- 两次历史真实开发集Pilot使用同五题：Single1/5→5/5、Multi4/5→4/5。40题已参与开发，不是独立Holdout，不能推导泛化提升或Multi总体优越性。
- Mac本地虚拟化曾有时钟回退与采样吞吐不足；原JWT与60/900秒合同未降低。本次短Demo不是新的Live环境准入。历史约1.91GiB环境的OOM/143、137均保留，不能称为完整单容器CI成功。
- Journal的node_journal/resume_journal直接字段快照不在R8冻结Oracle范围；镜像及托管Runner最终物理销毁UNKNOWN。图恢复不保证任意SIGKILL下外部模型调用exactly-once。
- 没有真实支付/退款、生产负载/SLA/灾难恢复验收或云部署。`VIDEO_NOT_RECORDED`；已提供截图及3—5分钟录制脚本。未来工作优先是获授权的真实多轮Pilot和面向使用者的交互优化。
- 历史作品集Demo限时停止未完成API临时Schema的优雅清理；业务原件保存后，专属PG和Volume等资源已删除并查无。内部停止原因UNKNOWN，不能将stop退出0当作清理证明。复现时按[专属清理步骤](docs/PORTFOLIO_DEMO.md#停止及清理)处理，不触及历史数据。

## 许可与贡献说明

原创内容采用[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk。第三方组件分别遵守[自身许可证](THIRD_PARTY_NOTICES.md)；[版权](COPYRIGHT.md)、[许可决定](docs/LICENSE_DECISION.md)与[公开快照边界](SNAPSHOT.md)可核查。公开仓库不包含原Private研发历史、原始Live账本、批准回执、模型权重或原始Checkpoint。

面试表述应按事实说明个人设计、实现、调试与AI辅助范围，不把仓库规模或测试数字等同于个人独立贡献。发布、Push、远程Actions及部署仍是独立操作，不由本地演示准备自动授权。
