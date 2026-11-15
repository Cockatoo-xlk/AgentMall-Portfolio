# V2.15 可靠性工程验收

本轮只改进正式产品与离线回归，不继续修补L8私有执行器、不重跑历史任务。基线为 `71970c88d8827d22cd5626de20317a89d389bafc`，基线tree为 `50921e7431437e0603f6b59487dbbf6cf6e80ec6`。本地分支 `codex/v215-reliability-engineering`；提交身份由最终本地回执记录。V2.14 Release保持ON_HOLD，V2.15未发布。

## 已确认问题与修复

| 问题 | 修复及可复现证据 | 保留的边界 |
|---|---|---|
| 比较有线/无线时枚举循环覆盖约束，推荐数量没有独立表达 | [推荐约束](../backend/src/agentmall/agents/product_preferences.py)、[实际过滤与完成检查](../backend/tests/test_v215_recommendations.py)；比较与任选不收窄为单一连接，明确单一连接、预算和库存仍硬校验，候选不足如实请求补充 | 仅只读推荐的款数/比较完成检查；不通过增加模型调用凑数量。01历史实际查询未导出，不能宣称唯一历史原因已证明 |
| 采购、量词、退货提案和人工工单意图漏识别 | [有界动作解析](../backend/src/agentmall/agents/request_intents.py)、[接线回归](../backend/tests/test_v215_intent_integration.py)；否定/条件/第三方陈述不授予动作，歧义及文本/typed冲突澄清 | 不是通用中文理解；typed显式选择、角色权限、领域资格和独立确认仍分别验证 |
| 已确认提案结果与旧Specialist待确认摘要并存 | [Supervisor](../backend/src/agentmall/agents/supervisor.py)只新增来自已验证facts的 `action_outcomes`；同Run澄清保留未撤销的推荐目标，新Run不继承采购授权或推荐款数 | 不改Prompt、不重写依赖、不中转跨角色隐私；不自动修正模型Handoff |
| 后续SDK响应解析异常缺少关联诊断，可能继续请求澄清 | [模型诊断](../backend/src/agentmall/infra/model_diagnostics.py)、[持久化/去重/Fence测试](../backend/tests/test_v215_model_diagnostics.py)；该错误安全收敛为PARTIAL，同一Resume只读返回 | 并行只读兄弟沿原barrier收敛；不承诺撤销已提交业务，不扩大可恢复错误集合 |
| 售后失败原因仅显示代码 | [受控业务解释](../backend/tests/test_v215_failure_feedback.py)、[前端反馈](../frontend/src/api/runFailure.ts)；保留错误码、已提交回执与UNKNOWN含义 | 不改变资格、退款或库存状态机；不自动批准、Resume或重试 |

新合成[SDK＋SQL工作流](../backend/tests/test_v215_workflow.py)验证：退货和购买两份不同Confirmation、旧确认不能批准新购买、Case恰好1、新待支付订单恰好1、两把商品库存预留为2、付款/退款无新增；同请求重放不增加模型调用或业务写入。另验证后续解析失败保留已提交Case及消费记录。它们是CONTRACT_TEST_ONLY，不是历史L8重新评分。

原意图测试中“推荐一款，然后买两件”曾因数量解析不支持而被列作缺失数量。V2.15支持明确的两件采购，因此保留原句并移入[正向回归](../backend/tests/test_v2_intent_routing.py)：断言推荐款数1与采购量2分离、订单在确认前增量0、独立批准后唯一待支付订单及库存预留2、金额相等、重放不重复写入、付款退款增量0。缺信息/冲突保护用例仍保留，没有修改原Oracle或L8分母。

## 本轮验证

本轮最终验收全部通过：

| 检查 | 实际结果 |
|---|---|
| 完整后端CI_OFFLINE_CORE | 1534 passed / 14 skipped / 0 failed / 0 errors / 0 warnings；pytest 601.21秒，命令总耗时605.08秒 |
| Vitest | 132 passed |
| 完整Playwright | 119 passed / 0 failed / 0 skipped / 0 retries；215.31秒 |
| Ruff / format / TypeScript / ESLint / build | 全部通过 |
| 真实Provider / 真实Key读取 / 本轮费用 | 0 / 0 / CNY0 |
| 新真实BGE / 远程CI / 发布 | NOT_RUN / NOT_RUN / NOT_PUBLISHED |

14项沿用既有skip规则：13项需要真实BGE权重；1项需要未随新工作树提供的私有Live原件。未新增skip或降低Oracle。环境为Linux aarch64、Python3.12.10、独占PostgreSQL17/pgvector，不是当前分支的Ubuntu amd64远程CI。

中间失败没有删除：第一轮完整后端1418通过、67失败、29错误；第二轮1522通过、5失败；第一轮浏览器117通过、2失败。分别定位并修复隔离测试环境、旧句法/同Run澄清和测试输入兼容性后，才以最终源码重跑完整矩阵。日志与结果JSON/XML的SHA保留在回执；不将中间结果当最终成功。

同Run澄清只解析本次补充，合并既有canonical，再持久化当前消息及合并约束；不把两轮购买动词拼成新批次。Single和Supervisor都能取得原始目标，当前clarification单独呈现；角色、独立HITL、库存及幂等校验保留。

