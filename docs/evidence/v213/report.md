# V2.13 B2 离线修复与证据边界

基线：`b5d6a685dac44a8bf28aaf357af0e4f4b69f7d5f`。分支：`codex/v2-live-b2-remediation`。

**历史 B2 的确切根因仍不完整。** 本轮确认并修复一个通用 Specialist 提前完成缺口；没有完整历史轨迹可以证明它就是原真实 DeepSeek 失败的原因。因此最终诊断状态为 `AGENTMALL_V213_B2_DIAGNOSIS_INCOMPLETE`，真实模型复测保持 NOT_RUN。

[源码分析、依赖链、诊断使用与独立付费复测提案](../../V213_B2_REMEDIATION.md)。[机器回执](verification.json)保存实际测试数量、源码指纹和原始日志 SHA；原始日志和 Pilot 原件保留于 Git 忽略的私有目录，不随报告发布。

## 能确认与不能确认的事实

| 项目 | 结论 |
| --- | --- |
| 原 Pilot | 56 个已结算请求、有效 Usage；9/10 Episode 通过 |
| 原 B2 Multi | PARTIAL；模型 12、工具 6、输入 34,620、输出 3,555 |
| 预算耗尽是否是直接错误 | UNKNOWN；摘要只给 UNEXPECTED_ERROR，没有具体错误码 |
| Supervisor 是否在原 Run 重复路由 | UNKNOWN；没有保存路由/工具轨迹 |
| 原 Run 中约束是否被改写 | UNKNOWN；只有源码保护与离线反例，没有原 Handoff |
| 实际越权写入与虚构事实 | 无法由旧聚合诊断证明；两次缺失确认与一次缺失来源不等于实际写入/虚构事实 |
| 原始模型回答或商品来源 | 不存在完整原件，未重建、未补造 |
| 可复现代码缺口 | 只读成功回执可能使可写 Specialist 被判 done，却没有对应提案 |

原三个文件逐字节 SHA：

- manifest：`d1b062cc320421e3f1829cc0393def2904a64cad1b9dc207c05b7b1943566604`
- ledger：`39b39f3af50b5d9bfcbdb1e1c468b1b704389cdca9bdf01a1f776448f1d2ad96`
- summary：`03241d2ca61092e707c150450b240b533bceaff078807ae6759c44b1cdd2f38a`

## 修复前后

RED：真实隔离 PostgreSQL 上，AfterSales 完成三项读取后提前自然结束，原实现最终 PARTIAL，而不是等待退货确认。

GREEN：同一受控模型序列在现有一次修复机会内继续 `prepare_return`，不重复上述读取；等待确认 1，生成 Case；随后 Shopping 检索替代品，Order 准备 CHECKOUT，等待确认 2，创建订单。完整路径为：

| 模型调用序号 | 重建 Fixture 中的实际动作 |
| --- | --- |
| 1 | Supervisor → AfterSales |
| 2 | 读取原订单 |
| 3 | 资格和公开政策，两个独立只读工具 |
| 4 | 提前结束，命中 INCOMPLETE_WRITE_GOAL |
| 5 | 同 Specialist 按已验证来源准备退货提案；等待独立确认 |
| 6–8 | Supervisor → Shopping → 检索并返回替代候选 |
| 9–10 | Supervisor → Order → 独立购买提案；等待第二次确认 |
| 11 | 已确认执行后 Supervisor 正常结束 |

总共 6 次工具、3 次 Delegation。它是明确构造的 `RECONSTRUCTED_FIXTURE`，不是从原账本推算的历史路径。

没有更改 Supervisor、Durable Graph、预算上限、交易领域、库存服务、Checkpoint、Oracle、冻结数据、迁移或依赖锁。生产改动仅为 Specialist 完成校验/提示与允许列出的诊断投影、预算/来源元数据；评测入口增加可选导出。

## A–J 回归对应

