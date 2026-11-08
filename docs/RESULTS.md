# 验证结果与证据边界

本页是公开作品版的脱敏验证摘要，不包含原始Live账本、授权或私有模型对话。历史研发原件留在Private仓库；其远程CI成绩不代表独立作品版在GitHub上的运行结果。

## V2.11 商家AI运营助手（本地完整累计回归）

基于`9424b7d6d0b0ccebb52f219282a93e03038c6120`，独立商家只读LangGraph和8个工具名复用原领域/MCP映射，确定性统计与引用校验，草稿仅填原表单。模型SDK MockTransport，业务为独占真实PG；未调用真实LLM，不借用V2.10语义质量成绩。[架构与演示](MERCHANT_COPILOT.md) · [A—N及保留失败](evidence/v211/report.md) · [源码和日志SHA](evidence/v211/verification.json)。

一次完整累计回归 **pytest1083 passed /14 skipped、Vitest126 passed、Playwright118 passed /0 retries**；Ruff、格式、TypeScript、ESLint和build全部退出0。新后端27、Vitest8、浏览器3。实际工具样例与独立快照证明分析新增订单/付款/退款/Case/提案/Confirmation为0；基线含2笔合成订单和2笔模拟付款，不能写成付款总数0。历史文件与原skip边界不变，资源清理查无；Provider/Key/远程写0。当前V2.11远程CI和真实模型验收NOT_RUN。

## V2.10 真实本地检索质量与离线回归

基于`5bdf717280dbd623da8e842905e1757c098774f6`修改工作树，真实本地BGE512 + Cross-Encoder、PG17.11/pgvector0.8.7、Expanded120+动态1+探针7。160条查询执行完成，非法/过期结果0，业务查询前后快照一致，商品发布/变更/下架/重建检查通过。[本轮报告](evidence/v210/report.md)、[源码内容与日志SHA](evidence/v210/verification.json)、[模型和复现](REAL_RETRIEVAL.md)。

最终Test Hybrid → Reranker：Recall@5 **92.53%→91.84%**，MRR **96.88%→100%**，NDCG **95.82%→97.40%**，P50 **22.35→654.77ms**；无答案正确率均25%。**DEFAULT_OFF**，小型SINGLE_ANNOTATOR合成实验不证明统计显著优势，dev-01标签缺口保留。Fixture回归与真实模型成绩分开。

完整离线pytest **1056 passed /14 skipped**、完整Vitest **118 passed**、定向Playwright **16 passed /0 retries**，静态/格式/类型/lint/build通过。没有新远程CI、真实LLM、Provider或Key读取。旧测试/冻结数据和失败回执未改；本轮资源清理已独立查无，模型缓存与私有原件保留。

## V2.9 多轮组合重规划（本地累计完整回归）

基于`8a8d54bd7b21d7e084c7a8d02f312d64f0203b4b`，新增七种可信差分、按品类增量检索与当前事实复核、历史方案只读和前后价格对比。完整后端 **1038 passed / 14 skipped**（含22项新增）、完整Vitest **104 passed**、完整Playwright **113 passed / 0 retries**；Ruff、格式、TypeScript、ESLint、build全部退出0。[A—L场景及保留失败](evidence/v29/report.md)、[命令/日志/源码内容绑定](evidence/v29/verification.json)。

本轮独占PostgreSQL与官方Checkpoint，模型MockTransport、Embedding Fixture；真实Provider及Key读取0。首轮后端1007通过/31失败/14跳过因测试包装缺少私有`.env.rag`，补齐本轮配置后第二轮完整通过；首轮原件保留，不归咎于产品也不隐藏。旧跳过、断言与重试均未放宽，冻结eval数据与MCP权限未改。新版本远程CI、真实BGE和LLM效果均NOT_RUN。

## V2.8 MCP Tool Gateway（本地定向验收）

基于V2.7 `5f197611d6e4cb93a0a39c3882456f196c84551e`，新增官方SDK2.3.0的stdio和localhost Streamable HTTP接口。**181项定向pytest通过（含35项MCP协议/业务测试）**、完整Vitest **102通过**、选定Playwright **11通过 / 0 retries**；Ruff、格式、TypeScript、ESLint、build均退出0。不是完整后端或完整浏览器回归，也不是新的远程CI。[命令、源码内容绑定及日志SHA](evidence/v28/verification.json)。

