# 无Key默认Demo：Single + SDK MockTransport + Fixture

真实 React / FastAPI / PostgreSQL / LangGraph / Checkpoint，模型决策由 **SDK MockTransport** 提供，向量为 **Fixture Embedding**；合成数据，确认操作者为 **TEST_OPERATOR**。不是 DeepSeek 实况或本地 BGE 语义质量实测。**VIDEO_NOT_RECORDED**。

## 启动

在仓库根目录执行。需要Docker、支持 `!override` 的Compose v2，以及构建时获取锁定依赖的网络；不需要Provider Key或模型权重。Mac例子显式使用 `desktop-linux`，其他环境换成已核对的Context；不切换全局Context。

```sh
export COMPOSE_PROJECT_NAME=agentmall-v214-demo
# 先确认该项目不存在；若有同名历史资源，选择新的项目名，不能直接 down。
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml ps -a
lsof -nP -iTCP:8026 -iTCP:5196 -sTCP:LISTEN
# lsof没有输出/退出1表示没有匹配监听，不是业务失败。
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

`--env-file /dev/null`阻止Compose自动读取仓库本地`.env`。示例Compose的数据库密码/测试标签是公开合成配置，不是部署凭据。不要附加真实Key文件或旧PGDATA。脚本只允许在此类新建容器内初始化；拒绝复用已有业务Schema。

默认宿主网页 `http://127.0.0.1:5196`、API文档 `http://127.0.0.1:8026/docs`。PG内部55433，不发布数据库端口。源码中的8001/5174是内部应用，18001/15174是容器代理。若默认宿主端口已占用，在所有Compose命令前设置 `AGENTMALL_DEMO_API_PORT` 和 `AGENTMALL_DEMO_WEB_PORT` 为两个空闲端口，并相应修改下面的URL；不要停止未知监听进程。

新用户走上面的标准构建；本轮只验证了其静态配置，实际使用可信依赖缓存加准确跟踪源码构建，**冷启动拉取全部基础镜像NOT_RUN**，不是全新机器的网络保证。可信本地依赖镜像可以加速，但缓存缺wheel时 `--offline` 会失败，不应宣称离线缓存必然足够；[旧阶段缓存命令](history/PORTFOLIO_DEMO-before-v214.md)仅作历史记录。Guest约2GiB、PG1GiB是此Fixture Demo的限制，不是完整测试或Live容量保证。

## 场景设置

保持Demo终端前台运行，在第二个终端执行：

```sh
curl --fail --silent --show-error http://127.0.0.1:8026/__test/health \
  -H 'X-E2E-Key: agentmall-local-e2e'
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"context-catalog"}'
```

健康返回 `fake-model-real-fastapi-postgresql`，场景返回 `MOCK_TRANSPORT`、`real_model_calls=0`。这会使用当前真实目录，不制造固定必返回SKU。Mock回包的模型名/Token/费用不是Provider用量或账单。`/__test`仅存在于专用测试入口，其标签不是可公网部署的认证；普通 `agentmall.main` 默认MODEL_DISABLED。不要在未完成Run中切换场景或reset。

## 五分钟主线

登录：`buyer1` / `AgentMall-demo-2026!`（公开合成账户）。进入“工作流”，新建 **Single Thread**，保留 **Legacy Sync**。默认选Multi时请先手动改为Single；不要把界面默认值当成此次路线。

| 时间 | 操作 | 必须看到的事实 |
|---|---|---|
| 0:00–0:40 | 展示商城13品类，登录并创建Single Thread | 页面明确SDK MockTransport / Fixture；不是实况DeepSeek |
| 0:40–1:30 | 输入“推荐300元以内的静音键盘，不要购买。” | 真实目录候选及工具事件；不创建订单 |
| 1:30–2:15 | 输入“我改主意了，要支持无线连接的，预算提高到400元。” | 静音保留、预算替换400、无线条件、新的候选集合 |
| 2:15–3:10 | 输入“就买刚才推荐的第二款，一件，送演示宿舍。” | 当前第二款绑定Product ID；WAITING_INPUT；全部商品/数量/价格/地址快照；此时还没有新订单 |
| 3:10–4:00 | 以TEST_OPERATOR独立点击批准/继续 | 真实事务生成唯一PENDING_PAYMENT订单，付款增量0 |
| 4:00–5:00 | 打开订单详情，刷新并重新登录，恢复原Thread | 原订单/时间线仍可读；不新发购买请求，不产生第二订单 |

