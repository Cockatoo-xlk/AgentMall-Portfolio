# AgentMall T14-P0 本地模拟付款验收

## 结果与范围

IMPLEMENTED / FRONTEND_BUILT / REAL_PG_PAYMENT_E2E_VERIFIED / CHECKPOINT_REGRESSION_VERIFIED / LOCAL_FIXTURE_DEMO_READY。

在独立worktree `AgentMall-T14-P0-Mock-Payment`、分支`codex/t14-p0-mock-payment`实现。唯一父基线为公开main `17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`。原Private源码、历史、公开main和R5审核目录保持原样；没有Push、部署、远程Actions、真实资金或付费模型请求。

实际新增/修改33个文件见[完整清单](changed-files.json)，其中产品接线集中在payment.ts、MockPaymentPanel.tsx和Orders.tsx；其余为测试、隔离启动配置、文档和脱敏验收材料。

已证明的是本地Linux ARM64 Docker中的真实PostgreSQL离线流程。REMOTE_CI_NOT_RUN，LIVE_MODEL_NOT_RUN，VIDEO_NOT_RECORDED。本地验收不代表公开main已经更新或生产就绪。

## 页面操作

登录买家 → 商品加入购物车 → 购物车生成购买提案 → “确认并创建订单” → `/orders/{order_id}` → “模拟付款” → 核对服务端订单号、金额、CNY、有效期和提案状态 → **另行点击“批准并模拟付款”** → GET提案回执、GET订单核对 → 显示模拟支付成功及PAID。

从工作流创建的订单也进入同一个订单详情页。只有PENDING_PAYMENT展示可执行付款入口；所有页面明确标注合成数据、不发生真实扣款。购买Confirmation不能用于付款；付款拒绝只记录reject，不执行支付。

异常时显示DECLINED、EXPIRED、服务端版本变化、权限拒绝或“付款结果待核对”。结果未知先GET原提案/回执，再GET订单；用户明确继续时沿用原request_id、提案/执行Key及Confirmation。刷新并重新登录只读取恢复，不自动批准或执行。读到回执但订单GET失败时保留未知状态，不宣告整个流程成功。

## 实际接线与幂等

没有新增支付领域逻辑、路由、模型、迁移或依赖。前端仅使用既有五个API：POST订单payment-proposals、GET proposal、POST该proposal的confirmations、POST订单mock-payments、GET order。回执从GET proposal.result恢复，订单视图整体采用服务器GET DTO。

每次独立支付生成稳定request_id、prepare_key、execute_key；保存proposal_id和confirmation_id。sessionStorage只允许user/store/order命名空间内的非秘密恢复引用，不保存JWT、密码、地址、订单对象或模型对话。引用损坏拒绝写入；存储异常仍允许原引用GET。GET顺序先提案/回执再订单，避免把新回执配上更早的订单状态。

## 验证命令与实测

最终完整命令（本轮隔离覆盖配置保存在忽略目录，配置副本及哈希可由命令回执追溯）：

```sh
docker compose -p agentmall-t14-p0 -f compose.ci.yaml -f .t14-p0/compose-owned.yaml run --name agentmall-t14-p0-final-run --rm runner
```

退出0，总418.721秒。镜像内210个运行、测试和锁文件的哈希与验收源码逐项一致；没有源码挂载替换结果。内部步骤见[verification.json](verification.json)：

| 检查 | 实测结果 | 退出码 |
|---|---|---|
| 新空库迁移、官方Checkpoint、重复Seed | PostgreSQL17.11 / pgvector0.8.7 / Alembic0006；两次均3用户、12商品；Probe清理 | 0 |
| Ruff check / format --check | 均通过 | 0 / 0 |
| pytest --ci-offline-core --strict-markers -ra | 644 passed / 14 skipped / 3既有Jieba警告，251.01秒 | 0 |
| 前端typecheck / lint / build | 均通过 | 0 / 0 / 0 |
| Vitest | 55 passed（基线38 + 新增17） | 0 |
| Playwright全量 | 60 passed（既有43 + 新增付款17），155.829秒，1 worker、retries0 | 0 |
| 独立演示入口及浏览器购物至付款Smoke | 宿主5184/8014入口200；真实UI及独立SQL核对通过 | 0 / 0 |

14项skip没有扩大：13项需要未分发的真实BGE权重，1项需要未分发的私有Live证据。没有重新执行付费实验或封存开发题。后端全量包含原T09恢复/SIGKILL/Thread、T10 Trace、T11并发和不变量、T12授权/预算/Oracle。新增后端两项检查仅扩展受控测试环境；完整最终测试比基线642新增2项。