六个独立官方客户端进程完成Public/Buyer/Merchant × stdio/HTTP、共54次真实Tool Call；结果来自新独占PostgreSQL17/pgvector和原领域服务。数据库前后对照：商品120不变、订单1不变、付款0、库存预留1不变，仅草稿0→1；同request_id跨传输重放仍为同一DRAFT。待支付订单在MCP调用前由TEST_OPERATOR经原独立Confirmation创建，不是MCP下单。[客户端脱敏原件投影](evidence/v28/clients.json)及[本轮报告与保留失败](evidence/v28/report.md)。

HTTP实测协议2026-07-28；stdio另测2025-11-25兼容路径。角色过滤与每次领域认证保留；无批准、下单、付款、退款、发布或任意SQL工具。**REMOTE_AUTH_NOT_IMPLEMENTED**，仅localhost自定义Bearer，不是远程OAuth。Provider调用及Key读取0；普通业务回归为MockTransport/Fixture，没有新增真实BGE或LLM效果评测。

## V2.7 商家动态商品运营（本地离线）

基于V2.6 `cb70ebb6687490db7b21794eb8257a1078d6939d`，使用新独占PostgreSQL17/pgvector、官方Checkpoint及MockTransport/Fixture。完整后端 **981 passed / 14 skipped**，Vitest **102 passed**，完整Playwright **111 passed / 0 retries**；最后商品运营专项 **4 passed**（含3项重复覆盖，不相加为115）。Ruff、格式、TypeScript、ESLint和build均退出0。[本轮结果与保留失败](evidence/v27/report.md)及[命令/源码树/日志SHA](evidence/v27/verification.json)。只读审核、分立发布、版本/库存保护和新品Single/Multi/Bundle交易均有数据库断言。

本轮未重新加载真实BGE、未执行真实Provider、远程CI或部署。既有14项跳过不变；当前Commit通过的是本地离线验收，不能借用历史远程或Live成绩。

## V2.5 多品类目录验证

扩容基于V2 RC `6062c89965aee5dfa7d6ab3ec74917d5a706fe37`，在独占Linux aarch64 PostgreSQL17/pgvector中验证。实际测试数字、源码内容绑定、命令和日志SHA见[本轮摘要](evidence/v25/verification.json)。[目录说明](EXPANDED_CATALOG.md)记录Legacy/Expanded数据身份、迁移、重建和浏览器操作；旧评测和R8记录仍绑定各自历史源码。

| 本地V2.5完整验证 | 实际结果 |
|---|---|
| pytest | 905 passed / 14 skipped（原866 + 新39） |
| Vitest | 95 passed（原92 + 新3） |
| Playwright | 106 passed / 0 retries（原105 + 新1） |
| Ruff、格式、TypeScript、ESLint、build | 全部退出0 |

本轮模型为MockTransport/Fixture，Embedding为Fixture。真实BGE索引代码、固定权重Manifest及0.45阈值未修改，但没有新增真实BGE语义效果验证或真实Provider调用；不能把向量管线检查当作语义质量实测。完整离线回归结果以本轮摘要为准，没有新增skip/retry，没有运行新的900秒时钟准入或远程CI。

## V2 RC 本地集成回归（2026-11-07）

RC 基于 `d6b418a0aadb7b598595560a0df4c42dc79cce39`，整合商家运营、意图编排、SSE 与 Evaluation Studio。测试运行于 Mac Docker Desktop 的独占 Linux aarch64 容器，使用新 PostgreSQL 17 / pgvector 数据库、官方 Checkpointer、MockTransport / Fixture。源码内容哈希、实际命令、UTC、退出码与日志 SHA 见 [RC 回执](evidence/v2-rc/verification.json)。最终 RC Commit 可通过包含该回执的 Git 提交定位；正文不把基线 SHA 当作已修改源码。

