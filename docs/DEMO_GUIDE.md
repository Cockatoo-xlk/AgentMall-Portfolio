# 5–7分钟无Key演示

展示目标是“自然语言建议 → 可信提案 → 用户独立确认 → 唯一待支付订单 → 读回原工作流”。**SDK MockTransport / Fixture Embedding / 合成数据 / TEST_OPERATOR**；FastAPI、PostgreSQL、业务事务与官方Checkpoint真实运行。没有真实付款、退款、Provider请求或部署。

本轮V2.15新演示 **NOT_RUN**；以下复用已有脚本和Fixture程序，不声称当前版本已重新演示。V2.14 Release仍 **ON_HOLD**，V2.15未发布。历史截图仅用作操作参考，**VIDEO_NOT_RECORDED**。

## 演示前准备（不计入6分钟）

需要Docker、支持 `!override` 的Compose v2和本仓库。首次构建会获取基础镜像及锁定依赖；镜像/依赖准备好后，运行不需要Provider网络、Key或模型权重。标准冷机器构建不是已验证的全离线能力。

在仓库根目录操作。Mac例子使用 `desktop-linux`；其他环境显式换成已核对的Docker Context，不修改全局Context。项目名须独占；发现同名历史资源或端口占用时换名称/端口，不停止未知进程。

```sh
export COMPOSE_PROJECT_NAME=agentmall-v215-fixture-demo
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml ps -a
lsof -nP -iTCP:8026 -iTCP:5196 -sTCP:LISTEN
```

仅在该Compose项目查无容器且端口空闲时继续。`lsof`无匹配退出1表示未找到监听。若端口已占用，设置 `AGENTMALL_DEMO_API_PORT` / `AGENTMALL_DEMO_WEB_PORT` 为两个空闲端口，并替换后续URL。

```sh
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml config --quiet
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml build runner
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml up -d --wait postgres
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml run --rm --no-deps \
  runner python scripts/demo.py --catalog-profile expanded --seconds 900
```

保持这个终端在前台。`--env-file /dev/null`避免Compose自动读取本地`.env`；不附加真实Key、旧PGDATA或私有配置。脚本只在新建容器/临时Schema中运行，禁止复用业务Schema。公开演示账号和测试标签均为合成配置。

第二个终端选择既有 `context-catalog` 程序：

```sh
curl --fail --silent --show-error http://127.0.0.1:8026/__test/health \
  -H 'X-E2E-Key: agentmall-local-e2e'
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"context-catalog"}'
```

健康标识应为 `fake-model-real-fastapi-postgresql`，程序返回 `MOCK_TRANSPORT`、`real_model_calls=0`。`/__test`只属于专用测试入口，不对公网开放；普通 `agentmall.main` 默认MODEL_DISABLED。不要在运行中切换程序或reset。

## 六分钟脚本

打开 `http://127.0.0.1:5196`，使用公开合成账号 `buyer1` / `AgentMall-demo-2026!`。进入工作流，新建 **Single Thread**，执行模式选 **Legacy Sync**。

| 时间 | 操作/讲解 | 核对事实 |
|---|---|---|
| 0:00–0:40 | 展示Mock/Fixture标签与架构边界 | 真实后端 + 受控模型回包；不是DeepSeek实况 |
| 0:40–1:30 | 输入“推荐300元以内的静音键盘，不要购买。” | 返回当前目录候选和工具事件，订单增量0 |
| 1:30–2:20 | 输入“我改主意了，要支持无线连接的，预算提高到400元。” | 保留静音偏好，预算替换400，出现新的候选集合 |
| 2:20–3:15 | 输入“就买刚才推荐的第二款，一件，送演示宿舍。” | 当前第二款绑定Product ID；WAITING_INPUT；展示数量/价格/地址快照，尚无订单 |
| 3:15–4:10 | 以TEST_OPERATOR审阅后独立批准并继续 | 唯一PENDING_PAYMENT订单，付款增量0；不要点击模拟付款 |
| 4:10–5:10 | 打开订单详情；刷新并重新登录、恢复原Thread | 原订单和时间线可读，不发送新购买请求，不产生第二订单 |
| 5:10–6:00 | 打开[评测报告](EVALUATION_RESULTS.md)，解释1/5和UNKNOWN | 已评分20%不是15题通过率；08未定责，完整实费UNKNOWN |

名单、按钮和SKU按当前页面为准，不从历史截图抄ID。Mock协议里的模型名、Token和费用不是Provider用量/账单。历史[Proposal截图](screenshots/portfolio/04-proposal-confirmation.jpg)、[订单详情](screenshots/portfolio/06-order-detail.jpg)、[Thread恢复](screenshots/portfolio/07-restored-thread.jpg)及[来源哈希](evidence/portfolio-demo/verification.json)可作为备用讲解材料，须一直标注历史Mock/Fixture来源。

## 展示与核验范围

页面展示“待支付”、确认卡和事件；不把HTTP200或回答文字当数据库Oracle。自动化验证入口是[多轮浏览器测试](../frontend/tests/multiturn.spec.ts)、[下单测试](../frontend/tests/purchase.spec.ts)、[订单幂等/并发](../backend/tests/test_order_concurrency.py)、[Checkpoint恢复](../backend/tests/test_checkpoint_resume.py)。V2.15另有[两次独立确认与后续解析失败回归](../backend/tests/test_v215_workflow.py)、[用户失败反馈回归](../backend/tests/test_v215_failure_feedback.py)、[安全诊断回归](../backend/tests/test_v215_model_diagnostics.py)。当前验证汇总LOCAL_OFFLINE_VERIFIED；这些测试入口和实现不等于本轮已重演这条浏览器Demo。

解释时间线时，model_request_id只关联本地一次模型调用；Schema/响应哈希来自规范化SDK对象，不是原HTTP字节；响应body.id不是HTTP request-id。OBSERVED_VALID是数字自洽的响应观察，output_budget_state是本地预算状态，不讲成供应商已结算。旧single_agent.Guard不在新捕获范围。[完整字段边界](ARCHITECTURE.md#正式run模型诊断的证据边界)。

面试现场如有时间，可用本次Schema的独立只读连接核对订单、order_items、confirmation消费、库存预留、幂等回执和run_events；避免展示JWT、DSN、原始Checkpoint或私有日志。公开演示不读取L8私有原件、Gold或09—15输入。

Durable Async / Worker、Bundle、商家Copilot和MCP作为独立扩展演示，见[历史完整手册](PORTFOLIO_DEMO.md)。它们不挤入这条主线；没有Worker时202后QUEUED应如实显示。不要现场随机kill历史服务或将受控程序说成开放式语义模型。

## 停止与自有资源清理

保存合成结果后，在Demo前台终端按Ctrl-C。脚本尝试停止自有API、Vite/Worker并清理临时Schema；只凭退出码不能宣称全部已清理。历史停止异常保留于[原报告](history/PORTFOLIO_DEMO-before-v214.md#停止及清理)。

仅在确认仍为本次新建项目名后，删除该项目的合成数据：

```sh
docker --context desktop-linux compose --env-file /dev/null \
  -f compose.ci.yaml -f compose.portfolio-local.yaml down --volumes
docker --context desktop-linux ps -a --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
docker --context desktop-linux volume ls --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
docker --context desktop-linux network ls --filter label=com.docker.compose.project="$COMPOSE_PROJECT_NAME"
```

三项查询无资源行才可记录这组资源查无；失败/未知保留实际状态。该操作会删除本次合成Thread数据，不清理旧项目、共享BuildKit缓存或历史L8资源。