界面按钮以实际快照卡文案为准，批准与Resume使用原界面受控流程；Agent不能替用户点确认。买家批准购买不会批准付款。默认路线**不要点击模拟付款**。数量/第二款只按当前显示名单，不从历史截图抄SKU。

## 查看库存、幂等与持久状态

运行事件/订单详情是可展示部分；不要把HTTP200或回答文本当成数据库Oracle。需要开发者核对时，在本次PG内执行只读SQL：先用健康返回的**本次Schema**，核对标识后设置 `default_transaction_read_only=on` 与该Schema的search_path，SELECT订单、order_items、confirmations、products.reserved、idempotency_requests和run_events。不要在截图/共享终端展示JWT、DSN、原始Checkpoint或私有日志。

本轮实际演示的独立数据库断言和官方Checkpoint检查在[本轮回执](evidence/v214/verification.json)。自动化测试通过不等于用户本人授权；所有演示批准均归为TEST_OPERATOR。

## 可选扩展：不要挤进默认五分钟

- [Bundle](BUNDLE_SHOPPING.md) / [Replanning](BUNDLE_REPLANNING.md)：单独新Thread，使用既有bundle场景；不能把context-catalog的受控三轮程序说成开放式语义模型。
- [商家工作台](MERCHANT_WORKBENCH.md) / [Copilot](MERCHANT_COPILOT.md)：合成merchant登录；Copilot只读，草稿不执行审核。
- [MCP](MCP_GATEWAY.md)：独立官方客户端连接stdio/localhost；不要在当前Demo库随意迁移/Seed或公开Token。
- [Worker](V212_DURABLE_WORKER.md)：另一次新Demo启动加 `--async-worker`，界面显式选择Durable Async。HTTP202只表示入队；没有Worker时应如实显示QUEUED。故障恢复已有受控测试，不在面试现场随机kill历史服务。
- [Evaluation Studio](EVALUATION_STUDIO.md) / [真实检索](REAL_RETRIEVAL.md)：静态报告显示原始SHA和数据集，不能把历史数据说成当前模型已通过。

## 停止及清理

先保存脱敏截图/合成结果，然后在前台按Ctrl-C。脚本尝试结束自有API、Vite与Worker，并清理临时Schema；单凭退出0不能证明资源已清理。旧Demo曾出现限时停止不完整，历史事实保留于[旧报告](history/PORTFOLIO_DEMO-before-v214.md#停止及清理)。本轮实际停止与资源状态另记，不覆盖旧结论。

仅对**本次确认为自己创建**的同一项目执行：

```sh
# 必须仍是启动时的 COMPOSE_PROJECT_NAME；不使用通配符/全局prune。
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml down --volumes
docker --context desktop-linux ps -a --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
docker --context desktop-linux volume ls --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
docker --context desktop-linux network ls --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
```

没有数据行才可说明这组资源已查无；失败/未知则保留状态，不能自动删旧项目。`down --volumes`会删除本次合成数据，之后原Thread ID不再可查询。源码、依赖镜像tag和共享BuildKit缓存不属于该命令的清理证明。

## 历史素材与来源

[八张三轮截图](screenshots/portfolio/README.md)来自V1/e60ee792产品代码，MockTransport / Fixture / TEST_OPERATOR，付款0；[实际来源与哈希](evidence/portfolio-demo/verification.json)。不是本轮新Single截图，也不是L7的真实B2结果。[旧三轮Multi路线全文](history/PORTFOLIO_DEMO-before-v214.md)保留；新增各功能截图在相应指南。**VIDEO_NOT_RECORDED**。
