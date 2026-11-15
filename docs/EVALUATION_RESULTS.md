# 评测结果：保留分母、失败和未知项

**L8 已以 `L8_D3D_CLOSED_WITH_UNRESOLVED_UNKNOWN` 收口。** 这是自建前瞻性评测 `PROSPECTIVE_SELF_AUTHORED`，独立 Holdout **0**。计划15题，启动8题，评分5题；**PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7**。本轮 V2.15 进行产品改进和合成自动回归，不继续评测、不调用 Provider、不修改旧评分。

## 身份与公开投影

L8 Formal Source 为 `71970c88d8827d22cd5626de20317a89d389bafc`，Source Tree 为 `50921e7431437e0603f6b59487dbbf6cf6e80ec6`。这是 V2.15 的基线身份，不是新版本已执行真实模型的证明。不同历史Host版本与会话各自保留，不能把合计29次HTTP写成单一Host版本实验。

本页及[脱敏JSON](evidence/v215/l8-summary.json)依据已验收的只读D3D报告、原结果副本、统计、事故分类、用量附录和身份清单。私有原件不复制进Git，不公开Gold、任务全文、Prompt、地址、原始响应、逐请求授权或凭据。

| 原件 | SHA256 |
|---|---|
| D3D evidence-manifest | `1fe1947843d055cccd5ddc7b3a10c98aa8e4573e5c89ec4b26eb7670a8a75185` |
| D3D REPORT | `447d89fbdde304af798159204c07edf27212a491022a6e259fd280cd15461924` |
| preserved-results15 | `7524c9af6d17129d84fbad6fab81a92b3d81e60f37896f28ef16f77357ef7d89` |
| preserved-statistics | `649fdf8c2f51fb0ab2aa67a93fb95569cdd6986dbd77437a46468c1f3af0db24` |
| classification | `839da351898cc5144c97f7ac61e6a9d3f7705f6e4bf7a481a348156a550ccb01` |
| usage-reconciliation-appendix | `c9815f3ae8702665ef5c36da3049c2a36c39b6b85fc6fcca7e93e31c90742fd5` |
| frozen-identities | `940793daf475741d85f7bb9d32fa15255294501f172072b9760a76cfc8278858` |

哈希锚定这些报告的字节，不能替代报告未保留的原始模型响应或Provider结算凭证。[JSON](evidence/v215/l8-summary.json)另列冻结包、Dataset、Gold、Protocol与Oracle哈希，仅保留身份，不导出内容。

## 原15题：不重新评分

| 序号 | 任务 | 架构 | 原评分 | 原记录/解释范围 |
|---|---|---|---|---|
| 01 | A1_71 | Single | **FAIL** | `CANDIDATE_COUNT`；Run虽COMPLETED，候选数量目标未满足 |
| 02 | B2_71 | Multi | **FAIL** | `AFTERSALES_INELIGIBLE`；末尾精确选择未存，不等于起初资格不符 |
| 03 | B1_71 | Multi | **NOT_SCORED** | `PROTOCOL_VIOLATION`，Episode超时；底层原因UNKNOWN |
| 04 | E1_71 | Multi | **FAIL** | 原primary_failure=`RESOURCE_DELTA`；含`HANDOFF_CONSTRAINT_CHANGED`诊断 |
| 05 | A1_72 | Single | **PASS** | 原PASS保留 |
| 06 | B2_72 | Multi | **FAIL** | 原primary_failure=`RESOURCE_DELTA`；`RETURN_NOT_REQUESTED`，退货目标未完成 |
| 07 | B1_72 | Multi | **NOT_SCORED** | `IMMUTABLE_SNAPSHOT_CHANGED`；私有评测Host误比较可变status快照 |
| 08 | E1_72 | Multi | **NOT_SCORED** | `TOOL_ARGUMENT_SCHEMA_INVALID`；原Ledger UNKNOWN，触发全批停止 |
| 09 | A2_71 | Single | **NOT_RUN** | 未启动；不读取或公开其输入 |
| 10 | B2_73 | Multi | **NOT_RUN** | 未启动 |
| 11 | B1_73 | Multi | **NOT_RUN** | 未启动 |
| 12 | E1_73 | Multi | **NOT_RUN** | 未启动 |
| 13 | A3_71 | Single | **NOT_RUN** | 未启动 |
| 14 | B2_74 | Multi | **NOT_RUN** | 未启动 |
| 15 | R1_71 | Single | **NOT_RUN** | 未启动 |

