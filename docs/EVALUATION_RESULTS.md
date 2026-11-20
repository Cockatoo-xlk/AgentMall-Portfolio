# V2.17 验证结果：按Source、会话和证据性质分别记录

本页记录交易链路复验以及此前不同源码和会话的结果。每项结果对应当时的受测源码，原评分按批次保留。

## V2.17 交易链路复验

受测 Commit 为 `f8abf931c49f182951f439f3ae2fb644050dd0a3`，Tree 为 `0510a1ee54cdae7492f4067dd720b954a95c5bce`。文档提交 `45d87e7` 记录了这次运行。PR #9 后续产品修复的证据列在下节。

此前一次真实模型自动审批批次中，B 提交订单后仍进入下一轮规划，再次请求 `prepare_checkout`。`REPEATED_TOOL_CALL` 守卫拦截了重复调用，未新增订单。当时的 Run 为 `PARTIAL`，B 仍为 `NOT_SCORED`，C 为 `NOT_RUN`。按事件构造的离线回放观察到持久回执与旧提案摘要同时进入上下文，写工具仍可见。原始模型请求与响应正文缺失，无法确定重复请求的完整成因。

这次交付分开处理单价要求、单件上限和订单总预算，商品价格仍由服务端核验。B 的纯购买目标全部满足时，Single 依据已确认的持久回执结束并显示待付款。若用户还要求查询或另买一次，第一笔回执只证明对应交易已提交，剩余目标沿原流程继续。C 的退货回执也只完成退货，替换购买须走单独的提案、确认和 Resume。[价格约束回归](../backend/tests/test_unit_price_semantics.py) · [持久回执判断](../backend/src/agentmall/agents/goal_receipts.py) · [B/C 与独立目标回归](../backend/tests/test_b_post_commit_closeout.py)

该受测提交使用真实 DeepSeek、固定 BGE、正式 FastAPI、隔离 PostgreSQL 与 Checkpoint，按 B→C 各执行一次。每份提案使用冻结的 `AUTOMATED_TEST_POLICY` 做测试审批并显式 Resume。原业务 Oracle 和自动策略均 PASS，两题 Run 均为 `COMPLETED`。C 的合成准备订单及模拟支付在基线内，表中只统计 Agent 执行增量。

| 任务 | 独立 SQL 核验 | Episode / HTTP | 输入 / 输出 Tokens | 费用上界 |
|---|---|---|---|---:|
| B 购买 | 一笔 398 元待付款订单，数量 2，确认创建/消费 1/1，库存预留 +2 | 5.851 秒 / 3 | 8,066 / 237 | ¥0.018028 |
| C 退货与替换 | 先创建质量退货 Case，再用另一份确认创建待付款替换订单。确认创建/消费 2/2，库存预留 +1 | 19.946 秒 / 11 | 40,952 / 2,395 | ¥0.101064 |

两题支付与退款增量均为 0。共 14 次 HTTP、51,650 Tokens，用量全部结算。¥0.119092 为按峰值费率计算的保守费用上界，实际供应商账单为 `UNKNOWN`。本批次是两道已暴露任务的功能复验，未重跑 A。审批由自动测试策略执行，C 用到 11/12 次模型调用和 4/4 次委派，更复杂流程的调用余量仍待验证。

同一受测源码的定向回归为 **93 PASS**。单独运行的 Backend Offline Core 为 **1912 PASS / 0 FAIL / 16 SKIP**，其中 15 项为核心模式跳过的真实 BGE 测试，1 项缺少私有历史原件。另已验证固定 BGE 的文件哈希与 CPU 推理。Ruff、Format、Diff 通过。两组离线测试分别计数，独立于真实模型复验。原始运行证据和测试日志私有留档。

## PR #9 行为修复的离线验证

换购请求分别解析旧品报价、新品单价和总预算。Thread 更新偏好时先验证合并后的精确价与上限，冲突返回澄清错误，并保留原版本。Legacy 商品分页和 Durable 检索都在数据库截取候选之前过滤精确单价。[换购和偏好回归](../backend/tests/test_replacement_price_preferences.py) · [分页与检索回归](../backend/tests/test_exact_price_retrieval.py)