| 验证 | RC 实际结果 |
|---|---|
| 完整 pytest / CI_OFFLINE_CORE | 866 passed / 14 skipped |
| 完整 Vitest | 92 passed |
| 完整 Playwright / Chromium | 105 passed / 0 retries / 0 skipped |
| Ruff、format、TypeScript、ESLint、build | 全部退出0 |

14 项原跳过保持不变：13 项依赖真实 BGE 权重，1 项比较未公开的原始 Live 材料。本轮没有执行新的 BGE 专项或付费模型评测，Provider 请求为0；RC 的 GitHub Ubuntu amd64 CI 为 `NOT_RUN`。历史 R8 Run41972687787 对应 `e60ee792…`，不能充当 RC 的远程结果。

首轮完整后端为828 passed / 38 failed / 14 skipped，浏览器为101 passed / 4 failed。失败原件私密保留；没有改成 skip 或增加 retry。修复范围为过期退货提案的持久化事实同步、SSE 页面手动 GET 补读与恢复卡可见性，以及旧测试目标/临时授权 Fixture 与现有意图合同的对齐。修复后的完整结果单独记录。

跨模块浏览器场景用 TEST_OPERATOR 独立确认，串联只推荐且订单0 → SSE 真实进度 → 独立确认下单 → 独立模拟付款 → 商家发货/送达 → 只读评测页面。既有用例另覆盖售后两份独立确认、租户隔离、幂等恢复、部分成功与断流补读。Evaluation Studio 的18个Fixture Episode仍绑定历史运行源码 `8cb788de…`，不是新 RC 的真实模型效果指标。

## 历史验证记录

以下记录按其原阶段、源码与平台保留，不作为 V2 RC 的新运行结果。

| 原研发RC环境 | 实测 | 身份 |
|---|---|---|
| Mac完整后端 | 656 passed | R1本地完整验证，含真实BGE |
| Linux ARM64 CI等价 | 642 passed / 14 skipped | R1容器验证，不与Mac相加 |
| GitHub Ubuntu24.04 amd64 | 642 passed / 14 skipped；Vitest38；Playwright43 | Run41170933236，Attempt1，2026-10-31，SHA7cabcca55d600341b26972a46de757f26a50f044 |

[脱敏远程摘要](evidence/private-rc-ci.json)记录具体Step、初始化和Artifact核验。独立候选已在新的Linux ARM64 Debian容器中无缓存安装并完成离线CI：后端642passed/14skipped，Vitest38、Playwright43，总流程退出0；这与原Private Ubuntu amd64的执行分别记录。[本候选实际回执](evidence/candidate-verification.json)。独立Fixture浏览器Demo两次确认、刷新重登、SQL与Checkpoint核对通过（1→2张订单、REQUESTED Case1、Refund0、Checkpoint41、RunEvent69、Provider请求0）。这里记录的候选验证发生在本地Linux ARM64；独立公开仓库的远程CI须以其真实Run ID和对应SHA另行核验。

| 同一开发集Pilot | 第一次 | 第二次 |
|---|---:|---:|
| Single / Multi Oracle成功 | 1/5 / 4/5 | 5/5 / 4/5 |
| 实际模型请求 | 43 | 53 |
| 输入 / 输出Token | 92,638 / 8,277 | 130,259 / 10,159 |
| 冻结高峰价格估算 | ¥0.251492 | ¥0.341790 |
| 平台真实账单 | UNKNOWN | UNKNOWN |

[脱敏Live摘要](evidence/live-pilots.json)。第二轮Multi B2仍失败/PARTIAL，仅合法REQUESTED Case、无替代订单；外层误判SIGINT与退出130/-2保留。L6后没有第三次真实复测，修复效果LIVE_EFFECT_NOT_VERIFIED。原40题已参与开发，两轮同五题，不是独立Holdout、统计显著的架构优势或生产质量证明。

上述原Private RC远程CI不等于本作品版自己的远程CI。没有真实支付/退款、云部署、生产负载、SLA或任意崩溃的外部调用exactly-once保证。VIDEO_NOT_RECORDED。

## R5最终审核副本

