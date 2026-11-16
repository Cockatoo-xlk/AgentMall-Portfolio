# V2.17 当前限制

V2.17本轮为本地离线作品集交付，无新真实模型结果、生产部署或Release。新的四分钟视频是V2.16真实Mock业务素材的字幕剪辑，原录制器收尾失败不改写，SQL卡明确为证据投影。媒体可播放不等于录制器正常退出。

新Smoke为EXPLORATORY_PRODUCT_SMOKE，三题未运行；其静态validator不是Live启动器/权限平台，执行前仍需Owner授权、价格24h新鲜度和现有Runner各项硬门禁复核。L8 PASS1/FAIL4/NOT_SCORED3/NOT_RUN7、08 Ledger/实费UNKNOWN、E1_ORACLE_CONTRACT_MISMATCH、Independent Holdout=0不变。真实Provider请求与Key读取均0，Release ON_HOLD，RELEASE_COMMIT=UNBOUND，MCP REMOTE_AUTH_NOT_IMPLEMENTED。

以下保留各阶段限制的原始说明；其中VIDEO_NOT_RECORDED只适用于注明的历史阶段，不代表本轮没有成片。

---

# 已知限制与证据边界

当前本地候选为 **V2.16**，基于 V2.15 已合并的 `main d18161d1eb40667f4658e745d2f58369767d67f5` / tree `548b2f8e3180027bb179c2b42a1c4367984ff489`。基线 main CI 43718887411 已通过；V2.16 本地证据见[本轮交付](V216_PRODUCT_DEMO.md)，未 Push / PR / 发布 / 部署。本轮不运行真实 Provider，不改 L8 结果。V2.14 Release **ON_HOLD**；**RELEASE_COMMIT=UNBOUND**。

