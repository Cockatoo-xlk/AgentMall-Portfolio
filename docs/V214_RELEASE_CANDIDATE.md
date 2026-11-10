# V2.14 · Final Portfolio Release Candidate

## R2追加：首次远程超时后的CI可靠性修复

V2.14 `01f0115f6fa704dec7a272eab57579d21d8f4ae5`已发布至原审核分支；[Run42655215470 / Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42655215470)为cancelled，GitHub annotation确认30m0s Job超时。pytest步骤1345秒，Playwright剩余预算5分32秒，记录108项通过后取消；不能当成完整119项通过。

本轮R2仅拆分CI为独立Backend、Frontend-E2E及严格Release Gate，原T16/业务/模型预算/PW设置不变。[专项报告](evidence/v214-r2/report.md)与[新回执](evidence/v214-r2/verification.json)记录本地Linux aarch64执行和新源码指纹。**REMOTE_CI_NOT_RUN_FOR_R2 / AMD64_REMOTE_CI_NOT_RUN_FOR_R2**；原L7 B2仍PARTIAL。以下V2.14阶段内容为当时历史快照；其中“远程未运行/未Push”不代表当前追加状态。后续发布需批准R2准确SHA，不能复用01f0115授权。

状态以[最终检查清单](RELEASE_CHECKLIST.md)和[本轮回执](evidence/v214/verification.json)为准。功能冻结，不进行L8或新业务开发。产品源码基线 **`280ec90816ed3d70079b7fb89457f7f13a4d2278`**；包含本文的本地提交为V2.14文档/发布候选，不把该新Git身份冒充已执行的真实模型实验。

## 能力与证据矩阵

| 能力 | 源码/测试或原件 | 可确认范围 | 不可推导的结论 |
|---|---|---|---|
| 目录、购物车、单/多SKU事务 | [orders/service.py](../backend/src/agentmall/orders/service.py)、[并发](../backend/tests/test_order_concurrency.py)、[Bundle](../backend/tests/test_bundle_shopping.py) | 真实PG、金额整数分、锁后核验、整笔预留/回滚、幂等 | 无生产吞吐/真实支付/SLA |
| Agent提案、两次独立确认 | [L6 SDK/PG测试](../backend/tests/test_v213_l6_budget.py)、[L6报告](evidence/v213-l6/report.md) | MockTransport真实SDK路径，11/10模型调用、7工具、4Delegation、20Steps；Case1+新订单1，付款增量0 | 不是真实DeepSeek B2成功 |
| Thread候选、Bundle Replanning | [memory.py](../backend/src/agentmall/agents/memory.py)、[重规划测试](../backend/tests/test_bundle_replanning.py) | 版本化ID/rank、按品类约束、增量检索、当前商品复核 | 不保证任意自然语言都能解析 |
| 同步/异步执行与SSE | [Worker](V212_DURABLE_WORKER.md)、[进程测试](../backend/tests/test_worker_process.py)、[SSE实现](../backend/src/agentmall/agents/event_stream.py) | 真实PG/进程、Advisory Lock、Fence、Journal、官方Checkpoint、重放恢复 | 202非成功；没有通用Exactly-Once或生产容灾证明 |
| 商家发布/索引、Copilot | [商品运营](CATALOG_OPERATIONS.md)、[Copilot](MERCHANT_COPILOT.md) | 审核→发布→独立索引；只读分析不新增交易写入；Mock/Fixture | 不是AI自动批准/发布或实模准确率 |
| MCP Gateway | [官方客户端/权限测试](../backend/tests/test_mcp_gateway.py)、[指南](MCP_GATEWAY.md) | 9工具、真实协议传输、同领域数据源、stdio/localhost、草稿幂等 | REMOTE_AUTH_NOT_IMPLEMENTED；没有远程OAuth或交易执行工具 |
| 真实本地BGE / Reranker | [V2.10原始数值投影](evidence/v210/verification.json)、[报告](evidence/v210/report.md) | 固定Revision/SHA，512维CPU；40条合成查询 × 4管线；Linux aarch64，Reranker默认关闭 | 不是当前实模Agent评测、独立Holdout或amd64基准 |
| Evaluation Studio | [导出器](../evals/studio/__init__.py)、[界面](../frontend/src/pages/EvaluationStudio.tsx) | 静态脱敏结果、配对/计划分母、缺失值与失败诊断 | 不能把页面当前能加载解释成数据来自当前SHA |
| 真实LLM历史 | 下表与[审核投影](evidence/v214/live-summary.json) | 已留存的原始Manifest/账本/摘要哈希、源码/模型/任务身份 | 不混合源码、不外推生产可靠性；账单UNKNOWN |

