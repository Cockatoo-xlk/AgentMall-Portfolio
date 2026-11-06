# 三轮购物 Demo：Mock 决策，真实业务执行

适合3—5分钟作品集展示。React、FastAPI、PostgreSQL、工具、LangGraph和官方Checkpoint真实运行；模型由受控 **SDK MockTransport** 返回，检索使用 **Fixture Embedding**。这条演示验证应用链路，不验证模型智能或语义向量质量。真实BGE另有[已完成的R8 CI](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/41972687787)。

## 启动

需要Docker及支持`!override`的Docker Compose v2；先用下面的`config --quiet`验证兼容性。本配置使用已有CI镜像构建与Demo启动器，没有新的服务框架。先核对当前Docker Context、本目录归属和端口；不要停止不属于自己的进程。以下在Docker Desktop使用显式context，其他机器应替换成自己已确认的引擎。

```sh
docker --context desktop-linux ps -a
lsof -nP -iTCP:8026 -iTCP:5196 -sTCP:LISTEN
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml config --quiet
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml build runner
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml up -d --wait postgres
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml run --rm --no-deps \
  runner python scripts/demo.py --seconds 900
```

最后一个命令保持前台运行。它会检查新库、迁移、Seed，并启动API/Vite。打开[商城](http://127.0.0.1:5196)，[API文档](http://127.0.0.1:8026/docs)。脚本打印的5174/8001是容器内部地址；宿主访问5196/8026。数据库内部55433，**不发布宿主数据库端口**。使用新项目和专属Volume，不能把历史PGDATA挂进去。约3GiB的服务限额不是完整CI资源需求，也不是Live容量证明。

另开终端，先检查健康返回为`fake-model-real-fastapi-postgresql`、真实模型及外部请求均为0，再选择现有三轮Mock场景：

```sh
curl --fail --silent --show-error http://127.0.0.1:8026/__test/health \
  -H 'X-E2E-Key: agentmall-local-e2e'
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"context-catalog"}'
```

应返回`MOCK_TRANSPORT`、`real_model_calls=0`。该模式复用默认Seed目录，不创建专供演示的假商品；模型决策是确定性测试程序，商品、约束过滤和交易结果仍来自真实后端。页面应显示“DeepSeek SDK · MockTransport（离线，未调用真实模型）”。`deepseek-flash`只是Mock协议中的模型字段，不代表访问了Provider。页面的Token与费用数字为合成回执/预算演练，实际付费请求0。

`/__test`只存在于专用测试入口，公开标签不是安全凭据。只能在独占localhost演示中使用，禁止公网部署。普通`agentmall.main`没有这些控制接口，默认模型为MODEL_DISABLED。不要在有未完成Run的演示中切换或重置Mock场景。

### 本次Mac实际使用的缓存方式

标准构建曾在Docker Hub获取Node元数据时超时；没有改代理、证书或依赖。改用本机已有完整CI依赖镜像，复制当前源码并执行离线锁文件同步，成功构建。仅当本机确实拥有并核对了该可信缓存时可采用。以下命令**替代**标准流程中的`build runner`，成功后直接执行`up`和`run`，不要再次执行标准构建：

```sh
mkdir -p .playground
cat > .playground/portfolio-cached.Dockerfile <<'EOF'
FROM agentmall-t16-a3-runner:local
COPY . /work
RUN uv sync --project backend --locked --offline --no-extra embedding
EOF
docker --context desktop-linux build --network none \
  -f .playground/portfolio-cached.Dockerfile \
  -t agentmall-portfolio-demo-runner:local .
```

本次缓存基础镜像ID为`sha256:9486b157eeeb5cb9ca06ac4484f211fdbb3c794bd83d4d599344b6eb4bd1d159`。其他机器没有此缓存时应采用上面的标准Dockerfile，不下载来源不明的同名镜像。缓存构建只用于本地演示，不是镜像发布。启动器与权限、预算、时钟等产品合同均未改动。

本次现场使用临时项目`agentmall-portfolio-1bd09733`及私有覆盖文件；API/前端端口和服务资源与公开覆盖文件一致。上面的固定项目名用于复现示例，不能据此覆盖其他目录的同名项目。

## 演示实时进度

用本分支源码重新构建并启动上面的独占 Demo。用以下设置替换三轮 Mock 场景配置。延时只用于本地 MockTransport。

```sh
curl --fail --silent --show-error -X POST http://127.0.0.1:8026/__test/sdk-mode \
  -H 'X-E2E-Key: agentmall-local-e2e' -H 'Content-Type: application/json' \
  --data '{"program":"recommend","delay_ms":1250}'
```

以 `buyer1` 登录，在工作流创建 Multi Thread，输入「推荐300元以内的静音键盘，不要购买。」。在右侧时间线观察 `RUNNING` 时的 Supervisor、Handoff 和工具事件，再看 `COMPLETED`。用浏览器网络工具中断连接再恢复，时间线从最后收到的序号补读，刷新并重新登录后可通过原 Thread 查看历史。

购买演示可在当前 Run 结束后，把上面配置中的 `program` 改为 `purchase`，创建新 Thread 并输入「帮我找一款300元以内静音键盘准备购买，送演示宿舍」。到 `WAITING_INPUT` 时核对购买快照，再手动批准并观察 Resume 与业务回执。演示到待支付结束。

## 浏览器六步

| 步骤 | 操作 | 核对 |
|---|---|---|
| 1 | `buyer1` / `AgentMall-demo-2026!`登录，打开“工作流”，创建Multi Thread | MockTransport标识；记录Thread ID |
| 2 | 输入`推荐300元以内的静音键盘，不要购买。` | Shopping→retrieve_products；本次2件候选，提案/订单0 |
| 3 | 输入`我改主意了，要支持无线连接的，预算提高到400元。` | 预算400、静音保留、无线；本次3件候选，记录当前名单ID及第二款 |
| 4 | 输入`就买刚才推荐的第二款，一件，送演示宿舍。` | Order→get_product→prepare_checkout；WAITING_INPUT；确认前订单0 |
| 5 | 核对不可变快照后点击“批准并继续工作流” | 若由自动化操作，注明TEST_OPERATOR；唯一PENDING_PAYMENT订单，付款0 |
| 6 | 打开订单详情；刷新、重新登录，再用恢复面板读取原Thread并展开历史Run | SKU/金额/库存正确，事件和Checkpoint可读；不创建第二订单 |

不要根据这次截图固定选择某个商品。不同检索模式可能产生不同排序；“第二款”始终指浏览器当前名单的rank2和实体ID。本次Fixture是静音K98×1、¥399；历史真实BGE CI中第二款不同是允许的，不能跨名单搬用编号。

本场景到待支付为止，**不要点击模拟付款**。订单详情确有独立模拟支付入口，付款需新的提案及Confirmation，不复用购买批准。若另行录制支付闭环，应明确标为扩展的模拟资金场景，不能继续宣称付款0。

## 本次截图与事实

全部是合成数据，确认操作者为 **TEST_OPERATOR**；不是本人真实购物授权。完整结果及截图哈希见[验收摘要](evidence/portfolio-demo/verification.json)。

- [Workspace模式](screenshots/portfolio/01-workspace.jpg)
- [首轮推荐](screenshots/portfolio/02-first-recommendation.jpg)
- [预算和新候选](screenshots/portfolio/03-updated-candidates.jpg)
- [订单提案与独立确认](screenshots/portfolio/04-proposal-confirmation.jpg)
- [Resume与时间线](screenshots/portfolio/05-completed-timeline.jpg)
- [订单详情](screenshots/portfolio/06-order-detail.jpg)
- [Thread恢复](screenshots/portfolio/07-restored-thread.jpg)
- [当前Run时间线局部](screenshots/portfolio/08-history-timeline.jpg)

本次3个Run均COMPLETED，85条连续事件；官方Checkpoint均`next=done`、`pending_writes=0`。独立只读SQL核对订单/OrderItem/Confirmation/库存：目标on_hand20、reserved1；其他SKU不变；付款0。浏览器刷新重新登录后仍只有同一订单。没有用HTTP200代替这些事实。没有额外扩展Journal采集，直接两字段证据继续NOT_COVERED。

## 3—5分钟录制脚本

| 时间 | 画面 | 讲解 |
|---|---|---|
| 0:00—0:30 | 登录、Workspace模式 | 这是Mock决策、Fixture向量；真实数据库与工作流。不是DeepSeek实况。 |
| 0:30—1:10 | 第一轮、Shopping时间线 | 推荐不等于购买；从目录检索并经过预算/库存/店铺过滤。 |
| 1:10—1:55 | 第二轮、偏好摘要/候选卡 | 结构化版本把预算300替换为400，旧名单失效；按新名单绑定编号。 |
| 1:55—2:40 | 第三轮、Order工具及提案 | 再读最新商品事实，提案不是订单；人工确认前订单数0。 |
| 2:40—3:20 | 独立批准、订单详情 | 标注TEST_OPERATOR；Resume内确定性事务创建唯一待支付订单，未付款。 |
| 3:20—4:15 | 刷新登录、恢复Thread/历史Run | JWT只存内存；数据库和Checkpoint保留结果，不靠浏览器聊天记录。 |
| 4:15—4:45 | 架构图/验收摘要 | 行锁、幂等、HITL是业务边界；历史CI834/85/96，当前Live多轮未运行。 |

`VIDEO_NOT_RECORDED`。已交付截图和逐步脚本；没有录制整个桌面或纳入其他应用、凭据或私人浏览器内容。

## 停止及清理

在前台Demo终端按Ctrl-C，等待子进程退出和临时test_/cp_ schema清理。再对**本次确认属于自己的项目**执行：

```sh
docker --context desktop-linux compose -p agentmall-portfolio-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml down --volumes
docker --context desktop-linux ps -a --filter label=com.docker.compose.project=agentmall-portfolio-demo
docker --context desktop-linux volume ls --filter label=com.docker.compose.project=agentmall-portfolio-demo
```

`--volumes`仅销毁本例新建的合成专用Volume。项目若已经存在不明数据，不执行该命令，先核对归属。不要使用全局prune、删除历史Volume或停止旧容器。停止后临时Thread/订单不可继续查询，应先保存所需截图与合成结果。重新运行会创建新Thread/订单，截图中的UUID不是永久演示地址。

**本次停止异常保留**：`docker stop --time 30`约30.10秒返回后，API两份临时Schema仍在、未观察到最终子进程退出回执；不能称为优雅Schema清理通过，内部原因UNKNOWN。完成业务取证后，核对专属项目/Volume归属，最终删除本次Guest、PG、Volume、网络和新镜像tag并独立查无；原24容器不变。此异常没有修改交易结果，也未触发业务重试。本轮未为此扩大关闭机制开发，复现时须执行上述专属资源清理并核对结果，不能仅凭stop退出0认为清理完成。