NOT_RUN 不是已观察失败；NOT_SCORED 不是Oracle FAIL。业务存在合法副作用也不等于整题通过：02号历史资格为true且Case已REQUESTED，仍未满足完整任务；不能用最终错误码编造起初资格。所有历史SHA、原Oracle和原Run状态保留，不因V2.15新增测试而升级结果。

## 逐项归因：已证明环节与证据缺口

下列分类针对可证实的环节，不把相邻症状合并成唯一历史根因；新合成复现也不补写缺失的历史模型输出。

| 历史任务 | 证据支持的分类 | 能确认与不能确认的范围 |
|---|---|---|
| 01 | PRODUCT_BEHAVIOR_DEFECT；完整历史归因INSUFFICIENT_EVIDENCE | 推荐连接约束覆盖、数量完成检查可从源码和合成测试复现；实际检索参数未导出，不能确认这是候选不足的唯一原因 |
| 02 | INSUFFICIENT_EVIDENCE | 起初资格为true、Case已提交；末尾精确工具选择缺失。采购量词漏识别另有产品复现，但不能由此推定末尾资格错误的来源 |
| 03 | EVALUATION_HARNESS_DEFECT（脚本/时限阶段）；底层原因UNKNOWN | 原记录为SCRIPTED_CASE_NOT_UNIQUE与Episode超时；不能据此断言售后业务或模型的具体错误 |
| 04 | PRODUCT_BEHAVIOR_DEFECT；MODEL_OUTPUT_DEFECT（被拒的约束漂移） | 人工客服动作漏识别可复现；后续Handoff的reason/support漂移被校验拒绝，保护保持有效；不归责为权限校验缺陷 |
| 06 | PRODUCT_BEHAVIOR_DEFECT | 明确退货提案表达漏识别，记录RETURN_NOT_REQUESTED；原RESOURCE_DELTA评分保留，不把全部后续行为归为已证明的调度器缺陷 |
| 07 | EVALUATION_HARNESS_DEFECT | 私有Host比较了可变status快照；不是正式产品HITL放行或事务错误的证据 |
| 08 | INSUFFICIENT_EVIDENCE | 拒绝阶段明确；模型参数、Host解析或Provider协议责任缺少直接原件 |

当前没有足够直接证据将上述整次历史失败单独归为AGENT_ORCHESTRATION_DEFECT。V2.15的可信提案观察与安全终结属于可回归的编排改进，不能据此宣称原Multi失败已经在真实模型中解决。

## 分母与统计

| 指标 | 原结果 | 解释 |
|---|---:|---|
| 计划覆盖 | **8/15 = 53.33%** | 启动过的Episode占原计划 |
| 评分覆盖 | **5/15 = 33.33%** | 只有5题具有原Oracle评分 |
| 已评分成功率 | **1/5 = 20%** | 95% Wilson区间 **3.62%–62.45%** |
| Single已评分 | **1/2 = 50%** | Wilson **9.45%–90.55%**；原计划Single5题 |
| Multi已评分 | **0/3 = 0%** | Wilson **0%–56.15%**；原计划Multi10题 |
| 独立Holdout | **0** | 自建前瞻性集，不能称独立盲测 |

20%不是完整15题通过率。不能把1/15称为“15题实测成功率”，也不能从如此小且不完整的子集推导Single普遍优于Multi、统计显著架构优势或生产成功率。Wilson区间描述该样本的统计不确定性，不消除数据集自建、覆盖不足和停止机制带来的局限。

## 08号事故：拒绝阶段已知，责任未知

可确认的直接链路是：首次Supervisor `model_start` → `model_end failed` → 冻结Native `response_contract`严格JSON/Pydantic校验拒绝 → Run PARTIAL → 原账本UNKNOWN与Host停止。工具0、Delegation0、HITL0，无业务写入。

`TOOL_ARGUMENT_SCHEMA_INVALID`覆盖非法JSON、缺失/错误字段及语义校验失败，本身不指出具体字段。源码重建中Supervisor声明与适配器validator使用同一个IntentPlan，未证实Schema漂移；可能工具为route只是源码路径推断，不是实际回包原件。

| 责任候选 | 结论 |
|---|---|
| 模型参数非法 | 可能，缺原始arguments，未确证 |
| Host工具Schema不一致 | 未证实；重建一致，历史实际wire Schema缺失 |
| Provider响应协议非法 | 未证实；仅有Host状态/模型/Usage观察，无完整响应体 |
| 最终根因 | **INSUFFICIENT_EVIDENCE** |

