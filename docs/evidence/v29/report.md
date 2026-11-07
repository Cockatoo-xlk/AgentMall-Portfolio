# V2.9 Bundle Replanning：本地累计离线验收

**AGENTMALL_V29_BUNDLE_REPLANNING_READY**。基线`8a8d54bd7b21d7e084c7a8d02f312d64f0203b4b`，分支`codex/v2-bundle-replanning`；最终源码绑定包含本报告的Git提交及[源文件内容树、命令和日志SHA](verification.json)。基线SHA不冒充修改后源码。

## 实际能力

复用V2.6 Bundle与现有Run入口，严格BundleRevision提供KEEP、REPLACE、SET_CONSTRAINT、ADD、REMOVE、UPDATE_BUDGET、UPDATE_QUANTITY。修改前按原身份、Thread锁与Context版本校验；完整差分原子应用，模型不写授权字段。受控中文之外的硬约束澄清，结构化操作与文字不一致也拒绝。

保留/未修改品类重读原具体Product ID；替换、规格变更、新增才调用原Hybrid RAG。总预算和数量修改重算整套金额，不无条件重检全部品类。保留原2–5品类、每类至多5候选、最多3125组合、整数分与稳定平局规则。不是全目录最优保证。

新方案使用新CandidateSet身份，保存来源、前后商品事实/价格/数量/预算、保留或重检原因；原快照不变。无可行方案时保留需求、缺口与待重检品类，旧方案不继续作为购买选择。最多20份历史方案只读展示。新购买仍需本轮明确意图、当前唯一方案、数量/地址及独立Confirmation；原多SKU订单、库存、支付和退款事务未修改。

## 最终完整成绩

独占Linux aarch64容器、PostgreSQL17/pgvector、官方Checkpoint，Legacy和Expanded Fixture均保留。模型MockTransport、Embedding Fixture，真实Provider及Provider Key读取0。

| 验证 | 实际结果 |
|---|---|
| 完整离线pytest | **1038 passed / 14 skipped / 0 failed**，含22项V2.9新增测试 |
| 完整Vitest | **104 passed**，新增2项差异/未知金额展示测试 |
| 完整Playwright Chromium | **113 passed / 0 retries / 0 failed**，含新增多轮重规划浏览器场景 |
| Ruff / format / TypeScript / ESLint / build | 全部退出0 |

14项原跳过不变：13项依赖真实BGE权重，1项私有Live原件比较。3条Jieba SyntaxWarning来自既有依赖，没有屏蔽或升级依赖。新V2.7商品运营、V2.8真实MCP协议测试与V2.9累计在同一源码上通过；远程CI、真实BGE效果与真实LLM为NOT_RUN，没有执行900秒监控。

## A—L实际覆盖

| 场景 | 测试及实际断言 |
|---|---|
| A 耳机单独替换 | `test_cheaper_replacement_and_two_edits_then_safe_purchase`：真实目录调价/重建，只有headphones执行检索，换成不同且当前数据库单价更低的SKU，其他ID不变 |
| B 键盘改无线 | `test_incremental_edit_reuses_exact_other_skus`：只有keyboard检索，其他类别沿用原ID；保留原27英寸等条件 |
| C 保留显示器加音箱 | 同参数化用例：只检索speaker，新增第5品类，原SKU保持，保存source_bundle_id |
| D 删除 | 同参数化用例：删除mouse后保留3品类，零检索；删至1类/加至6类拒绝且原Context不变 |
| E 预算不足 | `test_insufficient_budget_clears_offer_keeps_requirements_and_rejects_old_selection`：无有效offer，4个需求保留，金额null，旧ID购买拒绝，提案0 |
| F 重放/并发 | 同request_id重放返回原Run，只有一个新有效方案、Context版本不再递增；`test_concurrent_revision_requests_accept_only_one_context_version`真实并发仅一个201，另一个409 |
| G 商品变化 | `test_reused_sku_is_revalidated_not_silently_replaced`：下架、库存0、涨价导致超预算均无完整方案，订单和预留增量0；既有Bundle测试另覆盖提案/执行竞态原子回滚 |
| H 多轮后购买 | 两轮编辑后明确选5品类，唯一提案；确认前订单0，TEST_OPERATOR独立确认后唯一PENDING_PAYMENT订单、5条OrderItem及对应库存各预留1，付款0 |
| I 过期选择 | 旧bundle_id和旧Context版本均409；WAITING_INPUT时编辑THREAD_BUSY，不修改旧提案 |
| J 恢复 | 新浏览器用例切断一次SSE、刷新重新登录，完整当前方案文字/商品/版本不变，历史不可选；官方Saver读取最终Checkpoint且pending_writes为空，原Resume重放不新增订单；既有SSE测试验证seq续读及去重 |
| K 隔离 | `test_structured_delta_scope_stale_version_and_text_ambiguity`及Store用例：其他买家、Thread、Store不能访问/修改，越权无提案 |
| L 旧版兼容 | 完整pytest/Vitest/Playwright覆盖V2.6 Single/Multi Bundle、单SKU、售后、商家工作台、V2.7上架、SSE、评测及V2.8 MCP |

