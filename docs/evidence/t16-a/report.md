# T16-A：Thread-scoped multi-turn context

状态：**T16_A_MULTITURN_OFFLINE_VERIFIED**。

代码和完整离线回归已在新的受控时钟窗口通过。早期全程时钟检测失败和所有回归失败均保留；只在完成独立诊断、进程级保醒及新的前瞻准入后解除本轮环境阻塞。未Push、修改PR/main、部署或读取真实DeepSeek Key；新增真实模型请求0。

## 实现

基于 `bd0f58368bd40e2b479599fa270b30e43703d2b8`，独立分支 `codex/t16-a-multiturn-context`。

- 迁移0007：ThreadContext、不可变 CandidateSet、幂等 ContextMutation，以及 Run 创建时绑定的 context_snapshot。原订单、库存、付款和官方 Checkpointer 内核没有重写。
- 只保留白名单结构化偏好；新预算替换旧预算，明确 CLEAR 删除，当前消息内部冲突先澄清。模型与检索内容不能写入可信偏好。
- 以名单ID、稳定编号、来源Run、商品ID、价格和Catalog Version绑定候选。偏好变化、旧页面、错店铺/用户/Thread、下架、涨价和缺货均不能沿用旧名单报价。
- 启动、PATCH、恢复保留请求身份、版本比较、Thread Lock、Epoch Fence、Journal和持久预算。同一Run的补充输入保留尚未撤销的当前意图；不同Run不继承数量、地址或购买授权。
- 现有 `/agent/workspace` 增加偏好摘要、版本来源、修改/清除、编号卡片与历史Run事件导航。刷新重新登录后可恢复；JWT仍只存内存。
- 推荐重试使用当前Thread偏好，不把旧Run预算或配送信息带回。旧无状态客户端保留原哈希与请求重放；新编号功能必须使用版本和名单绑定。

详见 [协议、存储与操作](../../THREAD_CONTEXT.md)、[局部设计](../../plans/t16-a-multiturn-context.md)。

## 最终命令结果

| 检查 | 实际结果 | 退出码 |
|---|---|---|
| 后端全量 CI_OFFLINE_CORE | 742 passed / 14 skipped | 0 |
| T16最终源码PG/SDK专项 | 29 passed | 0 |
| Vitest | 84 passed | 0 |
| Playwright全量 | 94 passed / 0 retries / 0 skips | 0 |
| Ruff / format、typecheck、lint、build | 通过 | 0 |

新增29项后端、4项Vitest、7项Playwright。旧断言保留，未增加skip、retry或force click。14项旧skip仍为13项真实BGE权重依赖、1项私有Live原件比较。T16检索使用真实PostgreSQL/pgvector与明确标记的Fixture Encoder，不声称验证真实BGE语义质量。

修复后全部命令在同一受控时钟窗口、相同最终源码指纹下重新执行。E2E探针读取已持久化的有效Run约束，而不是把原始请求中的空constraints误作有效状态。命令、源码绑定与原始日志SHA见 [verification.json](verification.json)。

## 三轮和数据库证据

Single/Multi分别完成：300元静音键盘 → 400元无线 → 当前名单第二款、一件、演示宿舍。实际ChatDeepSeek SDK通过受控MockTransport取得不同结构化输入，Supervisor/工具路径随输入变化；没有真实Provider网络调用。

数据库独立连接核对：第二轮版本4；选择后版本5；确认前订单0、提案1；独立Confirmation/Resume后唯一PENDING_PAYMENT订单1、预留1、支付0。价格与商品ID来自服务器不可变名单和最新提案。Checkpoint可重读、Graph结束、事件seq连续不重复。

[数据库终态](database-state.json) · [Multi事件](multi-events.json) · [Single事件](single-events.json)

[400元无线候选截图](screenshots/preferences.png) · [独立确认截图](screenshots/confirmation.png) · [订单回执截图](screenshots/completed.png)

## 失败与修复

原始失败保留于本地忽略目录，公开只给脱敏分类和SHA：[failure-ledger.json](failure-ledger.json)。

- 新环境初次全量705 passed / 32 failed / 14 skipped：31项缺独占项目配置，1项迁移表清单尚未包含新表。补齐合成配置及严格新表断言。
- 新浏览器专项6/7：定位器匹配两个合法错误提示；API确实拒绝下架报价。修改定位范围，未降低业务断言。
- 首次完整浏览器93/94：同一Run两次补充丢失购买意图，是真实回退。保留RED，用结构化补充合并修复；跨Run仍不继承意图。另加撤销测试，过期/下架引用不能阻止用户取消。
- 旧客户端编号缺少绑定的RED：创建Run前拒绝猜测，旧请求幂等回放仍保持兼容。
- 第二次完整浏览器93/94：有效预算仍为500元，旧探针误读原始请求为null。保留50000断言，改读持久化有效快照/节点约束；最终94/94。
- 过时验证曾在发现守卫缺口后主动中断；428 passed / 11 skipped、退出2，未计作通过。测试启动器的本轮残留API已清理，后续使用受控容器停止传播。

一次只读设计审查指出选中ID与报价基线、澄清、旧哈希、CAS/重放顺序和Checkpoint状态问题，均已落实并有测试。没有进行第二次独立终审，不宣称获得终审批准。

## 时钟阻塞与资源

新独立Linux aarch64 VM，PostgreSQL17.11、pgvector0.8.7；浏览器运行于Mac Chromium。旧共享Docker VM、旧容器及全局时间配置没有用于验收或被修改。

初始60秒时钟准入通过；随后完整约4478秒观测中，宿主43次、客体42次触发原定阈值，最大wall/monotonic残差约53.17秒，宿主出现约38ms回退。旧结果没有被删除或改写。只读电源日志显示期间52次Sleep、54次Wake及51次DarkWake，其中包括合盖与Maintenance Sleep；较大跳变与这些记录的时间吻合。该关联不代表已经解释所有细节，也不宣称修复原共享VM。

先前最终命令的约1052秒区间没有采到重大异常，但没有据此事后豁免全程失败。改为一次针对性环境准备：只对本轮进程持有 `caffeinate -i -s -t 1800` 保醒断言，启动前确认开盖，观测到断言后重新做60秒准入；不修改pmset全局配置、主机时间或JWT策略。

随后完整后端、29项PG/SDK专项、所有静态/前端检查和94项浏览器测试在同一窗口执行。连续约462.74秒采集宿主34943、客体41800个样本，重大异常均0，最大宿主/客体偏移变化分别约0.15ms/2.04ms；原阈值不变，准入PASS。断言随进程结束释放，没有保持系统长期唤醒。该结果仅证明受控离线测试时段；新Live仍须新的环境和预算准入。[全部诊断、旧失败与清理](environment-and-cleanup.json)。

本轮runner/PostgreSQL OOMKilled=false、重启0。测试结束时test_/cp_ schema、Advisory Lock、其他数据库会话均为0。只关闭本轮命名资源；保留历史容器、数据和本轮独占数据库Volume。受保护的137个公开基线文件（证据、Frozen配置/数据、许可及锁）一致。[隐私、许可及工作树核对](privacy-and-integrity.json)。

## 后续边界

T15-B1只证明旧提交617cdf29的一次指定购物Smoke。T16源码指纹已变化，真实Live多轮为NOT_RUN。后续在新的Live环境重新核对时钟、当前价格及源码绑定，再按 [待授权Smoke方案](live-smoke-proposal.md)单独申请模型、费用、调用及范围授权；不复用B1许可或账本。本轮未执行远程CI、Push或发布。
