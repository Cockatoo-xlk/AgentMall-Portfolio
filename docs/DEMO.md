本页保留历史Fixture演示步骤；当前录制请先读[Real Agent手册](REAL_AGENT_DEMO.md)和[3–5分钟脚本](DEMO_RECORDING_SCRIPT.md)。T15-B1仅在旧617cdf29提交完成一次真实场景，新版本Live仍NOT_RUN；VIDEO_NOT_RECORDED。

# 3–5分钟合成业务演示

按[首页](../README.md)启动隔离Compose及 `scripts/demo.py --prepare-return --seconds 900`。这是Fixture Model + 真实FastAPI/PostgreSQL/Checkpoint，准备订单由脚本独立确认并模拟付款，不是模型自主支付。

| 时间 | 操作 | 核对事实 |
|---|---|---|
| 0:00–0:30 | buyer1登录，打开“工作流”，指出Fixture标识；创建multi Thread | 当前服务使用Fake Model，JWT只存内存 |
| 0:30–1:15 | 输入“找一款300元以内静音键盘准备购买，送演示宿舍” | Supervisor/Handoff时间线；WAITING_INPUT只生成提案，没有新增订单 |
| 1:15–1:50 | 阅读快照，点击“批准并继续工作流”，查看订单 | 原Run Resume；新增PENDING_PAYMENT订单，不等于已付款 |
| 1:50–3:30 | 复制启动输出的delivered_order_id；新Run输入“订单<该UUID>质量问题想退掉，再帮我推荐一款500元以内静音键盘，准备购买，送演示宿舍。” | 第一次批准创建REQUESTED Case；第二张购买提案用新的confirmation再次批准；退款数仍0 |
| 3:30–4:15 | 刷新，重新登录同一买家，恢复原Thread | 数据库重建事件与真实资源，不新建原业务动作 |
| 4:15–4:45 | 说明失败、费用和许可边界 | UNKNOWN Usage、PARTIAL保留；无真实资金，也无生产负载或SLA验证 |

返回/重复确认/回包丢失的真实浏览器与SQL断言见[return_replace.spec.ts](../frontend/tests/return_replace.spec.ts)。网络不确定先GET核对原Thread/Proposal/Order/Case，保持原request_id，不自动重做业务。

以下是原T13合成Fixture演示截图，R2已审阅像素、R4核对SHA及PNG元数据，非本轮新Live或录屏：

- [购物完成](screenshots/shopping-completed.png)：PENDING_PAYMENT。
- [退货及替代购买](screenshots/return-replacement-completed.png)：两份确认，Case仍REQUESTED。
- [移动端恢复](screenshots/recovered-mobile.png)：刷新后登录恢复。

录屏状态VIDEO_NOT_RECORDED。端口占用或运行失败时保留错误，不能把历史截图称为现场成功。不要对公网开放测试控制接口。退出后等待本次进程/schema清理，按首页只停止本项目容器。


## T14-P0本地购物闭环

本节仅适用于包含T14-P0改动的本地开发分支，公开main是否包含这些改动应以具体提交为准。可沿用上述工作流创建订单，然后在同一个订单详情页付款；普通购物车也使用完全相同的详情页。

1. buyer1登录 → 商品加入购物车 → “生成购买提案” → 阅读购买快照 → “确认并创建订单”。订单此时是PENDING_PAYMENT，尚未付款。
2. 在订单详情点击醒目的“模拟付款”。核对服务端支付快照中的订单编号、金额、CNY、有效期及提案状态。
3. 单独点击“批准并模拟付款”。这会创建支付提案自己的Confirmation，与购买确认分开。页面查询原提案内的支付回执，再GET订单，显示SUCCEEDED与最新PAID状态；后续若已发货则仍显示真实最新状态。
4. 拒绝只记录reject；后端DECLINED不等于已支付。订单/提案过期或版本变化必须按服务端状态处理，重新准备的新快照仍需再次确认。
5. 连接中断时点击“核对付款结果”；已有approve可在核对后显式“继续已批准的模拟付款”，沿用原Key。刷新后重新登录同一买家会恢复本标签页的非秘密付款引用并只读查询，不自动执行付款。JWT仍只在内存。

在新的独立环境启动本分支（端口占用先辨认，不停止既有演示）：