实际工具参数、原始响应、历史请求Schema字节/哈希、原始响应哈希和Provider request-id未保留。不能编造字段、归责模型或宣称08已修复。正式产品新增安全诊断不能恢复这些历史原件。

## 用量、预留与费用分层

| 层级 | 可确认事实 | 不可推导结论 |
|---|---|---|
| 原Ledger权威状态 | 总HTTP **29 = 28 SETTLED + 1 UNKNOWN**；08 Usage UNKNOWN，预留 **CNY2.113536** | 不能改成已结算或释放预留 |
| 历史SETTLED小计 | 输入 **87,625**、输出 **7,152**；峰值单价估算 **CNY0.232466** | 不是完整实费或Provider账单 |
| D3D新增Host观察 | 08 HTTP200、response_model=`deepseek-flash`、输入 **3,654**、输出 **293**、合计3,947 | 不是原封存Ledger用量；模型别名不是不可变权重身份 |
| Host元数据费用算术 | 按输入2/输出8元每百万Token计算 **CNY0.009652** | 不是实费、发票、已结算记录或可释放额度 |
| 完整结算用量与总实费 | **UNKNOWN** | 不用预留额度充当消费额 |

Host观察文件的当前SHA为 `5992782713e44e9a6b1b379f8662124aa84e8c8baf05db41149eb97ead3a17ef`。它可关联原attempt/Execution，但未纳入原32项Live或119项离线封存，首次密码学锚点来自D3D审计；没有原始响应、原始参数、响应哈希或Provider请求回执ID，不能倒推自HTTP返回以来不可变。

冻结适配器只在整份响应契约有效时结算；工具参数拒绝后按原安全协议恢复发送前预留并标UNKNOWN。已确认该控制路径，没有证据证明Ledger磁盘写入故障。即使Host观察Usage相加有效，也不足以权威闭合费用。

若仅相加Host元数据，输入91,279 / 输出7,445、峰值算术CNY0.242118；该数**不计入原Ledger已结算总计，也不是实际账单**。08的1.854968292秒是Host EgressSession.send区间，含Host检查，不是纯Provider网络耗时。

## 从事故到产品工作

01的比较/数量目标、02/06的采购量词与提案意图、04的人工客服动作解析属于已确认的产品改进方向；04后续模型reason/support字段漂移仍应拒绝。03底层原因UNKNOWN；07是私有评测Host缺陷；08责任无法确定。[工程案例](ENGINEERING_CASES.md)将这些边界映射到源码与新合成测试。

D3D曾运行冻结解析器的26项MockTransport原生回归，证明拒绝、预留与停止分支；它不是新Agent Episode、真实模型复测，也不是V2.15成绩。V2.15的产品改进已实现：有界中文意图/量词、推荐只读款数与比较检查、可信提案状态和失败反馈，以及正式Run安全诊断。[工程案例](ENGINEERING_CASES.md)与[新SDK/SQL工作流测试](../backend/tests/test_v215_workflow.py)提供源码入口；当前本轮结果见[验证回执](evidence/v215/verification.json)，各项应绑定准确源码与实际运行。

新诊断的model_request_id是本地每调用UUID，tools Schema与SDK对象响应只保留规范JSON哈希；response_body_sha256不是原HTTP字节哈希，provider_response_id是body.id而非HTTP header request-id。OBSERVED_VALID只表示用量数字自洽，本地output_budget_state不表示供应商结算。旧single_agent.Guard不在捕获范围；这些未来观测能力不补写08号历史原件。[字段定义](ARCHITECTURE.md#正式run模型诊断的证据边界)。

V2.15结果独立记录：

| V2.15验证 | 当前状态 |
|---|---|
| 新合成意图/推荐/状态/诊断/工作流回归 | **LOCAL_OFFLINE_VERIFIED** |
| 后端完整回归、静态检查 | **1534 passed / 14 skipped / 0 failed / 0 errors / 0 warnings**；Ruff与format通过 |
| Vitest、Playwright、TypeScript、ESLint、build | **132 passed；119 passed / 0 retries**；TypeScript、ESLint、build通过 |
| 新真实Provider / BGE专项 / L8续评 | **NOT_RUN** |
| 远程CI / 发布 / 部署 | **NOT_RUN / NOT_PUBLISHED** |

历史CI数字只保留在其原回执，不复制成本轮成绩。当前V2.14 Release仍 **ON_HOLD**，V2.15仅本地工作；不新增Live授权、不重跑01—08、不读取09—15输入、不修改冻结证据。
