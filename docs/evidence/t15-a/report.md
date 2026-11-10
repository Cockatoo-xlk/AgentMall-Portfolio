# T15-A — Live Playground 离线实现与验收

状态：**IMPLEMENTED / OFFLINE_SDK_VERIFIED / PG_CHECKPOINT_VERIFIED / FRONTEND_VERIFIED**。真实 DeepSeek **LIVE_AGENT_VERIFIED=NOT_RUN**；付费请求0，未读取真实Key，未执行真实Smoke、Push、部署、Release或远程Actions。不能把本报告的MockTransport成绩称为网页真实模型验收。

## 基线和交付

独立worktree为 `AgentMall-T15-A-Live-Playground`，分支 `codex/t15-a-live-playground`，由核验干净且未变化的 `c06c5841af36a631b69462c035d6410f732af0db` 创建。本地提交SHA由最终交付消息及本目录Git记录提供；本报告本身包含在该提交内。

Native worktree工具不接受该聊天外的R1-A sourceRoot，故使用已授权的 `git worktree add -b codex/t15-a-live-playground ... c06c584...`；没有改动原候选目录。未发现适用AGENTS.md。[历史保护](historical-integrity.json)核对Private、Public、P0、P1、R1-A的HEAD和全部跟踪文件，变化0；203/1479/1595保护集合变化0；R5审核目录297文件变化0。新分支会正常增加共同Git对象及分支引用，没有修改既有提交或main。

[完整改动文件清单](changed-files.json)列出源码、测试、入口、配置、文档和审阅后的合成证据。主要内容：

- `backend/src/agentmall/playground/`：policy、环境所有权、单服务器租约、持久ledger、SDK transport、认证runtime、CLI和显式Live工厂。
- 原`agents/run_service.py`只增加认证调用scope及Provider配置身份；原`agents/routes.py`增加GET `/api/v1/agent/runtime?run_id=...`。未改领域事务、Checkpoint/Epoch内核、库存、付款或购物车服务。
- Workspace新增ProviderPanel及类型校验；Layout使用中性合成数据提示。Single/Multi Thread、Run/Timeline、HITL Resume、恢复、订单详情及T14模拟支付/购物车路径继续使用原API。
- 新增SDK/预算/启动器/PG测试、10项Playwright、6项Vitest；扩展原受控浏览器测试服务，仅离线测试入口可安装MockTransport。普通Live工厂不挂载`/__test`。
- 独立未来Live配置`compose.playground.yaml`；离线配置`compose.playground-tests.yaml`；后端轻量镜像及分别的Live/测试启动器，浏览器与Vite放在Mac宿主机。

[源码身份](source-identity.json)记录最终SDK/策略/工具/前端/迁移/锁文件/启动器的SHA-256：`ee0f6927f30687892159b39272148e8859fe61f406a0e5aa7c48cb5766766687`。宿主与实际测试镜像一致。旧Frozen Manifest保持原样，绑定旧版本，不能授权本版本或当作新实验封存。

## 实际接线和安全边界

普通FastAPI保持模型关闭；Fixture演示保持显式Fixture。只有新CLI显式enable、新用途授权、24小时价格、源码指纹、专属schema COMMENT、可加载的本地BGE及Key全部核验后，才注入5个真实ChatDeepSeek模型角色。Supervisor的route及Specialist function calls由SDK返回，原严格工具协议执行；生产入口没有预设业务步骤或Fake Model。测试证明不同自然语言和不同模型输出走不同领域工具；同一句话换模型route也会换真实工具路径。

认证GET runtime从服务端提供Fixture / MOCK_TRANSPORT / Live / MODEL_DISABLED、本人/本店/本Run的预留尝试、有效回执、Token、费用上界、实际账单UNKNOWN及停止原因。前端不能通过VITE变量自授Live；未观察到回执时明确标识“尚无有效Provider回执”。

发送前在独立私有ledger中flock、原子替换、fsync预留全局次数/输入/输出/费用/总窗口。无scope不发送；SDK retries0、固定HTTPS、无代理/重定向/外部tracing。Provider错误、未知Usage、错误工具/模型/嵌套响应或结果不明保留全额预留并全局暂停，不因新Thread/重启清零。同一已发送节点缺少Checkpoint时阻止自动付费重放，而不是承诺模型exactly-once。Graph预算继续独立持久化。

提案仍由用户独立批准。SDK购买等待时订单0，批准后仅一笔PENDING_PAYMENT；模拟付款再走原详情页新提案和新确认。退货与替代购买分别确认，Case只为REQUESTED；Agent不具备批准付款或退款工具。刷新/登录后GET原Thread、事件和回执，不重复业务。