纯购买收尾核对本次已处理提案的商品事实与请求。同句额外动作及具有独立数量的推荐继续由原流程处理。同大类商品还须匹配明确指定的类型或型号。正式 API 回归以隔离 PostgreSQL、持久 Checkpoint 和离线模型传输验证 B 只创建一笔 398 元待付款订单、预留两件库存。C 先创建退货 Case，再用另一份确认创建替换订单。跨提案复用确认返回 409，重复 Resume 后 SQL 读回一致，两题的支付与退款增量均为零。[商品和回执绑定](../backend/tests/test_checkout_goal_binding.py) · [B/C 交易断言](../backend/tests/test_b_post_commit_closeout.py)

真实 B→C 成绩归属 `f8abf931c49f182951f439f3ae2fb644050dd0a3`。本次修复仅进行了离线验证，真实模型表现仍待验证。

定向回归 **403 PASS / 0 FAIL / 0 SKIP**。完整 Backend Offline Core **2064 PASS / 0 FAIL / 16 SKIP**。其中 15 项需要真实 BGE 权重，1 项需要私有历史原件。两组计数各自对应本轮离线验收。

## 三个独立执行的真实成功案例

这些是经过产品调试和操作流程改进后的功能验收案例，不是未见输入盲测，不是同一版本连续3/3，也不用于统计可靠性认证。模型记录为 `deepseek-flash`，使用真实固定BGE、正式FastAPI/PostgreSQL/Checkpoint；涉及写入时由Owner独立审查Proposal、创建Confirmation并显式Resume。没有真实资金支付或退款。

| 案例 | 原执行Source Commit | 结果与SQL业务事实 | Episode / HTTP | 输入 / 输出Tokens | 当次保守费用上界 |
|---|---|---|---|---|---|
| A 商品推荐与比较 | `8171e5576180e8827b78fff3d6c9f58051729f08` | PASS；最终展示2款，Thread候选ID一致，探索记录保留；订单/确认/支付/退款增量0 | 7.094秒 / 3 | 9246 / 669 | CNY0.023844 |
| B 购买两件商品 | `115905a3cb45bfd2b70384fec7375be9243a6f92` | PASS；PENDING_PAYMENT订单+1、数量2、总价39800分、确认创建/消费+1/+1、库存预留+2；支付/退款+0 | 54.036秒 / 4 | 9523 / 407 | CNY0.022302 |
| C Multi退货与替换购买 | `8171e5576180e8827b78fff3d6c9f58051729f08` | PASS；Run COMPLETED、Case+1、PENDING_PAYMENT订单+1、确认创建/消费+2/+2、库存预留+1、支付/退款+0；Checkpoint 48行 | **81.333秒 / 11** | 40306 / 2276 | CNY0.098820 |

Source `115905…`的Tree为 `73bbecb8923a393fb0abbf003589fa54ff2963b4`；Source `8171…`的Tree为 `505dab36d2bcd07b6259fa9f67a3f5d899c3ba47`。C由Mac本地TTY操作员完成两轮独立审查、决定和Resume，连续90秒计时包含人工等待。成功案例各自的Provider用量均已SETTLED；上述金额按当次冻结峰值费率计算，**供应商实际账单均为UNKNOWN**，不能称作实际支付费用或当前价格报价。

| 私有回执的公开哈希锚点 | SHA256 |
|---|---|
| A所在Postfix A/C会话最终回执（其中C仍NOT_SCORED） | `3a52da4f4cf1148308b05cef601cf4c10b7f95a8a6f40919ab163a1e830eaddf` |
| B所在首次A/B/C会话最终回执 | `9fcd8bc6fbe6c0d6cf68371db7587629b48e953e6ecad76421c3e95b6c5f0d10` |
| 后续本地TTY真实C成功回执 | `e984adca9953fb1d192d589f307b36096138e63fd0ccd90b60a274dcf944b435` |

只公开汇总与哈希；不公开私有目录、运行身份、凭据传递日志、数据库连接信息或完整调试原件。哈希不能代替未公开原件的第三方审计。

## 原Owner提供四题：保留失败与未运行

该批次性质是 **PROSPECTIVE_OWNER_SUPPLIED / INDEPENDENCE_NOT_ESTABLISHED**，不是独立盲测。原计划4题；H01—H03拟执行3题，实际启动2题、完成原Oracle评分1题。H04未进入Episode，原静态拒绝保留。

