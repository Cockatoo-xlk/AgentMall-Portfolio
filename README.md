# AgentMall：事务电商与可恢复 Agent 工作流

一个面向 Backend / Agent / AI Application 工程岗位的合成电商作品。中文 Web 页面连接真实 FastAPI、PostgreSQL 和 LangGraph；模型检索商品、检查售后事实并准备提案，独立用户确认后由确定性领域服务执行。默认演示使用 Fixture Model，付费模型请求为零。

本项目的公开作品版由经审查的源码快照建立**独立 Git 根**，不携带原私有研发仓库的提交历史、账号密钥、原始 Live 账本或模型权重。项目原创内容采用[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；权利人已确认必要的源码公开权限。[验证结果](docs/RESULTS.md)区分原 Private RC 和本作品版的本地测试；本作品版的远程 CI 仅以其实际 GitHub Actions 回执为准。源码和文档不代替个人贡献说明，AI 辅助范围需按事实披露。

## 可以验证的能力

| 工程问题 | 实现与证据 |
|---|---|
| 库存、重复请求和响应丢失 | PostgreSQL 行锁、库存 CHECK、独立确认、action 身份和幂等回执；[领域事务](backend/src/agentmall/orders/service.py)、[真实数据库 Oracle](backend/tests/integration/oracle.py) |
| 工作流等待、刷新和恢复 | 官方 PostgreSQL Checkpointer、节点 Journal、Epoch Fence、持久预算；[恢复协调](backend/src/agentmall/agents/run_service.py)、[持久图](backend/src/agentmall/agents/durable_graph.py) |
| 人工授权 | Proposal → 独立 Confirmation → 原 Run Resume；退货和替代购买分别确认，[浏览器回归](frontend/tests/return_replace.spec.ts) |
| 专业 Agent 与检索 | Single，或 Supervisor + Shopping / Order / AfterSales；白名单、严格参数、服务端 Actor/Store 授权和公开政策版本检索 |
| 观察与费用 | 持久 RunEvent 和脱敏 Trace，UNKNOWN Usage 保留；两轮真实开发集结果与失败分开报告 |

[三项工程案例](docs/ENGINEERING_CASES.md) · [实际架构](docs/ARCHITECTURE.md) · [结果及限制](docs/RESULTS.md) · [候选来源与排除边界](SNAPSHOT.md)

## 无 API Key 的 Quick Start

准备 Docker 引擎及 Compose，在仓库根目录执行。首次必须使用本目录自己的新 PGDATA，端口冲突先辨认归属，不终止未知服务。镜像安装锁定依赖和浏览器，不读取个人 .env 或下载 BGE 权重。

```sh
docker compose -p agentmall-portfolio -f compose.ci.yaml up -d --wait postgres
docker compose -p agentmall-portfolio -f compose.ci.yaml build runner
docker compose -p agentmall-portfolio -f compose.ci.yaml run --rm runner
docker compose -p agentmall-portfolio -f compose.ci.yaml run --rm runner python scripts/demo.py --prepare-return --seconds 900
```

打开 [商城](http://127.0.0.1:5174)，合成账号 `buyer1` / `AgentMall-demo-2026!`。看到 Fixture 标识后按[3–5分钟演示](docs/DEMO.md)操作；接口文档在演示运行时的 [OpenAPI](http://127.0.0.1:8001/docs)。宿主数据库暴露为 55434；容器独立网络内部 55433 满足现有测试 Guard，**不连接宿主的历史 55432/55433**。

退出演示并等待清理后，`docker compose -p agentmall-portfolio -f compose.ci.yaml down` 只移除这个项目的容器/网络，保留本目录专属 PGDATA。不要加 `-v`、删除旧数据库、复用他人目录或把测试入口暴露公网。后续复用 PGDATA 不再称为空数据库首次验收。

## 验证与真实边界

原 Private RC 的 GitHub Ubuntu 24.04 amd64 Run **41170933236 / Attempt 1 / 2026-10-31** 已实测：后端 **642 passed / 14 skipped**，Vitest **38 passed**，Playwright **43 passed**。原本机 Mac **656 passed** 属于另一个环境。它们不等于此独立快照已在新的 Public GitHub 仓库运行；详见[脱敏 CI 摘要](docs/evidence/private-rc-ci.json)及[独立快照验证](docs/RESULTS.md)。

CI 的 14 项跳过仅 13 个真实 BGE 权重依赖与 1 个未公开私有 Live 原件比较；核心恢复、8组 SIGKILL、T11 并发、预算/权限/Oracle 不跳过。默认模型为 Fixture 和 MockTransport，不发 DeepSeek 请求。GitHub Actions 的 Action 和镜像固定 SHA；本作品版的远程 CI 状态须按其实际 GitHub Actions 运行记录核对。

两轮真实同开发集 Pilot：Single **1/5→5/5**，Multi **4/5→4/5**；43 / 53 请求，冻结高峰估算 ¥0.251492 / ¥0.341790，平台实际账单 UNKNOWN。第二轮 Multi B2 仍失败/PARTIAL，外层误判 SIGINT、退出130/-2保留；L6后没有第三次 Live。原40题已参与开发，不是独立 Holdout，不能推导泛化提升或架构总体优劣。

## 尚未验证与许可

合成账号、商品、地址、模拟支付/退款，没有真实资金或生产部署。进程内 Journal 收束不保证任意 SIGKILL 下外部模型调用 exactly-once；本地/远程 CI 也不是生产负载、SLA或容灾证明。没有录屏，`VIDEO_NOT_RECORDED`。

项目原创内容采用[MIT](LICENSE)，[权利人许可决定](docs/LICENSE_DECISION.md)及[COPYRIGHT](COPYRIGHT.md)说明归属。[第三方声明](THIRD_PARTY_NOTICES.md)限定已审核的源码/截图范围；未来二进制、镜像或模型再分发另行核验。公开仓库的 CI 是否通过，必须提供对应 Commit SHA、Run ID 和实际回执，不得以原 Private RC 的成绩代替。