数据库断言使用本轮独占PostgreSQL真实记录，不靠模型自然语言判定。更便宜替换的合法结果不固定为测试新调价的某一SKU，其他检索到的更便宜商品仍按原确定性排序选择；测试核对实际ID、数据库价格与原SKU差异。

## RED/GREEN与保留失败

- 初始增量API测试RED：原代码对键盘规格修改返回409；实现后通过。
- 中间定向运行保留所有失败，包括缺少测试导入、未覆盖“必须”触发词、原预算/clarification措辞兼容、0预算校验异常，以及一次误认为新调价SKU一定是最优候选的测试假设。修正边界或测试设置后，原V2.6合同仍通过。
- 新测试证明同轮SET价格上限不能覆盖REPLACE“严格更便宜”的要求，RED后将该上限按最小值合并，不依赖操作顺序。
- 独立只读审核发现并修复三项：失败重规划的待刷新品类丢失；结构化差分绕过未解析文字；新增品类在无方案差异中缺失。补充RED后，22项最终用例全部通过。
- 初次浏览器测试把innerText排版换行与textContent比较，错误拒绝同一恢复快照；改为同一文本表示，保留完整比较与业务断言后通过。
- 首轮完整后端为**1007 passed / 31 failed / 14 skipped**。本轮包装遗漏evals必需的私有`.env.rag`，导致评测/授权演练路径报`Project .env.rag is required`。只补入本轮数据库配置，无产品代码、断言或安全门禁变化，第二轮完整后端**1038 passed / 14 skipped**。首轮原件未覆盖。

## 资源与公开审查

清理前独立READ ONLY事务确认test_/cp_ Schema残留0；本轮Guest、PG、Volume和新镜像tag删除后逐一inspect查无。原25个历史容器ID/State未变，默认Context仍colima，未清理共享BuildKit。临时合成凭据删除；原始日志、截图及全部失败回执留在本轮Git忽略私有目录，目录0700/文件0600。

MCP认证/工具权限、原交易领域、Migration、依赖锁、Legacy/Expanded目录和冻结eval数据没有修改。公开仅源码、合成测试、脱敏回执与经过检查的截图，不包含JWT、DSN、Provider Key、Checkpoint原件或私有Prompt。截图是实际Mock/Fixture页面，操作者TEST_OPERATOR，不是真实购物或模型能力证明。

## 限制

受控中文不是无限开放理解；其他表达必须澄清。修改前请取消仅用于购买的方案单选，或使用结构化source_bundle_id；选择本身不授予购买权限。历史页最多20份，购买只允许当前最新方案；先前版本授权与等待提案不自动继承。沿用原Journal/Checkpoint持久化边界，本轮没有扩展独立Journal原始快照采集。没有真实Provider、远程CI、生产负载、跨Store购物或真实支付验收。

[演示、Schema及算法说明](../../BUNDLE_REPLANNING.md) · [实际前后对比截图](../../screenshots/v29/bundle-revision-diff.png)。