账本只保存安全元数据、摘要及Usage；公开Trace继续复用持久RunEvent白名单，未写入原始Prompt/对话/思维链/Key/JWT。实际平台账单不可得仍UNKNOWN；MockTransport示例的Token和估算是合成值，不能当作真实消费。[隐私审查](privacy-review.json)、[一次独立审查及修复](review.json)保留边界与证据。

## 完整离线回归

| 检查 | 最终实际结果 | 退出码 |
|---|---|---|
| 后端完整CI_OFFLINE_CORE | **711 passed / 14 skipped**，725 collected；新增41项 | 0 |
| 前端Vitest | **71 passed**，新增6项 | 0 |
| Playwright全量 | **84 passed / 0 skipped / 0 flaky**，新增10项；1 worker / retries0 | 0 |
| typecheck / lint / build | 全部通过 | 0 |
| Ruff check / format | 全部通过 | 0 |
| Compose静态配置 / 本地文档链接 / diff check | 通过，见最终静态回执 | 0 |

实际命令、耗时、日志SHA与JUnit/Playwright JSON摘要见[verification.json](verification.json)、[command-receipts.json](command-receipts.json)、[test-matrix.json](test-matrix.json)。原14项skip仅13个真实BGE文件依赖及1个私有Live原件检查，没有新增skip/retry或降低旧断言。原T09恢复/SIGKILL、T10 Trace、T11并发与T12协议/预算/Oracle均包含于完整后端。没有另行重跑封存40题或历史Live Pilot。

关键复现命令（在该worktree执行；先建立新独占测试PG）：

```bash
docker compose -p agentmall-t15-a-tests -f compose.ci.yaml -f compose.playground-tests.yaml up -d --wait postgres
docker compose -p agentmall-t15-a-tests -f compose.ci.yaml -f compose.playground-tests.yaml build runner
# .t15-a/backend-memory.yaml 内容：services: {runner: {mem_limit: 1152m}}
docker compose -p agentmall-t15-a-tests -f compose.ci.yaml -f compose.playground-tests.yaml -f .t15-a/backend-memory.yaml run --no-deps --rm runner sh -c 'python scripts/ci/bootstrap.py --port 55433 && set -a && . ./.env.rag && set +a && python -m pytest --ci-offline-core --strict-markers -ra'
backend/.venv/bin/ruff check backend evals scripts
backend/.venv/bin/ruff format --check backend evals scripts
cd frontend
npm run typecheck && npm run lint && npm run build && npm test
AGENTMALL_E2E_MANAGED_DEMO=t15 npm run test:e2e
```

实际执行还设置了各EVIDENCE_DIR到忽略目录并保存JUnit，详见命令回执。最后一条默认原购买/工作流测试会把证据写至其既有默认目录；严谨复现应使用回执列出的全部相对路径参数，避免把原始输出加入公开提交。启动器配置默认不复用任何已有监听服务。

平台为**本地Linux ARM64容器后端、Mac ARM64 Node24/完整Chromium headless**，不是Ubuntu amd64远程CI。[版本](versions.json)。仅完整检查集合分阶段通过，不声称单容器一体化CI成功。

## PostgreSQL、Checkpoint与浏览器证据

使用专属项目`agentmall-t15-a-tests`，宿主PG55440/API8016/Vite5186，内部受保护的127.0.0.1:55433/agentmall_test；PG17.11、pgvector0.8.7、迁移0006及官方Checkpoint。空库迁移/重复seed为3用户、12商品，初始化探针自动清理。

[逐场景数据库与SDK摘要](database-and-sdk-evidence.json)来自原测试服务的独立同步数据库连接，不以按钮或HTTP200计数代替业务效果。新10项场景最终均passed：

| 场景 | 实际数据库/SDK证据 |
|---|---|
| Multi推荐 / Multi订单 / Single订单 | 分别4 / 4 / 2次SDK Mock wire；实际retrieve_products / list_orders；订单0；Checkpoint16 / 16 / 13行 |
| 购买、丢失Resume回包、刷新、独立模拟支付 | SDK共6次，刷新及付款不增加模型请求；一笔订单PAID、一笔SUCCEEDED模拟付款、两份独立确认；Checkpoint27行 |
| 退货+替代购买、移动端 | SDK10次；原订单DELIVERED、新订单PENDING_PAYMENT；Case REQUESTED、Refund0；含准备原订单的购买/付款及退货/新购共4份独立确认；Checkpoint44行 |
| timeout / 缺Usage响应 / 非法付款批准 | 每个只1次Mock wire，PARTIAL、订单0、Confirmation0、UNKNOWN/停止；刷新不补发 |
| 未明确数量 | 领域工具返回PURCHASE_DETAILS_REQUIRED，订单及确认0；模型不能替用户补数量 |