| 要求 | 自动化证明与数据库断言 |
| --- | --- |
| A 两次确认 | `test_v213_reliability`：退货/购买两份不同 Confirmation；前者不能用于后者，返回 409 |
| B 不重复完成任务 | 同文件重复路由测试：REPEATED_DELEGATION，Delegation 仍为 1，Specialist 未再次执行 |
| C 预算安全停止 | 模型限制降低至 4 的反例保持 PARTIAL/BUDGET_EXCEEDED；Case、新订单、退货提案增量均为 0 |
| D 原来源 | 原订单与 SKU 来自已交付合成订单；现有 Handoff 测试拒绝改变 order/policy_version 或私有售后引用 |
| E 替代约束 | 新订单 SKU 不等于原 SKU；单价 ≤ 50,000 分、quantity=1、静音、reserved=1，逐轮约束和演示地址相同 |
| F Resume 重放 | 两个 Resume request_id 重放返回已完成结果，Case 仍 1、新订单仍 1、确认只消费一次 |
| G 模型错误 | 原有约束漂移、缺失引用、提前购买测试；拒绝后保留已提交 Case，不把真实失败改成 COMPLETED |
| H 权限/注入 | `test_multiagent_tools`、`test_prompt_injection` 和跨租户集成：其他用户/Store 与商品描述不能授予工具权限；无越权提案/退款 |
| I Single | 原 Single 评测、预算耗尽、独立确认与恢复测试全部包含在累计回归中；新完成门禁不作用于 Single |
| J Bundle/Worker | `test_bundle_replanning`、`test_worker_queue`、`test_worker_process`，及新增真实 SDK MockTransport Bundle 修复回归 |

SQL 断言使用独立连接读取真实 PostgreSQL。原已交付订单设置包含模拟付款，因此验证新动作的**付款增量为 0**。Bundle 新回归使用 Expanded 目录，确认前订单 0，确认后唯一订单含 4 个 OrderItem，库存总预留 4。不存在本轮真实付款。

## 测试与失败记录

最终累计结果：**pytest 1118 passed / 14 skipped / 0 failed；Vitest 127 passed；Playwright 119 passed / 0 retries**。Ruff、format、TypeScript、ESLint 和生产构建全部退出 0。新增 12 项 pytest 全部包含在最终完整回归中。完整后端原始运行耗时 547.35 秒；不是仅复测失败子集。此报告随同一已测可执行源码提交。

可执行源码 SHA256：`5f502b14a17bf155a609085fa98293e56f80f4cd90cfba3b7eb6827bc92d0540`，438 个受版本控制/候选源文件，算法及原始日志 SHA 见 `verification.json`。这不是对历史真实 Pilot 的重新判定。14 项原有 real_bge skip 保留，未新增 skip 或 retry。本轮是 Fixture Embedding + SDK MockTransport + Linux aarch64/PostgreSQL 离线验证，不是新的真实 BGE 或 DeepSeek 实验。

开发中的失败全部保留：最初写目标复现 RED；导出模块/字段尚未实现的 RED；资格拒绝不应强制写入的 RED；Confirmation 范围和错误分类 RED；独立审查发现 Bundle 自由文本泄漏及修复工具名不符的 RED；二次投影丢失安全约束的 RED。另有 Bundle 测试驱动初稿错误使用快照键 `product_id`，修正为实际字段 `id` 后仍先复现产品缺陷。测试过程中曾把缺失 Usage 预期为省略，已改为准确断言 UNKNOWN。均未删除安全断言、修改原 Oracle 或伪装成历史真实失败。

## 保全、清理与局限

原 Pilot 哈希和 72 份保护文件在结束前再次核验。只新建本轮 PostgreSQL、Volume、runner 镜像 tag 与缓存；清理必须有零自有 Schema 和独立查无回执，不能删除历史资源。最终清理通过：删除前自有业务/Checkpoint Schema 为 0；新 Guest、PostgreSQL、数据 Volume、runner tag、运行缓存和生成的测试凭据均独立查无。25 个既有容器的 ID/状态在本轮前后相同。默认 Docker Context 仍为 colima，所有操作显式使用 desktop-linux；未清理共享 BuildKit 缓存。原始日志、RED/GREEN 和回执继续私密保留。

真实 Provider 请求 0，Provider Key 读取 0，Push/Dispatch/Rerun 0。未创建 Live 批准回执或新 Live Ledger。未运行 900 秒监控、历史 Pilot 或远程 CI。

主要剩余限制：原真实 B2 归因 UNKNOWN；离线修复不保证真实模型在 12 次调用内完成；一次共享修复机会耗尽后仍安全停止；可选诊断最多 2000 事件并标记截断；当前 CLI 不支持单独 Multi 的 Live 命令，下一次 B2-only 执行包装器须另行审查与授权。独立真实复测结果才能评估本修复对 DeepSeek 的作用。
