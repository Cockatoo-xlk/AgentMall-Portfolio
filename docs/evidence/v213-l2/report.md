# V2.13-L2 离线回归报告

基线 `342c3c199984efb89bc649dcb3b1892aeb82da41`，分支 `codex/v213-l2-tool-batch-repair`。[实现、错误分类与复测边界](../../V213_L2_TOOL_BATCH_RELIABILITY.md)。[机器回执](verification.json)包含最终源码指纹、原始日志 SHA、实际退出码和清理结论。

## 证据范围

本轮为 Linux aarch64、独立 PostgreSQL 17/pgvector、官方 Checkpointer、SDK MockTransport 与 Fixture Embedding。真实 DeepSeek、当前源码远程 CI 和新真实 BGE 实验均 NOT_RUN。未运行 900 秒监控。

L1 原件记录 9 个真实且已结算请求、6 次工具、两次 INVALID_TOOL_BATCH 和最终 REPEATED_DELEGATION；确认 0、精细 Oracle 的越权业务写入 0。原始参数缺失，具体批次错误子类型仍 UNKNOWN。本轮没有补造参数、改写旧 Oracle 或重新解释旧计数为越权写入。

源码复现证明：旧错误合并导致合法格式错误没有原 Specialist 的局部修复；旧重复签名受 facts、引用和动态排除 SKU 影响。修复后的失败目标身份取可信 Runtime 用户约束，新增任务名、读取来源或原商品引用不能绕过失败目标拒绝。

## A–P 对应

| 场景 | 实际断言 |
| --- | --- |
| A 合法调用 | AIMessage 与 SDK 的合法调用正常扣工具预算并访问原领域服务 |
| B 非法 JSON | 固定 TOOL_ARGUMENT_JSON_INVALID；非法批次工具执行 0 |
| C 重复 Key | 原始消息及真实 SDK wire 均拒绝；不保留 Key 的值，不选择其中一个值 |
| D Schema | 固定分类和已知字段名；未知额外字段不进入日志 |
| E 未授权工具 | 包含在 raw、parsed 或 invalid 任一表示中均不可通过局部修复洗成合法调用 |
| F ID/重复 | 非法、已用 ID、持久预算竞争和已执行写调用均拒绝；工具预算不重复消费 |
| G 混合读写 | 全批拒绝，无部分读取/写入；公共错误码继续兼容旧合同 |
| H 一次修复 | 合法退货工具的 JSON 和 Schema 两种受控错误，在原 Specialist 中各可修复 |
| I 修复耗尽 | AfterSales 用掉一次后 Order 再出格式错误，PARTIAL；不授予第二次机会 |
| J 读取复用 | get_order、check_eligibility、retrieve_policies 各一次；修复轮相同调用被拒绝 |
| K 约束 | 修复反馈保持原订单、50000 分、静音、原 SKU 排除、quantity=1 与演示宿舍 |
| L 重派发 | 新 Task ID、新证据、新发现原 SKU 后均不能重派失败目标；独立持久拒绝事件可读 |
| M 完整 B2 | 两次不同 Confirmation；最终一份新增 REQUESTED Case、一笔新增 PENDING_PAYMENT 订单 |
| N 重放 | 两次 Resume request_id 重放，模型请求、Case、订单及库存预留均不增加 |
| O 错误终态 | 权限、重复 Key、修复耗尽保留 PARTIAL；已经确认的 Case 不被撤销 |
| P 兼容 | 最终完整 pytest / Vitest / Playwright 覆盖 Single、Bundle Replanning、MCP、商家与独立 Worker |

成功 B2 的确定性模型路径：Supervisor → AfterSales 读订单 → 资格/政策 → 被拒绝批次 → 同角色局部修复 → RETURN_REQUEST 确认 → Shopping 推荐 → CHECKOUT 独立确认 → 正常结束。11 次模型、6 次工具、3 次 Delegation；没有提高预算。模型仍选择路由/合法商品，服务端不硬编码 B2 或自动批准。

