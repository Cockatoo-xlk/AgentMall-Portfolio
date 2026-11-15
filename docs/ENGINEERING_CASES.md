# V2.16：从可运行页面到可核验业务

基于已合并 V2.15 main `d18161d1eb40667f4658e745d2f58369767d67f5`。本轮是本地离线产品改进，实际结果见[交付](V216_PRODUCT_DEMO.md)和[回执](evidence/v216/verification.json)。没有真实 Provider、付款、退款、部署或 L8 复测。

## RC1 重新审核与实际产品回归

[RC1审核](V216_RC1_REVIEW.md)覆盖原34项变更及周边权限、事务、Checkpoint/Fence语义，未发现需修复的新增产品代码问题，原产品实现保持逐字节一致。本轮从新建PG重新运行完整后端、前端与真实BGE；9条产品浏览器场景核对正式API、SQL事实和人工决策。跨Store拒绝由正式Resume API回归验证，不伪称浏览器切换Store已经演示。

原始录屏实际记录了三条业务链及安全停止；录制脚本自身的启动目录、全页跳转丢失内存登录、旧指令残留和等待结束指令超时均单独留证，不将它们列为Agent产品缺陷或L8评测结果。最终媒体可播放不等于录制工具退出码成功。只新增RC1证据与材料状态，不调Prompt、权限、Oracle或预算。

## 同批次重复 Handoff 绕过已存在的防重复检查

**复现：** Supervisor 一次生成两个不同 subtask_id、其余字段相同的只读查单任务。原实现仅检查已派发的 signatures，在整批验证结束后才加入新签名，因此两个重复任务都执行并消费两次 delegation。真实 PostgreSQL 的临时与持久图回归均观察到2次，预期整批拒绝、0次。

**最小修复：** [runtime.py](../backend/src/agentmall/agents/runtime.py)增加局部 batch_signatures，使用原有完整指纹，在任何派发和原子预算预留前拒绝重复。未改权限、Prompt、工具 Schema、事务、Fence 或预算。正向控制用同一个查询 goal 读取两个不同订单，仍执行两次合法派发。不是禁止所有相同 goal。[3项回归](../backend/tests/test_v216_agent_runtime.py)及既有路由/批次/依赖测试共同验证。

## UI 成功必须和数据库事实一致

[9条产品场景](../frontend/tests/product-demo.spec.ts)通过真实 SDK MockTransport 进入正式 Agent API，页面人工点击分别批准/拒绝；独立 SQL 连接查询商品、Proposal、Confirmation、订单、Case、库存、幂等回执、RunEvent 和 Checkpoint。购买成功须有且仅有一个 PENDING_PAYMENT 订单，不能以模型回答当订单；退换购第一份批准后只有 Case，第二份批准才允许购买。错误确认复用被拒绝，响应丢失重放与刷新不增加订单或模型请求。

页面将推荐事实快照和独立 GET 的当前业务状态分开；售后 REQUESTED 和后续失败可以同时存在。合成的后续 Provider wire 异常在原有校验层以 PROVIDER_TOOL_INVALID 安全停止，Case和已消费确认仍保留，没有伪装成历史08号故障复现。[审批快照](../frontend/src/components/WorkflowProposalDetails.tsx)、[比较表](../frontend/src/components/RecommendationResults.tsx)、[资源核对](../frontend/src/components/WorkflowResources.tsx)。

## 受控评测不沿用自动授权脚本

旧 UserSimulator 虽使用预声明脚本，却会自动确认、Resume 和 Recover。新[离线入口](../evals/CONTROLLED_OFFLINE.md)将读取、明确决定、Resume分开，冻结后才评分；完整 Usage 缺失时保留 UNKNOWN，合成 Token 不等于平台结算。只使用开发和 CONTRACT_TEST_ONLY 样本，不读取 L8 09—15，不构建新 Holdout 或通用评测平台。

以下保留 V2.15 阶段的原始说明与测试归属，不冒充 V2.16 新结论。

---

# V2.15：把真实失败变为可回归的工程问题

本轮基线 `71970c88d8827d22cd5626de20317a89d389bafc` / tree `50921e7431437e0603f6b59487dbbf6cf6e80ec6`。以下产品改进已实现，验证汇总为 **LOCAL_OFFLINE_VERIFIED**，[本地回执](evidence/v215/verification.json)已归档；没有新 Provider 请求或 L8 复测。原15题结果不改写，[完整结果和证据层级](EVALUATION_RESULTS.md)独立保留。

## 1. 比较意图、推荐数量与硬约束

