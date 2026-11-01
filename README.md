# AgentMall：事务电商与可恢复 Agent 工作流

一个面向 Backend / Agent / AI Application 工程岗位的合成电商作品。React 中文商城连接真实 FastAPI、PostgreSQL 和 LangGraph：用户可以自己选购，也可以让 Agent 检索商品、检查订单与售后事实、准备操作提案，最终由用户独立确认、确定性领域服务提交事务。

**当前本地发布候选包含完整模拟购买闭环：购物车 → 购买提案 → 确认下单 → 独立确认模拟付款 → 查询订单与回执。** 默认模型为明确标记的 Fixture Model，商品、账号、地址及资金均为合成数据，不发生真实扣款，也不需要付费模型 Key。本候选尚未上传；[已发布 main](https://github.com/Cockatoo-xlk/AgentMall-Portfolio) 保持原版本，等待权利人审核最终 SHA。

## 可以验证的能力

| 工程问题 | 实现与证据 |
|---|---|
| 购物车与订单一致性 | 服务器把 Cart 来源/版本绑定到不可变提案；订单创建和库存预留时在同一 PostgreSQL 事务中消费未变化的购物车。提案后新增、修改、重新加入的商品保守保留；Agent 独立商品下单不清理购物车。[事务与测试](backend/tests/test_checkout_cart_consumption.py) |
| 模拟支付的人工授权 | 订单详情展示服务端支付快照，用户单独批准或拒绝；不复用购买确认。付款、拒付、取消及到期不重复消费或擅自恢复购物车。[支付交互](frontend/src/components/MockPaymentPanel.tsx)、[浏览器闭环](frontend/tests/payment.spec.ts) |
| 重复请求和响应丢失 | PostgreSQL 行锁、库存 CHECK、action 身份及幂等回执；结果未知先 GET 核对原提案、订单和购物车，不换新请求盲目下单或付款。[数据库 Oracle](backend/tests/integration/oracle.py)、[Cart 浏览器回归](frontend/tests/cart_checkout.spec.ts) |
| 等待、刷新与恢复 | 官方 PostgreSQL Checkpointer、节点 Journal、Epoch Fence、持久预算；购买、退货及替代购买分别确认后 Resume。[恢复协调](backend/src/agentmall/agents/run_service.py)、[工作流回归](frontend/tests/return_replace.spec.ts) |
| Agent、检索与权限 | Single，或 Supervisor + Shopping / Order / AfterSales；严格工具参数、服务端 Actor/Store 授权、公开政策版本引用、持久 RunEvent 与脱敏 Trace。Fixture 验证不冒充真实 DeepSeek 推理。 |

[三项工程案例](docs/ENGINEERING_CASES.md) · [实际架构](docs/ARCHITECTURE.md) · [结果及限制](docs/RESULTS.md) · [3–5分钟演示](docs/DEMO.md)

本地开发版新增[Live Playground 显式入口](docs/LIVE_PLAYGROUND.md)，复用现有持久化工作流和独立人工确认。本轮只验证真实 DeepSeek SDK 的离线 MockTransport 接线；真实付费 Smoke 尚未授权、未运行，默认 Fixture/模型关闭边界保留。

[T15-A 本地离线回归](docs/evidence/t15-a/report.md)：后端711 passed/14 skipped、Vitest71 passed、Playwright84 passed；均为分阶段本地结果，不能代替真实 DeepSeek 或远程 CI 验证。

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

## T14 已验收基线与环境边界

2026-11-01 的 T14-P1 最终分阶段验收：

| 检查 | 实测结果 | 环境 |
|---|---|---|
| 后端 CI_OFFLINE_CORE | **670 passed / 14 skipped** | 本地 Linux ARM64 容器，真实 PostgreSQL17.11 / pgvector0.8.7 / Checkpoint |
| 前端 Vitest | **65 passed** | 本机 macOS ARM64，锁定 Node/npm 依赖 |
| Playwright 全量 | **74 passed**，1 worker / 0 retries / 0 skips | Mac 完整 Chromium headless + 独占容器 FastAPI / PostgreSQL / Checkpoint |
| Ruff、格式、typecheck、lint、build | 全部退出0 | 见原始回执哈希及源码对应核对 |

[T14-P1证据及数据库终态](docs/evidence/t14-p1/report.md)保留成功与失败；[本轮发布前核对](docs/evidence/t14-r1-a/report.md)复用经哈希验证的回执。14项跳过仅13个真实 BGE 权重依赖和1个未公开私有 Live 原件比较，核心事务、T09恢复/SIGKILL、T10 Trace、T11并发和T12预算/权限/Oracle没有扩大跳过。

本机约1.91GiB、无swap的 Docker 引擎曾在单容器完整流程中 OOM、退出143，因此**不声称单容器整套 CI 通过**。最终完整检查集合分阶段完成；这不是新的 GitHub Ubuntu amd64 远程 CI 回执。该候选尚未运行远程 CI，既有发布版与 Private RC 的成绩另见[结果索引](docs/RESULTS.md)，不能代替当前 SHA 的远程结果。

## 已知限制与许可

旧 P0 演示 runner 在 P1 期间结束，原因 **UNKNOWN**；用户确认没有手动关闭，本轮也没有向它发出停止/重启命令，不能据此保证共享引擎运行时完全未受影响。四个旧 PostgreSQL 容器及受保护文件核对一致，完整限制保留在 P1 报告。

两轮真实 DeepSeek Pilot 使用同一开发任务集：Single **1/5→5/5**，Multi **4/5→4/5**；第二轮 Multi B2 仍失败/PARTIAL，原始中断记录保留。43/53请求及冻结估算不等于平台实际账单（**UNKNOWN**）；原40题已参与开发，不是独立 Holdout，不能据此推导泛化提升或架构总体优劣。L6后没有第三次 Live，本候选没有新的付费模型实验；历史 Frozen Manifest 没有重封存来描述新源码。

进程内 Journal 不保证任意 SIGKILL 下外部模型调用 exactly-once；本地和远程 CI 都不是生产负载、SLA或容灾证明。没有真实支付/退款、云部署或生产验收，`VIDEO_NOT_RECORDED`。源码和文档不代替个人贡献说明，AI辅助范围需按事实披露。

项目原创内容采用[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；[权利人决定](docs/LICENSE_DECISION.md)、[COPYRIGHT](COPYRIGHT.md)和[第三方声明](THIRD_PARTY_NOTICES.md)说明归属。公开作品版建立独立 Git 根，不携带原 Private 研发历史、原始 Live 账本、授权记录或模型权重；[候选来源与排除边界](SNAPSHOT.md)仍保留。未来发布二进制、镜像或模型需另行审查。本阶段仅本地候选准备，上传、Actions、Release及部署均需各自明确授权。