## 真实模型历史

共同数据集：`evals/data/agent_dev.jsonl`，SHA256 **`a645fe1799ba46dda5a3fb59fd0d3d6778c8eb9dd4523dc3cbfef021b95c8336`**。五题配对Pilot只选其中A1_01、A2_01、B1_01、B1_02、B2_01；后续只测B2/Multi，均属于开发/定向修复实验，不是新独立Holdout。

请求与回包model字段均为 `deepseek-flash`；这是当时的Provider别名，不是不可变权重/服务版本。使用真实本地 `BAAI/bge-small-zh-v1.5@7999e1d3359715c523056ef9478215996d62a620`、512维，Legacy12合成商品；无真实支付。

| 实验/源码 | 类型 | 真实请求/已结算 | 业务/Oracle结果 | 高峰Token单价估算CNY |
|---|---|---:|---|---:|
| V2.12 `b5d6a685dac44a8bf28aaf357af0e4f4b69f7d5f` | 5题×Single/Multi，各一次 | 56/56 | 9/10：Single5/5，Multi4/5；Multi B2 PARTIAL | 0.393226 |
| L1 `342c3c199984efb89bc649dcb3b1892aeb82da41` | B2 Multi一次 | 9/9 | PARTIAL；INVALID_TOOL_BATCH / REPEATED_DELEGATION | 0.068782 |
| L3 `a055117fac4f5b27d8c04bc333ef317941509035` | B2 Multi一次 | 5/5 | PARTIAL；只读任务尝试写工具被拒绝，随后重复派发拒绝 | 0.038022 |
| L5 `d32d25b25db8d5464fb561b1ef1482598ae31b1c` | B2 Multi一次 | 12/12 | PARTIAL / BUDGET_EXCEEDED；退货确认已执行，缺购买确认 | 0.089722 |
| L7 `280ec90816ed3d70079b7fb89457f7f13a4d2278` | B2 Multi一次 | 6/6 | PARTIAL / CONTEXT_SCOPE_VIOLATION；第一份退货确认成功后、Shopping派发前停止 | 0.053718 |

这些是按已有Token回执及当时高峰单价估算，**不是平台账单证明**。L7具体非法引用/字段未保留；只确认范围校验拒绝，不能编造模型输出、确定违规字段或把Oracle诊断等同于实际越权数据库写入。L6离线路径成功与L7实模失败必须同时保留。V2.14不进行新真实调用。

39份私有原件只做校验与保全，不复制到Git；公开JSON只投影允许的指标、源码/数据集/文件哈希和错误码，不含逐请求账本、授权、原Prompt、JWT、DSN或Checkpoint。更早T12/T15/R8记录保留在[历史结果](RESULTS.md)，各自独立归属。

## 本轮离线验证

本轮已重新执行完整离线pytest1220 passed/14 skipped、Vitest127、Playwright119/0 retries及全部静态检查/构建；均来自新日志，不借用L6的历史成绩。使用专属Linux aarch64 PG17/pgvector、Fixture/SDK MockTransport；不加载本地API Key，不访问付费Provider。命令、UTC、退出码、skip数量、源码文件映射和日志SHA见[回执](evidence/v214/verification.json)。

本轮范围为文档/发布材料；产品执行源码、依赖锁、Oracle、模型Manifest、Migration和原预算均不变。默认Single/Legacy Sync三轮Demo使用现有入口；短Demo不代替真实BGE实验或Live环境时钟准入。所有14项原skip逐项保留，分别为13个权重依赖与1个不挂载私有Live原件的比较测试。

## 公开安全与许可

本轮逐Blob检查待发布HEAD可达历史，而不只扫描工作区。基线36个提交、1125个Blob，约23.7MB；没有模型权重或大于5MiB的Blob，未发现Key/JWT/私钥模式、私有目录路径或具体个人绝对路径。45个历史图片Blob进一步做元数据/OCR及关键页面人工可读性检查；这些检查有检测局限，不能宣称数学意义的“绝无秘密”。最终新增内容单独检查，所有详细扫描原件留在忽略目录。

