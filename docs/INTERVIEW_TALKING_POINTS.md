# V2.17 · 12个源码可展开的面试主题

使用[4分钟成片](media/v217/agentmall-v217-demo.mp4)与[简历稿](RESUME_PROJECT.md)，每个结论以相邻源码/测试为准。基线为已验收V2.16 main `8e21bdcad3170487626a17ccda0f624457bccd26`；V2.17新测试数量见[交付回执](V217_INTERVIEW_READY.md)。AI辅助开发，个人贡献按实际走读、设计、修改、复现与审查范围说明。

1. **LangGraph的作用。** 将路由、状态、失败和中断建模为图，持久路径支持interrupt/Resume和Checkpoint；它不负责数据库交易授权。临时graph不等于持久图，见[durable_graph](../backend/src/agentmall/agents/durable_graph.py)、[临时graph](../backend/src/agentmall/agents/graph.py)、[Checkpoint回归](../backend/tests/test_checkpoint_resume.py)。
2. **Supervisor怎样派发。** Supervisor产出受约束TaskSpec，runtime先验证角色、实体来源、依赖、批次和预算，再执行Specialist。模型不能声明Actor/Store或批准权限；[Supervisor](../backend/src/agentmall/agents/supervisor.py)、[runtime](../backend/src/agentmall/agents/runtime.py)、[批次重复回归](../backend/tests/test_v216_agent_runtime.py)。LangChain的[create_agent适配](../backend/src/agentmall/agents/specialists/runner.py)处理模型/工具middleware，不是另一个交易服务。
3. **Checkpoint的职责。** 它保存图运行位置和待确认中断，业务回执保存已经提交的订单/Case；恢复先读回执，不能凭Checkpoint重复写入。[持久化](../backend/src/agentmall/agents/persistence.py)、[提交后故障测试](../backend/tests/test_commit_then_crash.py)。不承诺所有外部副作用的任意exactly-once。
4. **HITL与事务怎样衔接。** 不可变Proposal包含服务端快照，用户身份下独立创建Confirmation；Resume重验绑定、时效和业务状态，事务中消费确认及提交业务。[动作服务](../backend/src/agentmall/actions/service.py)、[Run服务](../backend/src/agentmall/agents/run_service.py)、[双确认回归](../backend/tests/test_v215_workflow.py)。退货批准不授权购买，更不授权付款退款。
5. **防止重复下单。** 使用稳定request/command身份、一次性确认消费和持久幂等回执；响应丢失后读回原结果而不是创建新请求。[订单服务](../backend/src/agentmall/orders/service.py)、[浏览器响应丢失/刷新](../frontend/tests/product-demo.spec.ts)、[连续演示](../frontend/tests/interview-demo.spec.ts)。UI禁用按钮只是辅助保护。
6. **库存不超卖。** 交易服务按固定顺序锁定相关商品行，重读active/version/价格/可用库存，检查数量后在同一事务预留、建单和记幂等结果；异常整体回滚。[订单事务](../backend/src/agentmall/orders/service.py)、[库存并发回归](../backend/tests/test_order_concurrency.py)。这是受控数据库测试，不是生产吞吐承诺。
7. **工具调用失败处理。** 校验JSON、Schema、工具白名单、写入顺序、当前意图、角色和预算；非法批次整批拒绝，错误码与有界诊断字段脱敏，已提交Case仍可与后续PARTIAL并存。[模型控制](../backend/src/agentmall/agents/model_control.py)、[安全诊断](../backend/src/agentmall/infra/model_diagnostics.py)、[失败反馈回归](../backend/tests/test_v215_failure_feedback.py)。不存Prompt/Key或原始异常内容。
8. **PostgreSQL/pgvector的选择。** 业务事务、状态机、Jobs、Checkpoint和向量检索共用清晰的关系/事务边界；关键词为Jieba+PG全文ts_rank_cd，向量为本地BGE/pgvector，用RRF融合，默认不启用Reranker。[检索实现](../backend/src/agentmall/retrieval)、[检索验证](REAL_RETRIEVAL.md)。不能说成Elasticsearch/BM25或未经测量的性能优势。
9. **Token和费用控制。** Run预算限制models/tools/delegations/steps和输出Token；Live传输另外发送前持久预留费用、核对完整Usage并结算，UNKNOWN保留预留且停止。[GraphBudget](../backend/src/agentmall/agents/budgets.py)、[Ledger/Transport](../evals/provider.py)、[费用门禁测试](../backend/tests/test_eval_budget.py)。本地模型事件的OBSERVED_VALID不等于供应商账单，成本预留也不是实费。
10. **当前不需要Redis的原因。** 当前Jobs用PostgreSQL行锁及skip_locked领取，Thread advisory lock与epoch fence隔离旧Worker；已有PG承担持久性，没有引入新的缓存失效和双写边界。[Jobs](../backend/src/agentmall/agents/jobs.py)、[锁](../backend/src/agentmall/agents/locking.py)、[Worker](../backend/src/agentmall/agents/worker.py)。未来只有测量出队列/缓存瓶颈才讨论Redis，不声称它永远无用。
11. **模型错误与工具错误如何区分。** 先看实际拒绝阶段、Schema哈希、关联ID、原始证据是否足够，再分别归类产品、编排、模型、评测工具或证据不足。08历史错误码不足以归责，仍INSUFFICIENT_EVIDENCE/UNKNOWN；07是私有Host校验问题。[L8报告](EVALUATION_RESULTS.md)、[工程案例](ENGINEERING_CASES.md)。诊断增强不能补造历史响应。
12. **哪些能力真正验收。** 本轮独立重跑真实PG后端、固定六文件BGE专项、Vitest与Playwright，正式API/SQL核对三业务链和安全负例；代码与日志SHA见[回执](evidence/v217/verification.json)。录屏为SDK Mock/Fixture，不是新Live成绩；L8只有5题评分、1PASS/4FAIL，另3未评分/7未运行，Independent Holdout0。新Smoke、生产SLA和吞吐均未验证。