| 范围 | 已知限制 | 核查入口 |
|---|---|---|
| 真实模型可靠性 | L8自建前瞻性15题仅启动8、评分5，PASS1/FAIL4/未评分3/未运行7；独立Holdout0。不能称完整15题通过率、独立盲测或生产成功率 | [完整结果](EVALUATION_RESULTS.md)、[脱敏JSON](evidence/v215/l8-summary.json) |
| 08号事故 | 原参数、原始响应、实际请求Schema/hash、response hash和Provider request-id缺失；根因INSUFFICIENT_EVIDENCE | [事故分层](EVALUATION_RESULTS.md#08号事故拒绝阶段已知责任未知) |
| 费用与用量 | 29HTTP中28SETTLED、1UNKNOWN；完整结算用量与实费UNKNOWN。新增Host观察不能结算原账本，CNY2.113536预留保留 | [费用层级](EVALUATION_RESULTS.md#用量预留与费用分层) |
| 自然语言解析 | 支持有界语义与保守澄清，不能保证任意表达。比较、量词、条件/否定范围已有新实现及合成回归，本轮合成回归通过，见[RC1回执](evidence/v215-rc1/verification.json)；不应把歧义解释为授权 | [工程案例](ENGINEERING_CASES.md)、[当前意图](../backend/src/agentmall/agents/context.py) |
| 推荐完成检查 | 款数/连接比较的短缺检查只用于推荐只读场景；purchase、return、bundle目标沿用各自原完成语义 | [偏好/短缺实现](../backend/src/agentmall/agents/product_preferences.py)、[推荐回归](../backend/tests/test_v215_recommendations.py) |
| 正式Run诊断 | model_request_id为本地UUID；Schema/响应为规范JSON哈希，非原wire字节；provider_response_id取body.id而非HTTP header request-id。OBSERVED_VALID只表示数字自洽，output_budget_state仅本地预算，均非账单。旧single_agent.Guard不在捕获范围 | [字段边界](ARCHITECTURE.md#正式run模型诊断的证据边界)、[诊断回归](../backend/tests/test_v215_model_diagnostics.py) |
| 交易与HITL | 只能确认被审阅的具体提案；购买批准不含付款/退款批准。Case REQUESTED不等于退款成功 | [动作服务](../backend/src/agentmall/actions/service.py)、[售后服务](../backend/src/agentmall/aftersales/service.py) |
| Worker / 恢复 | 受控进程故障、Journal与原业务回执有测试；没有任意崩溃下外部模型请求通用exactly-once、生产灾备或SLA证明 | [Worker指南](V212_DURABLE_WORKER.md)、[进程测试](../backend/tests/test_worker_process.py) |
| 检索质量 | 历史真实BGE/Reranker实验为本地Linux aarch64/CPU、固定40条合成查询、单标注者；Reranker默认关闭，不能等同当前Agent质量 | [真实检索报告](REAL_RETRIEVAL.md) |
| MCP认证 | 仅stdio/localhost；**REMOTE_AUTH_NOT_IMPLEMENTED**，未实现可公网使用的完整远程认证；无付款退款执行工具 | [MCP指南](MCP_GATEWAY.md) |
| Demo | SDK MockTransport / Fixture Embedding / 合成账号 / TEST_OPERATOR；真实后端不等于真实模型。准备依赖后的无Provider演示不保证首次构建全离线 | [6分钟演示](DEMO_GUIDE.md) |
| 影像素材 | 保留历史截图，V2.16初次交付未录屏；RC1另有6:55静音原始录屏，非精剪演示片，收尾超时如实保留 | [截图来源](screenshots/portfolio/README.md)、[原哈希](evidence/portfolio-demo/verification.json) |
| 规模与部署 | 没有生产部署、真实用户规模、QPS、SLA、真实付款或退款证明；公开合成配置不能作为公网认证 | [项目说明](../README.md)、[架构](ARCHITECTURE.md) |
| 统计与版本 | 历史离线CI、真实本地BGE、Mock、不同Live会话分别绑定原SHA，不能相加或当V2.15结果。模型别名也不是不可变权重身份 | [历史结果](RESULTS.md)、[L8身份](EVALUATION_RESULTS.md#身份与公开投影) |
| 旧E1错误契约 | **ORACLE_CONTRACT_MISMATCH**仍未解决：Native的TOOL_NOT_DECLARED/SPECIALIST_FAILED与正式SDK的INVALID_TOOL_BATCH属于不同校验路径，未放行未知工具或修改原Oracle | [既有运行时修复](../backend/tests/test_l8_r4_original_oracle.py)、[批次硬拒绝](../backend/src/agentmall/agents/model_control.py) |
| 发布身份 | V2.14仍ON_HOLD，V2.15已合并但未发布，V2.16为本地候选，**RELEASE_COMMIT=UNBOUND**；本地回归与GitHub CI须分别核验；无Tag、Release或部署 | [本轮验收](V215_RELIABILITY_ENGINEERING.md) |

## 历史失败仍保留

- 01比较/候选数量、02/06采购及退货意图、04客服动作解析进入新产品回归，但原评分不提升。
- 02末尾 `AFTERSALES_INELIGIBLE` 的精确选择未保存；起初资格为true且Case已REQUESTED，不能反推起初资格失败。
- 03是时限/协议异常，底层原因UNKNOWN；07是私有评测Host误比较可变status快照，不列为正式产品bug。
- 08责任无法确定。新增正式SDK诊断只改善未来可观察性，不补写历史响应或释放原预算预留。
- 更早L7 B2 Multi仍 `PARTIAL / CONTEXT_SCOPE_VIOLATION`，没有完成第二次购买确认；[原记录](V214_RELEASE_CANDIDATE.md#真实模型历史)保留。离线成功不覆盖实模失败。

## 贡献与公开范围

项目使用AI辅助开发。面试中只陈述本人能够解释、定位和复现的设计、修改、验证与审查；仓库源码和测试数量不证明独立个人贡献。私有Gold、未运行任务输入、Key、完整Prompt、地址和原始响应不进入公开作品集；本页只说明保留的缺口，不要求读取它们。

本轮没有新L8授权，不继续09—15，不重跑01—08，不修改原Ledger、Oracle、评分或冻结身份。以后发布、部署或新Live实验仍应以新的准确源码与独立授权/回执记录，当前本地文档不代表已发布。


## V2.16 有界支持

- 比较表使用 Run 的检索事实快照；当前库存须独立GET核对，审批时服务端仍重验。界面不能保证任意自然语言都被正确解释。
- 同批重复派发拦截使用既有完整指纹；不保证语义不同但业务等价的任意模型表达都能判重。没有新增自动修复或重试。
- 受控入口是固定合成契约测试与薄API辅助类，不是新通用评测器；状态/错误评分不是业务Oracle，也不是独立盲测。
- SDK MockTransport完整业务链与真实BGE专项分开运行；不能将两者合并描述为本轮真实DeepSeek+BGE端到端评测。
- 原有13项real_bge标记在轻量核心回归中按策略跳过，本轮另行实际执行；私有历史证据测试缺少原件仍跳过。准确数量见[回执](evidence/v216/verification.json)。
- V2.16初次交付的**VIDEO_NOT_RECORDED**是历史状态；RC1原始录屏已独立验证，但没有旁白、末段静态停留较长，录制器未正常FINISHED。见[媒体限制](V216_RC1_REVIEW.md#实际录屏与质量限制)。本地验收时真实Provider请求0、真实Key读取0、GitHub写入0；远程CI和发布需另核。
