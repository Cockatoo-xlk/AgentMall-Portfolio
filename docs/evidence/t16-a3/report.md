# T16-A3：中文品类召回与完整业务 Oracle

最终状态：**BLOCKED**，原因 **BLOCKED_ENVIRONMENT_CLOCK**。代码已实现，真实 BGE 首轮召回已修复，三轮 Mock 曾取得完整业务数据；但长期监测发现 Docker Desktop Linux 墙钟回退，最终审查修复后的完整数据库/浏览器复测未启动。**不标记 T16_A3_RETRIEVAL_AND_ORACLE_OFFLINE_VERIFIED。**

本地分支`codex/t16-a3-retrieval-oracle`，独立工作树`AgentMall-T16-A3-Retrieval-Oracle`。基线`b6ab3e5cfa3e789bee5554277c5fd9d2b697cca0`。本报告与代码同一本地提交交付，完整40位SHA见最终交付回执。生产源码指纹`1e54c1f0d0b76ff0a975fbcc9938008336febbf1a1c8c5564253a23f4a901e27`。无Push、PR/main写操作、部署、真实Key读取或付费调用。

## 根因与最小生产改动

旧索引包含英文`keyboard`，没有“键盘”；通用中文查询既无词法命中，两个合法商品向量相似度约0.412/0.398又低于0.45。R2原始诊断、失败Schema和账本没有覆盖或重置。

仅修改两个生产文件：`retrieval/ingest.py`添加keyboard→键盘、mouse→鼠标、headphones→耳机三个可信目录词汇和商品专属文档标识；`retrieval/search.py`拒绝旧商品文档，并在重读当前事实后重算内容哈希。约13行新增、3行删除；具体以Git diff为准。未知品类不猜测，无召回兜底、固定SKU、Mock查询改写或新业务功能。

仍使用原RRF、BGE0.45、LIMIT前权限/属性过滤、当前Catalog Version重读和工具二次校验。商品标识为`jieba-0.42.1-search-nfkc-v1:catalog-zh-v2`；政策索引不变，无新增数据库结构迁移。重建保留Product ID与当前Catalog Version，更新当前文档hash/TSV/vector；旧索引须显式重建，未自动升级任何历史库。[重建契约](../../RETRIEVAL_INDEXING.md)

## 测试与真实 BGE

配置正确的基线RED为8 failed/2 passed；修复后相关检索套件34 passed/1个原有skip。Oracle最初11项RED→11 passed；独立审查新增11项RED→最终22 passed。最终新增pytest共32项：检索10、Oracle与清理22。没有扩大skip/retry或降低旧断言。

真实BGE仍为`BAAI/bge-small-zh-v1.5`、Revision `7999e1d3359715c523056ef9478215996d62a620`，六文件尺寸/SHA一致，512维CPU，真实PostgreSQL17.11和pgvector0.8.7。独立入口运行14个检索检查：

- “键盘”/300元静音：2件；“静音键盘”/300元：2件；“无线静音键盘”/400元：3件；“鼠标”和“耳机”各2件。
- 不相关查询、超预算、下架、缺库存、跨店、版本变化、未重建源变化、错误内容hash和旧文档标识均拒绝。
- 实际捕获两次召回SQL，预算/店铺/状态/库存/版本/属性条件在LIMIT之前；重建的12条记录ID/version/hash正确，政策tokenizer未改变。

这些是时钟异常前的真实检索证据，生产指纹与当前版本一致。[检索结果](retrieval-results.json)

## 三轮 Mock 与独立数据库事实

逐字使用三个固定输入，没有修改原ContextSDK的“键盘”查询，没有新造演示SKU。第一轮2件，第二轮3件，记忆版本2→4→5，预算30000→40000；旧名单失效，第三轮绑定第二轮实际第二款**办公K108**，Product ID `e5635304-5562-5b76-80ae-2f577488e404`、Catalog Version1。

| 阶段 | 购买提案 | Order | Confirmation | Payment |
| --- | ---: | ---: | ---: | ---: |
| 两轮推荐后 | 0 | 0 | 0 | 0 |
| WAITING_INPUT、独立确认前 | 1 | 0 | 0 | 0 |
| 明确的离线测试操作者批准、Resume及重放后 | 1 | 1 | 1 | 0 |

Order ID `74d61de1-9c6a-482f-bd68-cabc3cc60cb2`，状态PENDING_PAYMENT，总额35900分，数量1。最终Confirmation为approve，consumed_at非空、result_ref为该Order；Proposal为EXECUTED。Idempotency Request共2条，只有一条完成的execute_checkout业务回执；同Start/Resume请求重放不产生第二笔订单或模型调用。

独立READ ONLY/repeatable-read连接保存Order、OrderItem、确认前原Proposal、最终Proposal/Confirmation、全部SKU库存、幂等行、事件和Run。目标on_hand20/reserved1，对应唯一待支付订单行；非目标SKU库存不变。三个Run的事件seq分别26/33/26，共85；官方Checkpoint共52行，三个最终next=done、pending_writes0，付款0。官方Saver亦在独立显式READ ONLY事务读取。

原始业务JSON SHA：`1492599eaa4244d1caea4d60bfbe6762ce05e7af0e701406c47b962a3f0bab14`。原件与sidecar一致，保留于私有目录。公开摘要只含合成业务事实，不含JWT/Key/完整模型会话或Checkpoint序列化。[业务摘要](database-oracle-summary.json)