| 原任务 | 历史状态 | 证据与后续开发的边界 |
|---|---|---|
| H01 推荐 | **FAIL** | 原商品SQL证据投影缺少category；独立事实复查不构成重评分，原FAIL不变 |
| H02 购买 | **NOT_SCORED** | 交易已提交后再调用prepare_checkout，被REPEATED_TOOL_CALL拒绝；保留已提交订单及原停止结果，不恢复该Run |
| H03 总预算负例 | **NOT_RUN** | 未启动；不得作为已观察失败或开发调试样本 |
| H04 跨商品售后购买 | **STATIC_ADMISSION_REJECTED / Oracle NOT_RUN** | 原商品与新商品属性作用域冲突导致静态拒绝；原记录不改，暴露后的场景仅转为开发回归 |

原Source为 `8171e5576180e8827b78fff3d6c9f58051729f08`。原四题输入SHA256为 `33556ae1f5aa39bdb3c140d3b61ce8d916e4cebd5ae255e83206304760ee0ac7`；原Oracle代码SHA256为 `08d60ce38d6d63ea6da9a3837b6581b7eed7840cb6bbea05feee1e97b4be11f3`。原79份封存证据及评分全部保留，不合并开发回归、不重算通过率。**独立盲测数量仍为0**。

## 原 V2.17 RC 工程验证