下面保留V2.16及更早阶段的问题与回执归属；其中候选、未Push及VIDEO_NOT_RECORDED属于历史阶段，不能当作当前状态。

---

# 10个可用源码展开的面试问题

当前本地候选为 **V2.16**，基于 V2.15 已合并的 `main d18161d1eb40667f4658e745d2f58369767d67f5` / tree `548b2f8e3180027bb179c2b42a1c4367984ff489`。基线 main CI 43718887411 已通过；V2.16 本地证据见[本轮交付](V216_PRODUCT_DEMO.md)，未 Push / PR / 发布 / 部署。本轮不运行真实 Provider，不改 L8 结果。V2.14 Release **ON_HOLD**；**RELEASE_COMMIT=UNBOUND**。

项目一句话：把模型建议、可恢复执行和确定性交易连接起来。项目有AI辅助；个人贡献须按实际设计、修改、复现与审核范围说明，不能将整个仓库描述为独立手写。

1. **为什么不让模型直接下单？** 模型只生成提案，Actor/Store来自认证，价格库存由服务端重新读取；独立Confirmation后才执行领域事务。购买批准不含付款退款批准。可沿[工具](../backend/src/agentmall/agents/specialist_tools.py)→[动作服务](../backend/src/agentmall/actions/service.py)→[订单事务](../backend/src/agentmall/orders/service.py)解释，再看[写顺序](../backend/tests/test_agent_write_sequencing.py)和[订单并发](../backend/tests/test_order_concurrency.py)。

2. **Checkpoint和幂等有什么区别？** Checkpoint回答图执行到哪，持久业务回执回答实际提交了什么；恢复必须先读取原结果，不能因为HTTP响应丢失就新建购买。入口是[持久图](../backend/src/agentmall/agents/durable_graph.py)、[Checkpoint](../backend/src/agentmall/agents/persistence.py)、[提交后故障](../backend/tests/test_commit_then_crash.py)。边界是受控故障测试，不承诺任意外部调用exactly-once。

3. **为什么需要Thread锁和epoch fence？** Worker可能重领任务，旧执行器仍可能存活。实际数据库Thread锁保护串行执行，epoch/token防止旧执行器再写Journal/Checkpoint/业务；队列时间戳不是锁租约。看[Worker](../backend/src/agentmall/agents/worker.py)、[锁](../backend/src/agentmall/agents/locking.py)、[进程测试](../backend/tests/test_worker_process.py)和[恢复交错](../backend/tests/test_recovery_interleavings.py)。202只代表入队。

4. **Single和Multi的收益如何判断？** 两者共享领域服务、HITL和预算，Multi增加任务派发与上下文校验成本。不能因角色更多就说效果更好。沿[Supervisor](../backend/src/agentmall/agents/supervisor.py)、[Specialist runner](../backend/src/agentmall/agents/specialists/runner.py)、[独立Oracle](../evals/oracles.py)讲协议，再以[L8完整分母](EVALUATION_RESULTS.md)回答：15计划/8启动/5评分/1通过，自建前瞻性、独立Holdout0，无法证明架构优势。

5. **一次自然语言失败怎样转成工程问题？** 01号比较有线/无线可能被折成一个硬约束，数量不足也可能显示done。当前改进将比较和明确单一要求区分，推荐款数与购买quantity分开，从可信候选事实判断短缺。看[偏好解析](../backend/src/agentmall/agents/product_preferences.py)、[Thread合并](../backend/src/agentmall/agents/memory.py)、[合成回归](../backend/tests/test_v215_recommendations.py)。款数/比较完成检查只用于推荐只读场景，purchase、return、bundle保留各自原完成语义；有界中文规则不能保证任意表达。V2.15验证汇总LOCAL_OFFLINE_VERIFIED，实模改善NOT_RUN。

