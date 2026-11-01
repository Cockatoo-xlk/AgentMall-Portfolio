# Real Agent 展示与安全运行手册

本源码的默认演示是 **Fixture**，普通FastAPI是 **MODEL_DISABLED**。真实SDK注入只通过受门禁保护的Live入口。不得更换页面文字把Fixture称为DeepSeek。

已核验的真实运行属于历史提交617cdf29：一次合成静音键盘场景，7次真实Provider请求、人工确认、唯一PENDING_PAYMENT订单；[公开摘要](evidence/t15-c/b1-public-summary.json)只适用于该版本。T15-C改变了源码指纹，**CURRENT_SOURCE_LIVE_VERIFIED=NOT_RUN**。旧B1授权、Session和账本均已使用，不能继续调用。本手册不是付费许可。

## 无Key演示（默认、可公开复现）

使用[README Quick Start](../README.md#无-api-key-的-quick-start)的新独占目录/Compose项目。首次构建安装锁定依赖，需要软件包网络，不调用聊天模型。登录合成buyer1，打开 `/agent/workspace`；服务端必须显示 `Fixture · Fake Model`。不要开放测试控制API到公网。

输入“找一款300元以内静音键盘准备购买，送演示宿舍”→核对Supervisor路由和Specialist工具→WAITING_INPUT→本人读取不可变快照并批准→订单PENDING_PAYMENT。购物车来源订单在创建事务中安全消费；Agent独立SKU下单不清理购物车。模拟付款必须另外准备提案并独立确认，是真实数据库状态变化，但无真实资金。

## 准备新Live窗口（以下需要新的独立批准）

1. 在新的独立工作副本核对Git/锁文件、CPU/内存、Docker、三个端口归属。`agentmall-playground-local` 固定使用宿主55441/8017/5187，容器内部55433。若已有任何同名项目或历史`.playground`，停止并辨认归属；不能删账本、覆盖环境、移走原数据后假装全新环境。现有B1环境不得被本版本改造；需要新独占环境时另行批准。
2. `.playground`私有目录700，配置/内部DSN/JWT/Policy/审批记录600；均保持Git和Docker构建上下文忽略。真实Key仅安全加载到未来批准后的服务端环境，不进Git、命令字面量、浏览器、Vite、截图、终端回显、日志、共享环境转储或`docker compose config`输出。禁用SDK debug和外部Tracing。
3. 先在**没有任何Provider变量的干净子环境**构建镜像、核验BGE和初始化；不要因为Compose只是`--describe`就把真实Key注入容器。项目使用固定BGE Manifest（6文件尺寸/SHA、Revision、512维），缺权重即停止，不改用Fixture embedding。真实加载、CPU推理、pgvector写入/检索及内存峰值必须另有无Key准入回执。旧机器约1.91GiB曾OOM；Live基线实际峰值762MiB/上限1024MiB，不代表任何机器都足够。全局Docker设置和其他容器保持不动。
4. 在受控容器内部执行初始化，生成新environment UUID及test_/cp_，两份schema COMMENT必须匹配。绝不从Mac宿主直接用内部55433连接，因为它可能属于历史实例。只在全部新资源已获确认后运行下列命令；使用独立空`--env-file`和必要的本地私有覆盖配置。原示例口令是公开合成值，实际Live应按本地安全策略在私有覆盖中设置自己的专用数据库口令，不输出DSN。

```sh
# 以下是操作路径，不是自动批准或本轮实际执行命令。
docker compose -p agentmall-playground-local -f compose.playground.yaml up -d --wait postgres
docker compose -p agentmall-playground-local -f compose.playground.yaml build server
docker compose -p agentmall-playground-local -f compose.playground.yaml run --no-deps --rm server python -m agentmall.playground --init-environment
docker compose -p agentmall-playground-local -f compose.playground.yaml run --no-deps --rm server python -m agentmall.playground --describe
```

5. 从最终镜像`--describe`获取准确新source_sha256。只读核对DeepSeek官方当前模型/Function Calling/价格，记录UTC price_checked_at，Policy最多24小时有效。当前代码协议固定deepseek-flash、非思考function tools；如官方支持或价格不再匹配，停止，不能静默更新Policy。不要使用README历史价格作新报价。新的session/environment/source/policy hash、场景、请求数、输入输出Token、费用上限和总秒数全部需要权利人明确批准；图内预算与全局账本取严格者。
6. 取得真实新授权后才按现有`validate_approval`契约记录真实approval_reference。仓库没有可复用的approved=true文件。**不复用B1/T12任何授权**。`--check`必须在正确容器内执行，且仍不读取Key：

```sh
docker compose -p agentmall-playground-local -f compose.playground.yaml run --no-deps --rm server python -m agentmall.playground --enable-live --check
```

7. 只有全部门禁及真实资源检查通过，才安全注入批准的Key并启动。固定当前已审镜像、无pull/无自动重启，预设不超过授权窗口的外部停止计时器，并保留容器ID。输出不足/Usage未知/Provider错误保留预算预留并停止，不能自动追发；SDK retries=0。启动入口与前端保持分离：

```sh
# 仅在另行批准后的Live服务端环境中；实际操作需带已审私有覆盖文件。
docker compose -p agentmall-playground-local -f compose.playground.yaml run --no-deps --name agentmall-authorized-live-once server python scripts/playground_server.py --enable-live
# 另一终端无Provider环境，仅传本地API地址；端口占用即停止。
cd frontend
AGENTMALL_API_TARGET=http://127.0.0.1:8017 npm run dev -- --port 5187 --strictPort
```

对新版本运行前必须重新做以上准入；不能直接照抄历史B1环境标识或价格/账本。镜像默认server内存768MiB不等于已验证足够，B1用已审私有1024MiB覆盖；资源不足就BLOCKED，不降低Guard。

## 页面中应展示什么

- `/agent/runtime?run_id=...`经过认证提供Fixture / Live / MockTransport / MODEL_DISABLED。Live已启用但没有有效回执时明确显示“尚无有效Provider回执”。MockTransport是离线SDK测试，不是Live。
- 费用区分SDK预留尝试、有效回执、输入/输出Token、未知Usage、估算上界、实际平台账单UNKNOWN及本地上限。UNKNOWN不当作0。预算停止后先读资源，不能新建Run规避。
- RunTimeline来自持久RunEvent，展示Supervisor路由、Handoff、工具名/结果/耗时、模型Usage。结构化记录可展开，无完整模型对话或原始内部思维。
- 提案倒计时由GET响应头`X-Server-Time`（数据库clock_timestamp，客户端附加展示字段server_time）与浏览器单调时钟估计，浏览器日历时钟不授权。到零后暂停新确认，最多自动GET一次当前快照；只有服务端EXPIRED才提示新提案。查询失败是待核对，不能伪装业务失败或自动重新报价。没有server_time时显示UNKNOWN，可手动刷新。
- 某些系统休眠会暂停单调时钟，唤醒后估计可能滞后；先点击“刷新提案状态”重新获取服务端时间。倒计时从不替代服务端的过期检查。
- 批准购买与购买预算授权是两件事。用户必须亲自读取当份快照并点击；退货/替代购买各自独立确认；Agent没有批准购买、付款或退款的工具。

## 刷新、登录和恢复

1. 保存非秘密Thread ID或工作区URL；JWT仅内存，刷新后重新登录相同合成买家。浏览器保存ID不授予对象访问权。
2. 在恢复框输入原Thread，GET Thread取最新Run和pending_confirmation；事件从seq0重建且去重。先看runtime全局预算、原提案和业务回执。
3. WAITING_INPUT：仅操作当前interrupt，检查服务端有效期；旧confirmation不能用于第二份提案。提案已过期后需手动明确重新报价，再独立批准；新Run可能产生付费调用，必须在新授权范围内。
4. PARTIAL/FAILED或响应丢失：先GET原Thread、Proposal及Order/Case。业务已提交就展示已有资源；保留原request_id、run_id、interrupt_id、proposal_id、confirmation_id与Key，不能用新随机ID盲目重试。
5. `恢复原 Run`/Recover可能继续模型节点，并非纯读。只在原批准窗口/预算仍有效、结果已核对且操作者明确操作时使用；已发送但缺Checkpoint的模型步骤会MODEL_REPLAY_BLOCKED，宁可停止，不能保证外部模型exactly-once。不要因为余额尚有剩余而重启结束的B1。
6. 只重试推荐必须是合法独立任务且原Case保留，不重复申请；没有安全子任务入口时说明限制。Case REQUESTED/人工Ticket RESOLVED不等于退款。

## 停止与核对

仅停止本次记录的容器ID/进程组；不`down`未知项目、不删volume、不重置数据库。等待请求停止，记录实际退出码、时限、OOM事件、预算和HTTP未知结果。读取独立连接终态（订单/库存/确认/业务事件/RunEvent/Checkpoint），确认Advisory Lock、ServerLease和会话已释放。

保存私有元数据账本和证据；含Key容器移除前只读State/内存等安全字段，不能导出Config.Env。为避免错误使用剩余预算，关闭模型服务，不自动重启。本人授权的停止/失败也要保留，不能挑绿色截图。之后发布只能提交审阅过的脱敏摘要；原始授权、Live Ledger、私有Checkpoint及密钥永不进入Git或Actions Artifact。