**已确认问题：** 连接枚举逐项匹配时，包含“有线和无线”的比较请求可能只剩最后一个值；Thread偏好解析又可能把同一句比较当成硬约束冲突。即使返回数量不足，完成分支仍可能显示done。01号原评分是 `FAIL / CANDIDATE_COUNT`，`Run COMPLETED` 不能推翻该失败。

**已实现：** 统一无状态与Thread路径的连接语义，区分明确单一要求、比较/可选与真正矛盾。推荐“几款”单独存为只读目标，不借用购买quantity；只从服务端已验证候选快照判断数量/对照是否满足，短缺时如实要求补充，不补造商品、不放宽价格库存过滤。

[解析与短缺检查](../backend/src/agentmall/agents/product_preferences.py)、[Thread合并](../backend/src/agentmall/agents/memory.py)、[结果渲染](../backend/src/agentmall/agents/graph.py)；[合成回归](../backend/tests/test_v215_recommendations.py)覆盖比较、任选、明确无线、互斥要求、数量不足、候选事实、旧约束序列化及Bundle品类隔离。款数/比较短缺检查仅用于推荐只读场景；purchase、return、bundle保留各自完成语义。**当前验证汇总：LOCAL_OFFLINE_VERIFIED；真实模型改善：NOT_RUN。**

## 2. 当前动作意图不能从模型输出反推

**已确认问题：** “采购”及“只/副”等商品量词未完整识别，06号“生成退货提案”未认作提案意图，04号“建立人工客服工单”未认作人工协助意图。04号模型后续 `reason` / `support` 字段漂移被严格校验拒绝；应补足用户请求解析，保留拒绝保护。

**已实现：** 明确采购、提案与客服动作，按子句处理否定、条件和历史陈述；只从购买动作范围提取商品数量。多个商品、相互冲突或条件未决时澄清，不把“介绍采购政策”“查看退货记录”当写请求，不把推荐几款/几个步骤当购买数量。识别购买意图仍不授权执行，原HITL与事务校验继续适用。

[购买意图](../backend/src/agentmall/agents/purchase_intent.py)、[动作与量词](../backend/src/agentmall/agents/request_intents.py)、[可信约束](../backend/src/agentmall/agents/context.py)；[合成意图回归](../backend/tests/test_v215_request_intents.py)、[既有写批次保护](../backend/tests/test_agent_write_sequencing.py)。支持范围为有界中文表达，不能保证任意自然语言。**当前验证汇总：LOCAL_OFFLINE_VERIFIED；历史02/04/06仍为FAIL。**

02号末尾原错误码 `AFTERSALES_INELIGIBLE` 不证明起初资格不符：历史资格为true，Case已REQUESTED；触发末尾拒绝的精确选择未保存，仍为UNKNOWN。不能把新解析工作描述成“修复了原先不符合退货条件的订单”。

## 3. 提案观察与安全诊断

**问题：** 已提交提案的PENDING、APPROVED、EXECUTED、REJECTED等状态需要与模型总结分开；08号又显示，只有统一错误码和Token摘要，无法重建实际工具参数或把失败精确归责。

**已实现：** 从 `runtime.facts` 中提取最小提案状态观察，校验ID/动作/状态，不暴露快照或地址、不把APPROVED改写为EXECUTED，也不改变权限。正式Run的SDK/model事件增加每调用本地UUID、实际SDK工具Schema规范JSON哈希、规范化SDK响应对象哈希和用量数字观察状态；原始Prompt、工具参数、凭据与私人响应正文不进入公开日志，原预算和停止规则继续适用。

[提案状态观察](../backend/src/agentmall/agents/goal_receipts.py)、[观察回归](../backend/tests/test_v215_goal_receipts.py)、[诊断模块](../backend/src/agentmall/infra/model_diagnostics.py)、[诊断回归](../backend/tests/test_v215_model_diagnostics.py)、[模型事件入口](../backend/src/agentmall/agents/model_control.py)、[SDK入口](../backend/src/agentmall/infra/llm.py)。**已实现；验证汇总LOCAL_OFFLINE_VERIFIED。**