```sh
docker compose -p agentmall-payment-local -f compose.ci.yaml -f compose.payment-local.yaml build runner
docker compose -p agentmall-payment-local -f compose.ci.yaml -f compose.payment-local.yaml up -d --wait postgres
docker compose -p agentmall-payment-local -f compose.ci.yaml -f compose.payment-local.yaml run --rm runner python scripts/demo.py --seconds 900
```

宿主浏览器打开 http://127.0.0.1:5184 ，OpenAPI为 http://127.0.0.1:8014/docs 。脚本打印的5174是容器内部地址，本覆盖配置映射为宿主5184。数据库是本目录专有 `.t14-p0/demo-postgres-data`，宿主55438；不使用历史55432/55433/55434及现有8001/5174演示。测试项目与本演示项目不得同时占用这组新端口；先完成测试清理再启动。结束后只对agentmall-payment-local执行相同两个-f文件的down，不加-v，不清理他人数据。

模拟付款的浏览器/独立SQL断言见[payment.spec.ts](../frontend/tests/payment.spec.ts)。本轮不录制视频，VIDEO_NOT_RECORDED；Fixture浏览器闭环通过也不等于真实支付或真实模型质量验收。

## T14-P1本地购物车结算

在T14-P1独立worktree使用新项目及新端口，先确认端口归属，不能停止现有演示来腾出端口：

```sh
docker compose -p agentmall-t14-p1 -f compose.ci.yaml -f compose.cart-local.yaml build runner
docker compose -p agentmall-t14-p1 -f compose.ci.yaml -f compose.cart-local.yaml up -d --wait postgres
docker compose -p agentmall-t14-p1 -f compose.ci.yaml -f compose.cart-local.yaml run --rm runner python scripts/demo.py --seconds 900
```

宿主网页5185、API8015、数据库55439；脚本打印的5174为容器内部地址。PGDATA只属于本worktree的`.t14-p1/postgres-data`，不能与其他目录共享。`compose.cart-local.yaml`只调整本轮资源、端口和本地输出；没有调整全局Docker或远程CI配置。默认Playwright仍使用原端口及浏览器；新增managed模式允许本机完整Chromium headless连接本轮容器服务。

买家登录 → 加入A → 生成提案 → 确认并创建订单：此时订单待支付、购物车已由服务器消费，徽标为0。再独立确认模拟付款，购物车仍为空。若在提案之后修改数量、重新加入A或新增B，订单仍可采用原快照，但购物车保留并显示核对提示。Agent独立商品下单保留已有购物车。提案页恢复出已完成回执时也主动核对购物车，无需先打开订单详情。

页面刷新后需重新登录。查询购物车失败时数量显示待核对，不显示虚假的空车；重读服务端状态，不重复下单。源码及真实SQL断言见[cart_checkout.spec.ts](../frontend/tests/cart_checkout.spec.ts)。保留`VIDEO_NOT_RECORDED`、Fixture模型及合成资金标识。

离线CI可使用相同隔离配置运行runner，命令及分阶段资源限制以[T14-P1验收](evidence/t14-p1/report.md)为准。输出位于`.t14-p1/manual-ci`和`manual-playwright`；已有日志时脚本拒绝覆盖。结束后只对获确认属于本worktree的`agentmall-t14-p1`项目执行相同配置的down，不加-v，不清理他人数据。


本轮完整浏览器回归采用下列分离方式：先启动上述独占PostgreSQL，安装锁定的本机前端依赖及项目内Chromium，再运行：

```sh
npm --prefix frontend ci
cd frontend
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" npx playwright install chromium
AGENTMALL_E2E_MANAGED_DEMO=1 NO_PROXY=127.0.0.1,localhost npm run test:e2e
```

managed模式由Playwright启动并回收固定名称的`agentmall-t14-p1-native-servers`，禁止复用已有网页服务。FastAPI、真实数据库与Checkpoint仍在本轮容器网络内使用受保护的55433；宿主只通过8015/5185访问。1 worker、0 retries、全部场景和断言保留。Mac headless shell最小探针曾渲染0帧并点击超时，改用同版本完整Chromium headless后探针和完整回归通过；没有force点击或关闭交互检查。不要同时运行手动演示和managed测试。此配置须先检查新端口空闲及本机资源，不修改其他演示环境。
