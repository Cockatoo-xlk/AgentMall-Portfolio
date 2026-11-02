# AgentMall：可恢复的 Multi-Agent 事务电商

基于 **FastAPI + PostgreSQL + React + LangGraph** 的合成电商与 AI 应用工程作品。支持 Single-Agent，或 **Supervisor + Shopping / Order / AfterSales** 协作；通过 Hybrid RAG 检索商品和公开政策，用 Tool Calling 准备操作提案，再由用户独立确认、领域服务提交事务。HITL、PostgreSQL Checkpoint 和持久事件支持等待、刷新与故障恢复。

**购物车 → 购买提案 → 人工确认下单 → 独立确认模拟付款 → 服务端订单与回执。** 库存预留、购物车消费、Confirmation 和幂等回执在 PostgreSQL 事务中协调；金额、账号、商品与资金均为合成数据，不发生真实扣款。

| 运行方式 | 模型与验证边界 |
|---|---|
| 默认无 Key Demo | 明确标记 **Fixture Model**，真实 FastAPI / PostgreSQL / Checkpoint；普通 FastAPI 单独启动为 MODEL_DISABLED。 |
| Live Playground | 独立本机入口使用真实 ChatDeepSeek SDK，需新授权、环境、价格和持久预算门禁。**T15-B1 仅在旧提交 `617cdf29` 完成一个 Multi-Agent 购物场景**；7 次 Provider 回执、50 条事件、唯一待支付订单。当前源码新 Live 验收 **NOT_RUN**，旧许可不能复用。[历史摘要](docs/evidence/t15-c/b1-public-summary.json) |

T16-A 本地离线回归：**pytest 742 passed / 14 skipped · Vitest 84 passed · Playwright 94 passed / 0 retries**。独立 **Linux aarch64 + Mac Chromium**；新受控保醒窗口连续时钟检测通过，旧休眠异常与失败全部保留。当前T16源码远程CI及真实Live多轮验收均为 **NOT_RUN**。[结果、时钟与限制](docs/evidence/t16-a/report.md)

[安全运行与恢复](docs/REAL_AGENT_DEMO.md) · [3–5分钟演示脚本](docs/DEMO_RECORDING_SCRIPT.md) · [架构](docs/ARCHITECTURE.md) · [工程案例](docs/ENGINEERING_CASES.md)

T16-A 增加同一 Thread 的版本化购物偏好、稳定候选编号和跨 Run 恢复；偏好可替换或清除，购买授权不继承。[多轮操作与 API](docs/THREAD_CONTEXT.md)。当前改动仅做离线验证，真实 Live 多轮验收 NOT_RUN。

## 可以验证的能力

| 工程问题 | 实现与证据 |
|---|---|
| 购物车与订单一致性 | 服务器把 Cart 来源/版本绑定到不可变提案；订单创建和库存预留时在同一 PostgreSQL 事务中消费未变化的购物车。提案后新增、修改、重新加入的商品保守保留；Agent 独立商品下单不清理购物车。[事务与测试](backend/tests/test_checkout_cart_consumption.py) |
| 模拟支付的人工授权 | 订单详情展示服务端支付快照，用户单独批准或拒绝；不复用购买确认。付款、拒付、取消及到期不重复消费或擅自恢复购物车。[支付交互](frontend/src/components/MockPaymentPanel.tsx)、[浏览器闭环](frontend/tests/payment.spec.ts) |
| 重复请求和响应丢失 | PostgreSQL 行锁、库存 CHECK、action 身份及幂等回执；结果未知先 GET 核对原提案、订单和购物车，不换新请求盲目下单或付款。[数据库 Oracle](backend/tests/integration/oracle.py)、[Cart 浏览器回归](frontend/tests/cart_checkout.spec.ts) |
| 等待、刷新与恢复 | 官方 PostgreSQL Checkpointer、节点 Journal、Epoch Fence、持久预算；购买、退货及替代购买分别确认后 Resume。[恢复协调](backend/src/agentmall/agents/run_service.py)、[工作流回归](frontend/tests/return_replace.spec.ts) |
| Agent、检索与权限 | Single，或 Supervisor + Shopping / Order / AfterSales；严格工具参数、服务端 Actor/Store 授权、公开政策版本引用、持久 RunEvent 与脱敏 Trace。Fixture 验证不冒充真实 DeepSeek 推理。 |

## 无 API Key 的 Quick Start

准备 Docker 引擎及 Compose。**仅在新克隆的独立目录、无同名 Compose 项目且端口空闲时运行**；已有同名项目或端口占用时先核对归属，不能停止未知服务或复用他人的 PGDATA。镜像安装锁定依赖和浏览器，不读取个人 .env 或下载 BGE 权重。

```sh
docker compose -p agentmall-portfolio -f compose.ci.yaml build runner
docker compose -p agentmall-portfolio -f compose.ci.yaml up -d --wait postgres
docker compose -p agentmall-portfolio -f compose.ci.yaml run --rm runner python scripts/demo.py --prepare-return --seconds 900
```

