# 5–7分钟无Key演示

展示目标是“自然语言建议 → 可信提案 → 用户独立确认 → 唯一待支付订单 → 读回原工作流”。**SDK MockTransport / Fixture Embedding / 合成数据 / TEST_OPERATOR**；FastAPI、PostgreSQL、业务事务与官方Checkpoint真实运行。没有真实付款、退款、Provider请求或部署。

V2.16 的三条 SDK MockTransport 浏览器业务链已通过本轮 [9项产品场景](../frontend/tests/product-demo.spec.ts)，分别独立核对 SQL；[当前回执](evidence/v216/verification.json)与 V2.15 基线 CI 分开。以下是可手动复现的讲解脚本，自动化点击属于明确的合成 TEST_OPERATOR 操作，不是实际人类测试研究。V2.14 Release仍 **ON_HOLD**，V2.15已合并但未发布，V2.16仅本地候选；**VIDEO_NOT_RECORDED**。

## 演示前准备（不计入6分钟）

需要Docker、支持 `!override` 的Compose v2和本仓库。首次构建会获取基础镜像及锁定依赖；镜像/依赖准备好后，运行不需要Provider网络、Key或模型权重。标准冷机器构建不是已验证的全离线能力。

在仓库根目录操作。Mac例子使用 `desktop-linux`；其他环境显式换成已核对的Docker Context，不修改全局Context。项目名须独占；发现同名历史资源或端口占用时换名称/端口，不停止未知进程。

```sh
export COMPOSE_PROJECT_NAME=agentmall-v216-fixture-demo
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
  runner python scripts/demo.py --catalog-profile legacy --prepare-return --seconds 900
```

保持这个终端在前台。`--env-file /dev/null`避免Compose自动读取本地`.env`；不附加真实Key、旧PGDATA或私有配置。脚本只在新建容器/临时Schema中运行，禁止复用业务Schema。公开演示账号和测试标签均为合成配置。

`--prepare-return`通过正式 API 准备一笔合成 DELIVERED 原订单，包括独立的**测试环境模拟付款与发货**；这不属于演示中的新购买，也不是真实资金。先记录控制台 `delivered_order_id`，后续核对付款/订单增量时减去这份初始化基线。不执行任何用户 Agent Run，不自动批准演示 Proposal。

第二个终端选择既有 `context-catalog` 程序：

```sh
curl --fail --silent --show-error http://127.0.0.1:8026/__test/health \
  -H 'X-E2E-Key: agentmall-local-e2e'
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"context-catalog"}'
```

健康标识应为 `fake-model-real-fastapi-postgresql`，程序返回 `MOCK_TRANSPORT`、`real_model_calls=0`。`/__test`只属于专用测试入口，不对公网开放；普通 `agentmall.main` 默认MODEL_DISABLED。不要在运行中切换程序或reset。

## 5–7分钟讲解脚本

打开 `http://127.0.0.1:5196`，公开合成账号 `buyer1` / `AgentMall-demo-2026!`。进入工作流，执行模式选 **Legacy Sync**，不勾选 Durable Async。先用 Single Thread 展示A/B，再用新 Multi Thread 展示C。

| 时间 | 操作/讲解 | 核对事实 |
|---|---|---|
| 0:00–0:40 | 展示 OFFLINE DEMO / MOCK MODEL，解释 FastAPI、PG、LangGraph、RAG | 模型为受控回包；真实BGE专项与Demo的Fixture Embedding分开 |
| 0:40–1:30 | A：输入“推荐三款400元以内支持无线连接的静音键盘，不要购买。” | 比较表3款、真实价格/库存快照、独立GET当前状态；订单增量0 |
| 1:30–2:20 | B：输入“就买第二款，一件，送演示宿舍。” | WAITING_INPUT；核对商品、数量、金额、地址、政策、快照标识；批准前无新订单 |
| 2:20–3:00 | 明确选择批准并继续；打开订单，刷新重登恢复同Thread | 唯一PENDING_PAYMENT、库存预留1、付款增量0，刷新不重放购买 |
| 3:00–3:30 | 原Run已终态后，切换下方return_replace程序，新建Multi Thread | 不在运行中更换程序；使用控制台的原订单ID |
| 3:30–4:30 | C：申请质量退货并购买替代商品；检查后批准第一份退货提案 | Case REQUESTED新增1，新订单仍未产生，无退款 |
| 4:30–5:30 | 检查第二份CHECKOUT；再次独立批准 | 不同Proposal/Confirmation；第二份批准才新增待付款订单 |
| 5:30–6:30 | 展示时间线、SQL投影、失败场景和L8历史分母 | 已提交Case不会因后续失败消失；1/5历史成绩不被本轮Mock覆盖 |

切换C（**仅在原Run已终态**）时，将下面值替换为本次初始化输出的合成订单ID，不抄历史ID：

```sh
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"return_replace","order_id":"本次delivered_order_id"}'
```

C输入：`订单<本次ID>有质量问题，申请退货；然后推荐另一款500元以内静音键盘，准备购买一件，送演示宿舍。` 两次均先审阅实际快照，再明确点击批准或拒绝；第一份确认不能授权第二份。按钮由用户触发，前端通过独立 Confirmation / Resume API 提交，未额外直接调用订单/售后写接口。

### 拒绝与安全失败

用全新的演示环境运行反例，不复用已执行交易或未结束的Run：

- A：明确“不要购买”时没有Proposal/订单；选择 `missing_usage` Mock程序验证UNKNOWN停止。
- B：审批时选择拒绝，订单/预留增量0；浏览器测试另在Proposal创建后下架该合成商品，证明过时快照不允许下单。
- C：拒绝退货不会自动购买；独立的购买意图仍可能生成新提案，须另行检查并决定；`return_wire_failure` Mock程序在退货已提交后注入非法响应，原校验层以PROVIDER_TOOL_INVALID停止，Case和已消费确认仍保留。

`/__test`只用于本地专用测试入口，不能公开部署。演示程序不是任意自然语言模型，不推断真实DeepSeek完成能力。本轮实际截图和来源见[验证材料](V216_PRODUCT_DEMO.md#浏览器与数据库证据)。

## 展示与核验范围

页面展示“待支付”、确认卡和事件；不把HTTP200或回答文字当数据库Oracle。自动化验证入口是[多轮浏览器测试](../frontend/tests/multiturn.spec.ts)、[下单测试](../frontend/tests/purchase.spec.ts)、[订单幂等/并发](../backend/tests/test_order_concurrency.py)、[Checkpoint恢复](../backend/tests/test_checkpoint_resume.py)。V2.15另有[两次独立确认与后续解析失败回归](../backend/tests/test_v215_workflow.py)、[用户失败反馈回归](../backend/tests/test_v215_failure_feedback.py)、[安全诊断回归](../backend/tests/test_v215_model_diagnostics.py)。V2.16三场景实际执行结果见[本轮回执](evidence/v216/verification.json)；测试环境与手动演示依赖准备分开披露。

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
