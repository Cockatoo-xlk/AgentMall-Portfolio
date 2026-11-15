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