“缺Usage响应”浏览器fixture同时缺少强制route，传输层会先以协议错误停止；缺Usage的独立分支另由真实SDK单测覆盖。该差异按实际错误码保留，没有把错误分类改成预期名称。

[RunEvent与Checkpoint例证](run-events-example.json)包含购买恢复后的真实持久事件序列和Graph终态：45条事件、handled原提案、pending_action=null、next=done、pending_writes0。事件来自数据库；模型回执是明确标记的MockTransport。两次购买/售后确认的旧confirmation重放被409拒绝，重复Start/Resume也由PG专项核对仅一笔业务。

已经检查并原样保留的合成截图：[等待独立确认](screenshots/purchase-waiting.png)、[刷新恢复](screenshots/purchase-restored.png)、[独立模拟付款](screenshots/separate-payment.png)、[退货及替代购买移动端](screenshots/return-replacement-mobile.png)、[UNKNOWN后停止](screenshots/timeout.png)。像素/PNG元数据及SHA见[screenshots.json](screenshots.json)。截图不是Live或录屏。

## 失败、审查及资源

[全部已记录失败与归因](failed-attempts.json)及原日志SHA保留，包括TDD预期RED、实际scope重放/费用预留缺陷、一次独立审查发现的两个P1协议边界、测试配置错误、浏览器下载失败、OOM、启动器及UI定位问题。没有只保留最后的绿色结果。

独立审查一次：强制Supervisor route缺失可能触发旧schema-repair再付费；未经检查的嵌套Usage/推理字段可能在SDK解析处失败但账本已结算。3项Mock用例均先RED，之后通过强制tool_choice检查及嵌套白名单重建修复，保留全额预留/停止；最终完整回归包含这些用例。未循环扩展审查。

首次完整后端在640MiB发生实际cgroup OOM、退出137；仅本轮完整后端临时覆盖1152MiB后通过，没有改Docker全局配置。保留Docker oom事件；采样并非准确瞬时峰值，见[资源测量](resource-measurements.json)。Chromium CDN安装退出1/ECONNRESET，随后只读复制本机同版本1248公共依赖，347文件哈希一致，未借用P1源码/证据/凭据或修改原缓存。

早期浏览器启动两次0用例失败（环境继承和本轮端口映射）；一次主动终止已明确失败的本轮浏览器组，退出130，30 passed/4 failed/1 interrupted/48 did not run；后续25/1及83/1均保留。未用force点击、延长断言、skip或retry制造通过。早期“漏数量”失败未保存其完整SQL快照，只有截图/日志；后续新增同输入拒绝测试记录完整终态，不伪造早期证据。

[清理](resource-cleanup.json)：所有本轮test_/cp_ schema0、其他客户端会话0、advisory lock0后，专属Compose down退出0，专属容器0，移除本轮新建PGDATA。原5个PostgreSQL容器ID/StartedAt/mount均不变并继续运行。开始存在的P1演示runner结束且对象已移除，原因UNKNOWN；本轮没有对其发出停止/重启命令，不宣称共享引擎绝无间接影响，也没有擅自恢复。P0历史异常和原有Live限制保留。

## 首次真实Smoke尚需单独批准

[启动说明](../../LIVE_PLAYGROUND.md)与[待批准方案](live-smoke-proposal.md)给出准确模型、官方价格来源、三个合成场景、建议人民币5元/30请求/1200秒/输入4,194,304/输出24,000上限、独立数据库、Key加载、元数据、人工确认和未知结果停止方式。

本轮没有正式`.playground`环境/新授权回执/Live账本；测试仅创建临时合成策略与账本。含真实BGE的Live镜像未构建、模型文件未安装在该worktree，加载与容量尚未实测。下一步必须先准备独占环境和经manifest核验的BGE，重新核对24小时内官方价格，并取得绑定最终源码、环境UUID、新session及policy SHA的具体用户许可。不得用本报告或历史T12许可代替。

真实网络/Provider能力、真实模型选择质量、实际Token和平台账单、Live时延及任意SIGKILL下付费调用exactly-once均未验证。真实Smoke成功前，仍不能宣称“网页真实Agent已验证”。不自动付费、不自动发布或推进后续任务。