确认操作属于 TEST_OPERATOR 的独立测试动作。SQL 独立读取 Order/OrderItem、Case、Confirmation、库存和付款：替代 SKU 不等于原 SKU，单价不超过 50,000 分，静音、quantity=reserved=1，付款增量 0。原已交付订单准备包含模拟付款，不能把该数据库的总付款数写成 0。

## 修改范围

| 文件 | 变化 |
| --- | --- |
| agents/model_control.py | 保留公共码的类型化细分、两种表示与全批验证、权限优先、格式修复资格及安全事件 |
| agents/specialists/runner.py | 一次共享修复、保留已验证读取、耗尽事件、失败目标标记 |
| agents/runtime.py | 稳定失败目标身份、拒绝重派发与安全持久事件 |
| agents/specialist_tools.py | 原 Specialist 修复状态标记；领域执行逻辑不变 |
| agents/durable_budget.py | 正确读取已消耗修复状态，复用持久事件标记；限额不变 |
| agents/run_service.py | 对新增已持久事件去重；未改变执行器或交易路径 |
| infra/llm.py | 非流式 SDK 归一化前的固定错误标志，防止重复 Key 信息丢失 |
| infra/observability.py | 固定分类、已知字段/工具名、阶段、权限和预算投影 |
| 三份 test_v213_l2 测试 | SDK、AIMessage、PostgreSQL、权限/共享预算/恢复和隐私反例 |

## 开发与完整回归失败保留

最初 13 项 RED 复现缺失细分、非法批次和重复派发。随后保留：整批权限优先、raw/SDK 参数不一致、畸形结构、重复读取、畸形内部标志、持久 ID 冲突及两项独立审查发现的 RED。审查修正含“原始格式错不能掩盖另一 SDK 表示中的权限或身份/参数冲突”和“发现原 SKU 后失败标记仍稳定”。

中间测试驱动曾误用 Playground 的更严格预校验路径，模型错误在到达 Guard 前被 PROVIDER_TOOL_INVALID 拒绝；改为与 L1 相同的直接 SDK + MockTransport，没有修改或绕过生产 Playground 校验。实现过程中另有诊断写锁等待及 SDK 默认 null 的误判，均保留原始失败日志并修正来源，没有吞掉异常或删安全断言。

第一次累计回归发现旧 Single-Agent 混合读写公共错误码兼容问题：更细的“已用写工具”拒绝不能改变原 UNORDERED_WRITE_BATCH 合同。修正只恢复公共码的优先级；内部 POLICY_DENIED 和 repairable=false 继续生效，不因公共码而授权重试。原失败及最终完整回归分别记录，不以定向结果代替全量结果。

第二次完整回归实际通过 1154 / 原 14 skipped。收尾的 Single 意图反例又证明：畸形但未请求的写操作不能获得格式修复。3 项 RED 后补充修复资格拒绝，67 项相关测试通过，并对该最终源码再次执行完整回归；有效参数的原领域拒绝路径不变。三轮结果分别保留，不将补丁前成绩冒充补丁后成绩。

最终授权修正版完整 pytest：**1157 passed / 14 skipped / 0 failed**，新增 39 项测试全部包含其中。Vitest 127 passed；TypeScript、ESLint、生产构建通过，前端源码在各轮间未变；最终 Python Ruff 与格式检查通过。Playwright 与清理结论完成后统一记录于机器回执。

最终可执行源码 SHA256：`cf5850c08790273036883fd13b3b16a00ee1abc9a04a72d9e20091d127d3cac2`（441 个文件）。具体原始日志 SHA 见机器回执；原有 14 项 real_bge skip 保留，未新增 skip/retry，未修改历史 Oracle 或冻结答案。

## 安全与剩余边界

74 份交易、权限、GraphBudget 限额、StateGraph、Checkpoint、Epoch Fence、Single 旧实现、迁移、锁文件及冻结数据等保护文件核对未变。新增诊断仅包含固定枚举、字段名和已验证工具名，没有 Prompt、原始参数、JWT、Key、密码或原始 Checkpoint。每个 Episode 的细分错误属于本次模型输出校验事实，不反向推定 L1 的参数。