原验收提交 `759391cd6c33a1bbc906df34e6de87126cb53dac`（Tree `339d618bd92d092467e62e0511649c77b3a701d8`）使用真实隔离 PostgreSQL 和 SDK MockTransport/Fixture。该次 Backend 为 **1824 PASS / 0 FAIL / 16 SKIP**，pytest 耗时 831.85 秒，退出码为 0。跳过项含 15 项依赖真实 BGE 的测试和 1 项缺少私有历史原件的测试。[精确分类与命令](V217_INTERVIEW_READY.md#最终源码验收)

完整Backend日志SHA256：`9e1c650840160e2a9a1f2e1ef108d2b770ec8e7eac87e5cbff4c7587f754afc0`；JUnit SHA256：`97623d36657d4186468913d165c1b6d5888a7cfe27f660b28206ee2b7c7d66c7`。早期RED和合成脚本协议适配的中间失败已保留，不累加不同源码结果充当全绿。

该阶段的开发修复包括商品事实 category 投影、同一新商品的属性冲突澄清、价格语义统一、推荐数量与 Thread 候选一致性，以及独立目标继续执行。纯购买在当时通过既有结构化结束信号收尾。该阶段只验证开发回归，原 Holdout 评分按原执行记录保留。[最终 P2 回归](../backend/tests/test_final_p2_contract.py) · [商品与交易回归](../backend/tests/test_post_holdout_product_fix.py)

## 首次V2.17真实Smoke与离线收尾

本节记录首次Smoke和当时的Post-Live离线收尾；后续独立执行结果已在上文另列，不将历史阶段的“当时未运行”沿用为当前状态。

实际执行Source `115905a3cb45bfd2b70384fec7375be9243a6f92`，Tree `73bbecb8923a393fb0abbf003589fa54ff2963b4`。冻结输入SHA `4dd539b51bc1b3162825a3721bb3e99c59d264ad9794d49db6107603fa620230`、协议SHA `bd5a7a44a16b5f8e2a112a42ae2c647364b97eec407ae186250369031758d96e`。最终私有回执SHA `9fcd8bc6fbe6c0d6cf68371db7587629b48e953e6ecad76421c3e95b6c5f0d10`。

| 任务 | 原结果 | 实际业务事实 | HTTP / 保守峰值估算 |
|---|---|---|---|
| A Single比较 | FAIL / CANDIDATE_COUNT | 最终商品事实3个，要求2个；无订单写入 | 3 / ¥0.021104 |
| B Single购买 | PASS | 待付款订单1、数量2、总价39800分、库存预留+2 | 4 / ¥0.022302 |
| C Multi退换购 | NOT_SCORED | 退货Case1；两份确认已批准，仅退货确认消费；无新增替换订单 | 10 / ¥0.075610 |

计划3题全部启动一次，评分2题：PASS1 / FAIL1 / NOT_SCORED1 / NOT_RUN0；已评分成功1/2，计划中PASS为1/3。17次HTTP全部SETTLED，输入46356/输出3288 Tokens；合计峰值保守估算¥0.119016，供应商实际账单UNKNOWN。支付/退款相对各题Setup基线增量均0。该批次原评分与证据不改，停止的Run不再Resume；后续独立授权、新执行身份的成功案例见上文，不与此批次合并。Release仍ON_HOLD。

A为产品展示约束缺陷：原`graph.render`逐一展示所有探索商品，`recommendation_shortage`仅检查数量不足，不限制超量。原模型最终原文和完整Run.result未被独立导出，不能声称LLM自由回答推荐了3款；但原已核验事实、Specialist引用和确定性renderer足以确认产品最终视图会展示3款。新补丁只对明确数量的只读推荐投影最终事实/引用，保持原始探索状态，并使Thread候选列表、连续序号及不可变列表身份与展示一致。购买、售后和组合交易事实不裁剪，不硬编码商品ID。

C连续Episode计时分解（秒）：

| 区间 | 耗时 | 时钟证据 |
|---|---:|---|
| Episode开始→首次WAITING_INPUT | 10.462 | Host持久起点 / PostgreSQL RunEvent |
| 首次WAITING_INPUT→退货Confirmation创建 | 14.261 | RunEvent / Confirmation.decided_at |
| 首次Confirmation创建→显式Resume命令 | 14.341 | Confirmation / Host命令接收UTC |
| 首次Resume命令→第二次WAITING_INPUT | 9.211 | Host命令 / RunEvent |
| 第二次WAITING_INPUT→购买Confirmation创建 | 35.563 | RunEvent / Confirmation |
| 第二次Confirmation创建→90秒截止 | 6.163 | Confirmation / 持久Episode起点+90 |

首个批准命令接收到Confirmation创建仅0.469秒，批准后14.341秒主要是操作员/工具调度间隔，没有证据表明API在此期间持续处理。SDK模型调用诊断累计17.181秒；HTTP预留至结算边界累计13.899秒，不能混称模型总耗时。工具诊断累计0.230秒（可重叠且包含DB操作），独立SQL/Checkpoint耗时UNKNOWN。工具RunEvent时间可能是节点Journal提交时间，不能据此伪造逐SQL延迟。

原始停码仍为`OPERATOR_OR_RUNTIME_STOPPED`；结合等待路径与90秒截止时间判断为时钟边界停止，底层异常类型未保留。收尾补丁仅让既有CLI在独立决定成功后显示绑定Confirmation及全新request_id的可复制`resume_command`和剩余时间；操作员仍须另行显式提交Resume。没有自动批准/Resume，也未修改90秒/300秒协议。此改进减少手工拼接，但不能保证远程审阅与调度满足90秒。

当时的离线收尾使用新DEV/CONTRACT_TEST_ONLY样本、SDK MockTransport、正式API及全新隔离PG，没有在该工程回归中重放A/B/C Live。合成操作员分两次独立决定和Resume，Mock计时不含人的实际阅读和远程命令等待，不能当作真实DeepSeek PASS。原Smoke断言、原Oracle及历史回执未改；此后真实验证另获Owner授权、绑定各自Source与新执行身份，结果见上文，不覆盖首次成绩。

收尾相关回归203项通过；随后修正列表身份的偏好绑定后，仅补跑受影响121项并全部通过（两组有重叠，不能相加充当独立测试数量）。生产90秒/300秒及回拨拒绝不变；离线性能测试使用真实单调流逝计时，避免VM壁钟校正污染性能样本。未改前端或BGE实现，不重复运行其完整矩阵。初始只读缓存配置、测试GET路由及VM时钟回拨造成的中间失败日志均保留，不计为最终通过。

---

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

以下为初次本地候选f017880的V2.15验证快照；后续[RC1修复与真实BGE专项](V215_RC1_REVIEW.md)另行绑定源码与回执，不能覆盖L8历史：

| 初次V2.15本地验证 | 原快照状态 |
|---|---|
| 新合成意图/推荐/状态/诊断/工作流回归 | **LOCAL_OFFLINE_VERIFIED** |
| 后端完整回归、静态检查 | **1534 passed / 14 skipped / 0 failed / 0 errors / 0 warnings**；Ruff与format通过 |
| Vitest、Playwright、TypeScript、ESLint、build | **132 passed；119 passed / 0 retries**；TypeScript、ESLint、build通过 |
| 新真实Provider / BGE专项 / L8续评 | **NOT_RUN** |
| 远程CI / 发布 / 部署 | **NOT_RUN / NOT_PUBLISHED** |

历史CI数字只保留在其原回执，不复制成本轮成绩。当前V2.14 Release仍 **ON_HOLD**，V2.15仅本地工作；不新增Live授权、不重跑01—08、不读取09—15输入、不修改冻结证据。