`model_request_id`是本地UUID，不是Provider请求ID；`response_body_sha256`不是原HTTP字节哈希；`provider_response_id`取响应body.id，不是HTTP request-id header。`OBSERVED_VALID`只说明用量数字自洽，`output_budget_state`只说明本地预算核对，两者均不是供应商账单。新捕获不覆盖旧single_agent.Guard入口。[完整字段边界](ARCHITECTURE.md#正式run模型诊断的证据边界)。

[失败反馈回归](../backend/tests/test_v215_failure_feedback.py)区分可核验售后原因、失败步骤与已有Case回执；[新合成SDK/SQL工作流回归](../backend/tests/test_v215_workflow.py)约束退货与购买两份独立确认、重放不增请求，以及后续解析失败不抹去已提交Case/确认消费。前端[runFailure](../frontend/src/api/runFailure.ts)与[timelineSummary](../frontend/src/api/timelineSummary.ts)展示固定解释和观测/预算分层，不新增授权或承诺回滚。结果见[回执](evidence/v215/verification.json)，不能把这些新合成测试当历史任务复测。

08号原生评测适配器保持冻结，根因仍 **INSUFFICIENT_EVIDENCE**，Ledger仍UNKNOWN，预留CNY2.113536不能释放。新产品观测能力不恢复旧响应，也不是08号已修复或续评许可。

## 哪些历史异常不纳入产品修复

03号因Episode时限/协议异常未评分，底层原因UNKNOWN；07号是私有评测Host对可变status快照作SHA比较的误判，不算正式产品bug；08号缺少关键原件，不能确定模型、Host或Provider责任。新合成测试属于 `CONTRACT_TEST_ONLY`，不读取Gold、不重跑原题、不重新评分。

## 历史工程案例（原阶段记录）

以下三项保留其原版本数字和证据范围，不作为本轮V2.15测试结果。

# 三项工程案例与可核查入口

## A. Checkpoint 兄弟分支取消与 Journal 恢复

原固定交错中，Shopping写完Journal后故障，Pregel取消Order分支；Order可能已消费Fixture响应但尚未写完整delta，恢复再次进入已消费脚本后变成PARTIAL。R1反事实控制两种Journal先后，定位了该窗口，不把pipeline warning当成根因。

[持久图](../backend/src/agentmall/agents/durable_graph.py)在原Run截止内收束同批已派发节点Journal再传播异常；[Run服务](../backend/src/agentmall/agents/run_service.py)以内存身份保留先观察到的分支错误，避免共同截止误分类。验证包括[固定交错/旧Send/截止回归](../backend/tests/test_recovery_interleavings.py)、[Checkpoint测试](../backend/tests/test_checkpoint_state.py)、[8组原子进程SIGKILL](../backend/tests/test_commit_then_crash.py)。

这些是受控故障与进程内保护，不保证任意SIGKILL下外部模型调用exactly-once。脱敏结果见[历史工程摘要](evidence/reliability.json)。

## B. 12路数据库竞争与幂等回执

T11原10库存/50独立购买：10张待支付订单、40库存不足、0其他错误；峰值12在途/12业务连接，最终on_hand=10/reserved=10。不是10笔已付款。[并发测试](../backend/tests/integration/test_business_invariants.py)通过独立连接、行锁、pg_blocking_pids与屏障观察真实竞争；[Oracle](../backend/tests/integration/oracle.py)独立查询终态。

R1发现原串行观察12个前缀耗尽最早请求3秒锁预算。修复[屏障](../backend/tests/integration/harness.py)先观测赢家，再同时派发其余请求并一次观察全部等待者，未放宽生产锁超时、并发或Oracle。新增[观察成本回归](../backend/tests/integration/test_barrier_deadline.py)固定该交错；同action同key/不同key/冲突payload由事务回执去重，不按HTTP200数当业务副作用数。

## C. Single/Multi 的真实成本、失败与安全边界

两轮同五个开发任务，[指标实现](../evals/metrics.py)与[独立业务Oracle](../evals/oracles.py)保留业务效果、确认和来源。第一次Single1/5/Multi4/5，43请求；第二次Single5/5/Multi4/5，53请求，估算¥0.251492/¥0.341790，平台账单UNKNOWN。

原失败含提前结束、缺get_order来源和无序写批次。第二次Multi B2仍HANDOFF_CONSTRAINT_CHANGED/PARTIAL，合法REQUESTED Case与失败可同时存在，没有替代订单。[写入顺序测试](../backend/tests/test_agent_write_sequencing.py)、[Handoff延续](../backend/tests/test_handoff_constraint_continuation.py)、[监控合成阴性控制](../backend/tests/test_eval_monitor_policy.py)分别验证安全、纠正和误停边界；原完整被拒ToolCall未保留，具体漂移字段UNKNOWN。

外层误判SIGINT导致退出130/-2的历史不改写。L6修复后没有第三次Live；原40题参与开发，不能称独立Holdout或声称Multi普遍更优。完整数字和限制见[结果](RESULTS.md)。

本页说明仓库行为，不证明作者独立手写全部实现；面试时须明确本人设计、修改、复现与AI辅助范围。