R5新的独占数据库和无缓存构建已完成完整离线CI：后端642passed/14skipped、Vitest38、Playwright43，总流程退出0；[本轮回执](evidence/r5-verification.json)绑定实际测试内容树，不能当作新的远程CI。R5阶段的项目源码范围已通过本地人工审核门禁（PUBLIC_SNAPSHOT_READY_FOR_OWNER_APPROVAL），项目MIT已由权利人选择；R4与原Private远程成绩继续保留各自身份。该阶段性审核不替代作品版后续的GitHub发布及CI回执。

## T15-B1历史真实运行与T15-C候选

[经过审阅的B1汇总](evidence/t15-c/b1-public-summary.json)：历史617cdf29，真实deepseek-flash单场景7请求，12,048输入/1,109输出，费用估算上界¥0.032968而实际账单UNKNOWN；用户本人确认后唯一PENDING_PAYMENT订单、付款0、持久事件50、Checkpoint done。没有Single/Multi公平质量比较或泛化结论。

[T15-C验收](evidence/t15-c/report.md)是新源码的本地离线回归及发布审计。源码指纹变化后Live=NOT_RUN，远程CI=NOT_RUN；旧B1授权、账本与历史Manifest保持不变。

## T15-C1：独立稳定时钟环境重新准入

[逐项归因与新回执](evidence/t15-c1/report.md)：在独立Colima Linux VM中，后端713/14skip、Vitest80、完整Playwright87通过，0失败/skip/retry/flaky。生产源码指纹7049db6a保持不变。旧环境同用例复现了JWT未来iat→401，但其余5项历史单请求信息不足，仍标原因未确定；并未把6项全部归为环境异常。旧81/6及原始日志不覆盖。

新环境连续时钟观测无重大异常，准入状态T15_C_LOCAL_RELEASE_GATE_PASSED只适用于该受验证环境。旧共享VM未修复或重启；当前源码Live=NOT_RUN、远程CI=NOT_RUN、新增付费请求0。

## T15-D1：最终公开内容审查

[D1审查报告](evidence/t15-d1/report.md)核对公开独立父链、全部可达历史Blob、15张合成截图及第三方声明，整理首页与运行/恢复入口。产品源码、锁文件、既有测试与workflow均未改变；复用经原始日志和JUnit/Playwright JSON哈希核对的C1回归，没有重新执行Live或封存评测。

截至D1，当前版本Ubuntu24.04 amd64远程CI为NOT_RUN；actionlint、官方Action固定SHA、87项浏览器收集与默认启动路径的静态检查不等于真实远程运行。[D2待授权方案](evidence/t15-d1/remote-ci-plan.md)只计划推审核分支，不授予Push、Actions、PR或main合并权限。后续实际结果应按准确Commit与RunID追加，不能覆盖各阶段历史回执。

## V2.6：组合购物本地验证

[实现及演示](BUNDLE_SHOPPING.md)、[本轮结果和失败记录](evidence/v26/report.md)、[命令回执与源码指纹](evidence/v26/verification.json)。基线为`c8e9683502e8672d7c23ff9f9b17b79d019c0220`；本轮只在独占PostgreSQL/pgvector、Expanded120 SKU、官方Checkpoint下使用MockTransport与Fixture Embedding，没有真实Provider请求或新远程CI。

新增41项后端、4项Vitest与2项Playwright。一次完整后端回归实际为917 passed /25 failed /14 skipped；失败来自新增工具与旧Fixture/冻结工具协议的兼容问题。修复保持Legacy注册表及历史Manifest不变，最后相关集合129 passed /10 skipped，覆盖全部25项失败。全量Playwright107 passed /1 failed /0 retries，旧Single Fixture工具集合断言修正后，组合/移动端/旧Single定向3 passed；Vitest99 passed。Ruff、格式、typecheck、lint和build通过。按限定范围未再次整套重跑，不把这些结果描述为一次全量全绿。当前收集960项后端测试（946可执行、原14项跳过）。

当前V2.6真实Live、真实BGE专项、远程CI均NOT_RUN；历史R8/V2.5结果保留原版本适用范围。