最终统计、命令、退出码、耗时、日志SHA与源码文件绑定见 [verification.json](evidence/v215/verification.json)。本轮使用新独占PostgreSQL17/pgvector、官方Checkpoint、SDK MockTransport及FixtureEncoder；无外部网络路由，无真实Provider Key。轻量环境与真实本地BGE专项分别标记。

没有改动原Oracle、DEV/TEST、锁文件、迁移、CI、模型预算、交易权限或HITL。新代码不提交私有日志、模型权重、Gold或运行凭据。

日志及结果封存后，按明确Owner核对并清理本轮4个测试容器和4个Volume，逐项验证不存在；历史L8资源未操作。本轮依赖镜像保留用于复现，见[资源处理回执](evidence/v215/resource-handling.json)。

## L8正式归档

完整[15题报告](EVALUATION_RESULTS.md)与[脱敏摘要](evidence/v215/l8-summary.json)保留原状态：PASS1、FAIL4、NOT_SCORED3、NOT_RUN7。只有5题完成原Oracle评分，1/5=20%，Wilson95%区间3.62%–62.45%；不是完整15题通过率。08仍INSUFFICIENT_EVIDENCE、LedgerUNKNOWN、实际费用UNKNOWN；Host观测与费用算术不闭合原账本。D3D的42份封存文件哈希已复核一致。

03时限/协议异常的底层原因UNKNOWN；07是私有Host快照误比较，不列作已修复产品缺陷；02初始资格为true且合法Case已提交，后续AFTERSALES_INELIGIBLE的精确工具选择没有原件。04/06原Oracle及模型约束漂移诊断分开呈现，不以新离线通过改写旧分数。

## 新诊断的隐私与证据含义

- `model_request_id`为本地每次调用UUID；Schema哈希覆盖实际SDK请求tools的规范JSON。
- `response_body_sha256`为SDK响应对象规范JSON的哈希，不是原始HTTP字节封存；`provider_response_id`是body.id，不是HTTP header request-id。
- `OBSERVED_VALID`仅表示观测用量数字自洽；本地 `output_budget_state` 与Provider财务结算分开。无法验证的字段保持UNKNOWN。
- 公共RunEvent仅白名单字段；不存Prompt、完整参数、响应正文、地址、Authorization或Key。沿现有RunEvent事务、Fence与去重机制保存，未创建第二套事件存储。
- 畸形SDK对象的序列化使用 `warnings=False`，防止Pydantic警告回显响应片段；解析异常仍被拒绝。合成canary回归同时检查事件和警告，未读取真实响应补全历史证据。
- 新捕获覆盖 `model_control.model_call` 的持久Single/Multi/Supervisor路径；旧 `single_agent.Guard` 保留原逻辑。

## 下一版评测预案

状态为 **DRAFT / SOURCE_AND_DATASET_UNBOUND / NO_LIVE_AUTHORIZATION**，不生成新题或消耗旧许可。

1. 建议另建V2.15预注册研究，仍标记PROSPECTIVE_SELF_AUTHORED；独立Holdout为0。优先设计新的业务任务，先冻结源码、执行器兼容性、任务、Gold、原Oracle及评分规则，再运行。不得使用未运行09—15调试产品。
2. 如果Owner选择原09—15，须制定独立续评协议，明确旧D3C因UNKNOWN停止、08账本仍未闭合、产品与Host版本变化及新授权会话；08权威费用证据不足仍阻断续评，必须满足既有安全停止解除条件，不能仅靠新会话绕过。不能直接恢复旧批次，结果只做有版本区分的补充，不覆盖原15题。
3. 计划规模可另行批准为Single5/Multi10，预算提案沿原限制：每题HTTP12、Models12、Tools16、Delegations4、Steps24、输入3145728/输出12000Tokens、Episode90秒含HITL、Outer300秒、CNY2.50；15题理论CNY37.50。仅方案，当前费用授权0。
4. 每题一次，独立Run/Thread/业务状态/Ledger/证据。失败不重试、换Run或调Prompt；费用或写入UNKNOWN、安全/身份异常全局停止。清理需独立精确所有权及已验证封存证据。
5. 预注册计划/启动/评分分母，分开PASS、FAIL、NOT_SCORED、NOT_RUN；报告Single/Multi、Wilson95%、模型/工具/Delegation、延迟分布、HITL、Token、保守费用与实际账单状态。额外业务质量审查不得冒充原Oracle。
6. 执行前重新核验官方模型、非思考配置、24h价格、BGE与工具Schema身份，以及真实发送、凭据与安全停止链路；逐份提案由重新授权的操作员独立审查。不得沿用L8旧授权。

现有Release Gate阈值未修改。新真实评测的通过标准属于未来预注册内容；离线CI成功不等于真实模型可靠性、生产认证或发布授权。

## 作品集表达

可表述为：用FastAPI、PostgreSQL和LangGraph实现带独立人工确认、Checkpoint、事务和幂等回执的Agent电商工作流；通过真实模型前瞻性试验暴露失败，保留不完整结果，再以合成合同回归修复可证实的解析、约束与诊断问题。

应同时说明：原L8仅评分5题、1通过4失败；3未评分、7未运行，08费用未知；V2.15本轮没有真实模型复测。不能写成“15题通过”“已证明Multi稳定可靠”“生产Exactly-Once”或“真实支付上线”。演示见[Demo Guide](DEMO_GUIDE.md)，源码问题见[面试提纲](INTERVIEW_TALKING_POINTS.md)。