打开[商城](http://127.0.0.1:5174)，合成账号 `buyer1` / `AgentMall-demo-2026!`；演示运行时可查看 [OpenAPI](http://127.0.0.1:8001/docs)。宿主数据库端口55434，容器独立网络内部55433；不连接宿主历史55432/55433。测试控制入口和公开合成口令仅供独占、一次性本地演示，不能作为公网或生产服务的配置。

登录 → 加入购物车 → 生成购买提案 → 确认并创建订单，此时待支付且未变化的结算项已移除。订单详情点击“模拟付款”，审阅金额、币种、有效期后单独批准，再查询真实后端回执和最新订单。刷新后需重新登录；购物车查询失败显示待核对，不伪造空车。

退出演示并等待清理后，使用相同项目及配置执行 `docker compose -p agentmall-portfolio -f compose.ci.yaml down`，只移除确认属于该目录的容器/网络；不要加 `-v` 或删除历史数据库。已有演示的开发机可使用[独立端口与分阶段验证配置](docs/DEMO.md#t14-p1本地购物车结算)。

## 本地验证与环境边界

| 检查 | 实测结果 | 环境 |
|---|---|---|
| 后端 CI_OFFLINE_CORE | **742 passed / 14 skipped** | 独立 Linux aarch64 VM，真实 PostgreSQL17.11 / pgvector0.8.7 / Checkpoint |
| 前端 Vitest | **84 passed** | Mac，锁定 Node/npm 依赖 |
| Playwright 全量 | **94 passed**，1 worker / 0 retries / 0 skips / 0 flaky | Mac 完整 Chromium headless + 独立 Linux aarch64 VM 后端 |
| Ruff、格式、typecheck、lint、build | 全部退出0 | 见原始回执哈希及源码对应核对 |

当前T16源码的命令回执、源码指纹、PG/Checkpoint终态和新增29/4/7项测试见[T16报告](docs/evidence/t16-a/report.md)。[历史T15-C1回执](docs/evidence/t15-c1/report.md)与D1审查对应旧指纹，仍原样保留。14项跳过仅13个真实BGE权重依赖和1个私有Live原件比较，事务、恢复/SIGKILL、Trace、并发和预算/权限测试没有扩大跳过。

原共享VM的时钟回退仍未修复；旧T15-C的81通过/6失败保留，一项同用例复现了JWT未来iat，其余五项历史原因未确定。T15-C1的独立VM准入及完整测试窗口无重大时钟异常，旧六项当时在87项中一次通过。T16早期观测又发现宿主休眠相关跳变；使用有时限的进程级保醒重新准入后，完整742/84/94回归窗口没有重大异常。不能放宽JWT校验或在旧环境反复碰绿色。

本机约1.91GiB、无swap的旧 Docker 引擎曾在P1单容器完整流程中 OOM、退出143；T15-A也保留OOM/137。**不声称这些单容器流程通过**。本地检查集合分阶段完成，不替代当前版本GitHub Ubuntu24.04 amd64实测。[历史结果索引](docs/RESULTS.md)保留各阶段证据与失败。

## 已知限制与许可

旧 P0 演示 runner 在 P1 期间结束，原因 **UNKNOWN**；用户确认没有手动关闭，本轮也没有向它发出停止/重启命令，不能据此保证共享引擎运行时完全未受影响。四个旧 PostgreSQL 容器及受保护文件核对一致，完整限制保留在 P1 报告。

两轮真实 DeepSeek Pilot 使用同一开发任务集：Single **1/5→5/5**，Multi **4/5→4/5**；第二轮 Multi B2 仍失败/PARTIAL，原始中断记录保留。43/53请求及冻结估算不等于平台实际账单（**UNKNOWN**）；原40题已参与开发，不是独立 Holdout，不能据此推导泛化提升或架构总体优劣。L6后没有第三次开发集Pilot；历史B1只有一次指定Smoke；T15-C无新付费请求，历史 Frozen Manifest 没有重封存来描述新源码。

进程内 Journal 不保证任意 SIGKILL 下外部模型调用 exactly-once；本地和远程 CI 都不是生产负载、SLA或容灾证明。没有真实支付/退款、云部署或生产验收，`VIDEO_NOT_RECORDED`。源码和文档不代替个人贡献说明，AI辅助范围需按事实披露。

项目原创内容采用[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；[权利人决定](docs/LICENSE_DECISION.md)、[COPYRIGHT](COPYRIGHT.md)和[第三方声明](THIRD_PARTY_NOTICES.md)说明归属。公开作品版建立独立 Git 根，不携带原 Private 研发历史、原始 Live 账本、授权记录或模型权重；[源码来源与排除边界](SNAPSHOT.md)保留。未来发布二进制、镜像或模型需另行审查。[D1发布审查](docs/evidence/t15-d1/report.md)与[发布清单](docs/RELEASE_CHECKLIST.md)按阶段记录，上传、Actions、Release和部署各需独立授权及对应SHA回执。