6. **中文意图识别如何避免扩大权限？** “采购三只”应识别动作与商品数量，“介绍采购政策”不应变写请求；条件、否定、历史陈述和多个商品须保守处理。“生成退货提案”也不是批准退货。看[购买解析](../backend/src/agentmall/agents/purchase_intent.py)、[动作/量词](../backend/src/agentmall/agents/request_intents.py)、[回归](../backend/tests/test_v215_request_intents.py)。新语义支持不替代原Schema、HITL或领域资格校验。

7. **怎样证明“已执行”和“模型说执行”不同？** 当前状态观察仅接受runtime.facts中的可信Proposal ID、动作和状态，APPROVED不改成EXECUTED；不导出地址快照，不从模型总结授予新权限。看[最小状态投影](../backend/src/agentmall/agents/goal_receipts.py)、[状态回归](../backend/tests/test_v215_goal_receipts.py)；验证汇总LOCAL_OFFLINE_VERIFIED。[工作流回归](../backend/tests/test_v215_workflow.py)和[失败反馈回归](../backend/tests/test_v215_failure_feedback.py)分别约束两次独立确认、重放及已提交Case与后续失败并存。02号Case已REQUESTED与整题FAIL可以同时成立。

8. **为什么有HTTP200和Token数仍不能结算08号？** 原响应契约拒绝，冻结账本按安全协议保留UNKNOWN和CNY2.113536预留。新发现Host观察3654/293，但不在原封存，无原始响应/参数/响应哈希/Provider request-id；CNY0.009652仅费用算术。最终根因INSUFFICIENT_EVIDENCE。看[证据分层](EVALUATION_RESULTS.md)、[公开JSON](evidence/v215/l8-summary.json)。新[诊断模块](../backend/src/agentmall/infra/model_diagnostics.py)中，model_request_id为本地UUID，tools Schema和响应只存规范JSON哈希，响应哈希非HTTP字节；provider_response_id取body.id而非HTTP request-id。OBSERVED_VALID仅数字自洽，本地output_budget_state不代表供应商账单；旧single_agent.Guard不在捕获范围。不要把新诊断描述成修复了历史事故。

9. **RAG质量和事务正确性如何分开验证？** 检索是Jieba + PostgreSQL ts_rank_cd、本地BGE/pgvector和RRF，不是BM25；Reranker默认关闭，预算/租户/状态过滤与最终版本复核仍在服务端。看[检索实现](../backend/src/agentmall/retrieval)、[检索回归](../backend/tests/test_retrieval_hybrid.py)、[真实BGE实验](REAL_RETRIEVAL.md)。历史40条合成查询、单标注者结果不能证明当前模型完成购买任务。

10. **怎样向招聘者证明系统可以复现？** 用[6分钟无KeyDemo](DEMO_GUIDE.md)展示MockTransport/Fixture + 真实PG/Checkpoint，独立TEST_OPERATOR确认后唯一待支付订单、付款0、刷新读回。CI按[workflow](../.github/workflows/ci.yml)分后端/前端与严格release gate；成绩需绑定准确SHA和新日志。历史截图明确来源；MCP为独立外部入口、REMOTE_AUTH_NOT_IMPLEMENTED，VIDEO_NOT_RECORDED，无生产SLA或部署证明。

面试前至少独立走读一条完整调用链，并将自己的具体修改、错误定位过程和真实验证收据对应到[工程案例](ENGINEERING_CASES.md)。没有亲自验证或证据不足的内容直接标UNKNOWN；不要承诺量化性能提升、独立开发全部代码或生产级可靠性。


## V2.16 面试展开

用[5–7分钟讲解](DEMO_GUIDE.md)展示三条业务路径，再打开[批次重复派发修复](ENGINEERING_CASES.md#同批次重复-handoff-绕过已存在的防重复检查)：两个不同任务ID为何仍是同一个业务读取、为什么要在整批派发前检查、如何用不同订单的正向控制防止过度拦截。用SQL、确认消费及持久化事件证明结果，不只展示聊天答复。

说明本轮 UI/E2E 是真实后端加 SDK MockTransport / Fixture Embedding；真实 BGE 专项单独验证固定六文件和512维CPU推理。没有新真实模型结果，不能宣称 Multi-Agent 可靠性提升了某个百分比。L8只有5题评分、1通过，另3题未评分、7题未运行，独立Holdout0；本轮不改变这些成绩。


## RC1 面试材料使用

[RC1证据](V216_RC1_REVIEW.md)为本轮新跑的Backend1603/14skip、真实BGE13、Vitest146和Playwright128/0重试，不借用V2.15远程CI。可播放本地6:55静音原始录屏，按[时间码](DEMO_GUIDE.md#rc1-实际录屏)补充口头讲解；声明其无旁白、末段静态较长、录制器收尾超时，不能称精剪视频或真实DeepSeek实况。面试优先展示两次不同Proposal/Confirmation、Case与新订单的SQL增量，再解释模型失败与已提交事务为何可以同时存在。

产品代码在RC1未改；真实模型可靠性仍NOT_TESTED。先通过后续经授权的Push/PR各自CI，再由Owner单独决定合并，不把候选或CI成功说成Release。