付款专项17个浏览器用例覆盖：成功并双击、拒付、拒绝、订单到期库存释放、提案过期、陈旧版本重新报价、提交后丢回包、回执已到而订单GET失败、提案回包丢失、确认回包丢失、刷新重登、非待付及跨买家、工作流订单、390px移动端、真实15秒ApiClient超时、丢失未提交reject、存储异常后的只读恢复。没有仅用“成功”文字代替数据库断言。

## 数据库证据

[database-evidence.json](database-evidence.json)保存最终全量执行中的12份合成终态快照及独立演示快照。每份事实从参与业务Session之外新建psycopg连接查询，不读取Session identity map。

- 成功：1订单PAID、1笔mock/SUCCEEDED Payment（29900分）、2份不同提案的Confirmation、1条ORDER_PAID；reserved=0，商品on_hand从20减至19。
- DECLINED：订单仍PENDING_PAYMENT、没有成功Payment，拒付回执持久化；on_hand=20、reserved=1。
- EXPIRED：订单EXPIRED、没有Payment，库存仅释放一次；on_hand=20、reserved=0。
- 丢回包和真正ApiClient超时：GET原提案回执及订单恢复，Payment/事件仍至多一次；没有换随机Key盲目重新执行。
- unknown/reconciled配对：数据库同一订单已PAID、同一Payment已SUCCEEDED。首次订单GET失败时UI显示待核对，随后GET得到同一订单及同一Payment，没有第二次执行。
- 工作流购买：Run COMPLETED、27条真实Checkpoint，订单进入同一付款页，经独立人类付款确认后PAID。没有Agent付款授权。

测试最初尝试改expires_at被数据库不可变触发器拒绝，RED已保留。最终仅在受控测试服务器使用已有时钟注入入口、以PostgreSQL时间为锚；没有绕过触发器或修改领域判断。控制接口沿用仅测试进程挂载、loopback及测试Key保护，生产应用不挂载。

## 失败与审查

完整保存RED、失败和GREEN回执及原始日志哈希，见[failed-attempts.json](failed-attempts.json)、[command-receipts.json](command-receipts.json)。

首次全量退出1：后端644/14及Vitest55通过，Playwright共58项，57通过、1失败；另外两项审查恢复用例是在这次执行之后新增的，最终共60项。失败为既有T10刷新重登时Chromium `Target crashed`。同窗口未观察到Docker OOM事件，根因仍UNKNOWN，不能声称已修复。另有Ruff两处SQL字面量行长错误，修复仅换行，AST和SQL值保持一致。一次独立审查发现两个恢复问题，均先RED后修复；最终完整回归通过。没有通过新增skip、自动重试、调大资源或挑选绿色记录隐藏第一次失败。详见[review.md](review.md)。

独立演示首次把浏览器安排在60秒服务窗口结束后，ERR_CONNECTION_REFUSED；第二次默认代理探测未通过，浏览器未启动，服务器本身正常退出。诊断证实宿主默认HTTP代理探测返回RemoteDisconnected，显式直连loopback返回200，未修改全局代理。随后同一受控90秒启动窗口内完成入口、浏览器及SQL核对。没有为此修改demo.py或业务内核。原始失败全部保留。

## 截图、清理与限制

四张最终执行截图已逐张视觉检查、PNG元数据检查，见[截图清单](screenshots.json)；只含合成商品、订单ID及公开UI，保留Lucide/Feather许可。可查看[独立支付确认](screenshots/payment-confirmation.png)、[支付成功](screenshots/payment-succeeded.png)、[结果未知](screenshots/payment-outcome-unknown.png)、[移动端成功](screenshots/payment-mobile-succeeded.png)。

测试及演示项目均已down，本轮两处PGDATA已清理；退出前schema=0、其他会话=0、Advisory Lock=0，原三容器ID/StartedAt/挂载/端口不变。Private2074个已跟踪文件、203/1479/1595保护组、Private refs/objects/config/index、public297文件及main、R5树`8da9a5c18674520dab92195c279a5faf86c7f710fafe7575697ee0309e687508`全部一致。见[清理](resource-cleanup.json)、[历史保护](historical-integrity.json)。

**可以录制本地Fixture完整购物闭环Demo**：按[DEMO](../../DEMO.md#t14-p0本地购物闭环)在本worktree启动，使用宿主5184新入口；当前进程已停止，未替换既有演示。视频尚未录制。拒付/时钟/陈旧版本为受控E2E注入，不提供普通买家的自选支付结果。持久引用仅在当前浏览器sessionStorage内；其他设备没有这些引用时不能声称完整恢复同一支付操作。服务端认证、对象归属及幂等仍为最终边界。

本地提交身份由`git show HEAD`给出，提交的父SHA必须为上述17f72基线；本报告不嵌入自引用commit SHA。本轮没有改动远程或公开main。下一步只等待用户单独发布授权，不继续功能扩展。