新建 PostgreSQL、Volume、runner tag 和缓存只属于本轮 owner；最终清理与历史 25 个容器状态对照见机器回执。原始日志及 L1 九份原件哈希保存在 Git 忽略的私有目录，未复制到公开候选。

限制：本轮格式修复针对 L1 的直接 SDK / LangGraph Guard 路径；Playground 的更严格上游 Provider 仍会先拒绝不合法输出，不因此自动获得本轮局部修复。非流式 DeepSeek SDK hook 绑定当前锁版本；升级 SDK 或启用 Token Streaming 需重新验证。失败目标去重只在当前 Run 及其可信约束内生效，不是跨 Run 的业务授权。Worker 模型请求仍不具备通用 Exactly-Once；原业务幂等与 Fencing 保持不变。L1 精确子类型 UNKNOWN；真实 B2 复测须针对新 SHA 单独授权，不能沿用已用的 L1 额度。


## 浏览器兼容修正与验证范围

第一次完整 Playwright 为 **118 passed / 1 failed / 0 retries**：`durable single mode also requires approval`。原因在旧 `workflow_e2e.py` Mock：Resume 后只看新的临时 ToolMessage 列表，忽略已提交 CHECKOUT，重新准备同一购买；新重复写入门禁正确返回 PARTIAL。只修正测试 Fixture 读取已执行/已拒绝的权威提案事实后结束；PENDING/APPROVED 不得冒充执行完成。浏览器断言保持原样，生产代码没有回退安全检查。

新增 4 项 Fixture 正反例 RED→GREEN。`workflow_e2e` 的既有调用者仅为浏览器测试服务器。完整后端 1157/14 之后仅改此测试 helper 并增加这四项测试；生产源码与该完整回归逐文件一致。因此不把 4 项定向补测说成又一次全量后端测试，也不填写不存在的“1161 项全量通过”。完整浏览器复测结果与新候选源码哈希另行绑定。

执行记录：第一次浏览器失败后，外层包装命令未因预检查的 AssertionError 短路，仍清理了本轮已 teardown 为零 Schema 的资源；这是执行错误。原始日志、JSON、失败截图均在删除前已复制保存，25 个历史容器未改变。后续浏览器复测新建不同 owner 的隔离资源，保留第一次清理回执；最终清理改由同一 Python 控制流在哈希/结果核验成功后调用，防止再次提前继续。

本轮取舍：沿用已有 linked worktree 的新分支；优先保留私有失败原件；重复 Key/身份重用保守拒绝；粗公共错误码与精细诊断分离；失败目标仅绑定当前 Run 的可信约束；第三次后端完整回归用于新增的意图反例安全修正，而非同源码反复挑绿。没有增加 Provider 或模型调用额度，没有修改生产 Single 完成判定，也没有掩盖任何失败。


## 最终结论

- 后端完整回归：**1157 passed / 14 原有 skipped / 0 failed**；该生产源码此后未再修改。
- 后续仅测试 Fixture 修正：**4 项定向通过**；没有声称执行了 1161 项完整后端回归。
- 完整 Vitest：**127 passed**；完整 Playwright 最终：**119 passed / 0 failed / 0 retries**。
- 最终 Ruff、format、TypeScript、ESLint、生产构建均通过；浏览器复测使用最终候选 Fixture。
- 两批本轮自有 Guest / PostgreSQL / Volume / runner tag / Runtime 均独立查无，删除前各自 Schema 为 0，25 个历史容器 ID/状态保持。共享 BuildKit 缓存保留。
- 新增 43 项测试：39 项包含在后端完整回归，4 项为最后 Fixture 定向回归。原 14 项 real_bge skip 没有增加。
- Provider 请求 0、真实 Provider Key 读取 0、Push/Dispatch/Rerun 0。L1 九份原件哈希保持。

状态：**AGENTMALL_V213_L2_TOOL_BATCH_REPAIR_READY**。这是离线交付；真实 DeepSeek B2 复测仍为 NOT_RUN。最终候选和已全量验证生产源码的两个 SHA 指纹、所有失败及清理回执均在机器摘要区分列出。