**版本边界：** 这次数据库运行在最终独立审查修复之前。现有原始JSON已经包含完整确认前提案与库存记录；当前严格Oracle以其已保存字段重新验证，仍无违反。该复核另存文件，未修改原件、未读取新的数据库终态、未新建Run或再次清理。它不能冒充最终代码的一次新端到端运行。

## 一次独立审查及修复

审查发现3项Important：文件fsync不等于目录项持久化、提案qty/附加item/hash/订单地址变异曾可假通过、重复state可能加载旧失败Schema；另有Minor的清理后失败报告误称Schema保留。

已补严格原始提案快照与payload hash、完整Order/Quote/Product一致性；目录及祖先目录同步失败即停止；数据库访问前原子创建新state，拒绝已有目录；清理状态区分OWNED/DROPPED/UNKNOWN。新11项RED已逐项观察，最终Oracle单测22 passed。父任务将错误清理状态报告按重要证据正确性问题处理，代价是小范围验证工具状态标记及3项纯测试。

没有再次独立审查，也没有宣称获得新的独立最终签核。最终完整Oracle清理链尚未在稳定环境重新运行。[审查与处置](review.json)

## 完整回归的实际结果与阻塞

| 实际执行 | 数量/结果 | 退出码 | 限定 |
| --- | --- | ---: | --- |
| 首次完整pytest | 823 passed / 14 skipped | 0 | 审查修复前；执行窗口早于异常 |
| Vitest | 85 passed | 0 | 前端源码未改 |
| Playwright | 96 passed / 0 retries / 0 skips | 0 | **执行期间发生时钟回退，不授予环境验收** |
| typecheck / lint / build / format | 通过 | 0 | 首次完整流程 |
| 首次Ruff | 102字符字符串行宽失败 | 1 | 原失败保留，整套流程退出1 |
| 最终Ruff / format | 通过 | 0 | 静态检查，不访问DB/模型 |
| 最终审查修复单测 | 22 passed | 0 | 无业务写入的Oracle/文件门禁测试 |
| 最终完整pytest / Playwright / 新BGE清理链 | NOT_RUN | — | 时钟阻塞后不在同环境重跑挑绿 |

14项仍为原13项BGE核心CI策略跳过与1项私有Live原件比对；真实BGE另跑强制专项。记录的是本地Docker Desktop Linux aarch64，不是远程Ubuntu amd64 CI。[真实命令/退出码/日志SHA](verification.json)

60秒时钟准入通过；随后连续监测约2906.637秒，Mac重大异常0，Linux1。北京时间**2026-11-03 00:23:26.484078**，墙钟增量**-1.843431ms**、单调增量+10.841208ms、残差-12.684639ms，触发原-1ms门槛；read_span仅917ns。原门槛未放宽。

Playwright实际窗口00:21:44.673–00:24:09.692，故该异常落在浏览器回归内。Linux底层时钟调整原因仍UNKNOWN；没有把之前900秒通过解释成长期稳定。检出后停止监测及最终复测准备，未修改系统时钟、共享Docker或JWT。原始两端JSONL与SHA、连续序号及异常样本保留。[时钟数据](clock-summary.json)

## 失败、资源与历史保护

保留Docker Hub连接超时、Google cache超时、Debian HTTP包502、初始测试配置遗漏、所有RED、验证器首次错误接口、Ruff失败及本次时钟失败。Node24.21.0改由官方站点下载并核对官方SHASUMS；只在私有镜像中使用官方HTTPS Debian仓库，未改全局配置或关闭TLS。Playwright重试始终0。[失败台账](failure-ledger.json)

首次验证器在确认前错误调用不存在的GET Run路径；其独占业务/Checkpoint Schema、Mock账本和原日志保留。只读复核该失败状态为Proposal1、Order0、Confirmation0、Payment0、Advisory Lock0。没有重置账本或复用该state做新场景。成功的审查前验证使用另一个全新环境，按当时代码导出/回读SHA后清理；该版本尚缺目录fsync，现已修复并明确为历史证明。

Docker Desktop7.75GiB，runner4GiB、每个PG768MiB；成功BGE/Mock容器内存峰值约701.32MiB，本轮容器OOMKilled均false，整个VM峰值未测。监测进程已结束；本轮两个PG服务停止、Volume保留；旧R2服务未操作。未删除任何旧VM/Volume/Live数据。[资源与保留状态](resource-summary.json)

原T16-A2仍为b6ab3e5且干净；R2受保护96文件SHA完全一致；local main仍17f72b8，Frozen Manifest和依赖锁未改。旧Private、PR/main、历史Live账本没有写操作。[历史保护](historical-integrity.json)

## 后续边界

当前首轮召回修复和Oracle安全修复已写入；最终稳定环境完整验收仍未取得。先解决/解释Docker Desktop墙钟回退，再由独占稳定环境执行当前完整pytest、前端/Playwright及显式真实BGE验证入口。失败证据保留，不通过降低安全阈值或反复选绿解除阻塞。

后续新的B0必须绑定本地最终提交、当前源码指纹、新Environment/Session/Policy和24小时内官方价格。R2旧Policy实测SOURCE_MISMATCH；没有创建新的Live批准或预算账本。所有Agent请求均为MockTransport，真实DeepSeek0；本轮不具备进入付费Smoke的准入条件。[下一次预检要求](live-preflight-next.md)