公开Compose/测试中的固定密码与JWT签名材料是显式公开的合成fixture值，不是用户生产凭据；禁止复用为公网认证。`.env` / `.playground` / 模型和测试输出均不提交。构建验证使用审核后的跟踪文件快照，避免把本地忽略文件误带入镜像；构建不加载Provider Key。本轮使用可信现有依赖镜像+准确跟踪源码快照+锁定依赖同步；458个执行文件逐一与镜像核对一致且未发现额外源码文件。**标准基础镜像冷构建NOT_RUN**。初次离线缓存缺wheel、浏览器定位超时及采集器误读字段均已保留日志，并在[公开回执](evidence/v214/verification.json)列出脱敏命令、退出码和SHA；修正仅在私有构建/演示工具，没有产品改动。

[MIT与权利人确认](LICENSE_DECISION.md)、[第三方许可限制](../THIRD_PARTY_NOTICES.md)、[版权](../COPYRIGHT.md)保持。原依赖和模型许可审查并不自动授权镜像/模型权重/二进制分发。本轮不新增第三方素材或依赖。

## 一次性受控发布方案（未批准、未执行）

1. 所有者审阅最终本地40位Commit、内容指纹、完整Diff与本清单；确认目标新分支及预期远程状态，单独批准一次普通非强制Push。main/PR#1不在该许可内。
2. 执行前重新只读核对main、目标分支、操作者与已有Run。若目标分支存在不同提交或响应不明，停止并读取实际状态，不盲目重复Push。
3. 推送新RC分支会由现有 `ci.yml` 自动触发普通 **CI_OFFLINE_CORE / Ubuntu24.04**；这不是T16手动A/B或新的900秒实验。无需额外workflow_dispatch，不添加Secrets，不Rerun挑绿。
4. 只观察该准确SHA的Attempt1，核对真实测试、原skip、日志与公开摘要。失败停止，记录失败点，不自动开发L8或热修业务。
5. 远程通过后仍需独立批准PR/合并/main/Release/部署；本次本地候选不包含这些操作。

当前只读快照：main=`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`；最近已发布V2.5=`c8e9683502e8672d7c23ff9f9b17b79d019c0220`，其Run42348866265 Attempt1 success；当前产品比该提交多11个本地提交，V2.14最终提交还将增加1个。PR#1仍是旧T15 Draft。当前 **NO_PUSH / REMOTE_CI_NOT_RUN_FOR_V214 / NO_LIVE_REQUESTS / NO_DEPLOY**。

## 本轮实际结论与保留限制

完整离线pytest **1220 passed /14 skipped**、Vitest **127 passed**、Playwright **119 passed /0 retries**，Ruff/格式/TypeScript/ESLint/build全部退出0。14项原skip为13项真实权重依赖、1项私有Live原件不挂载比较；没有增加skip/retry或降低断言。默认Single三轮浏览器演示完成，TEST_OPERATOR批准后唯一 **PENDING_PAYMENT / ¥399 / quantity1**；付款0，当前第二款绑定正确，库存预留合计1。独立REPEATABLE READ READ ONLY连接与官方Checkpointer核对3个Checkpoint、pending_writes0、事件seq连续；刷新重登不产生第二订单。没有扩大Journal直接快照的证据范围。

本轮Demo stop退出0，API进程0、Vite进程-15；独立SQL确认无残留test_/cp_ Schema后，才删除仅本轮Compose容器、数据Volume、网络和新镜像tag；独立查无。25个历史容器ID/状态未变化，默认Context仍colima。不清理共享BuildKit缓存；私有源码快照、失败片段及审核原件保留。该结果不覆盖旧Demo停止异常。

公开安全扫描未发现匹配的凭据/个人绝对路径，45张历史图的元数据/OCR和关键页面可读性检查完成；不等于绝无隐蔽秘密，也不替代权利人或法律确认。标准基础镜像冷构建、V2.14远程CI、真实支付与生产SLA仍未验证；本轮真实Provider/Key读取/托管Embedding均0。私有日志、SQL原件、截图和SHA目录仅本地可读，不上传原件。
