# V2.17 · 12个能沿源码解释的面试问题

用[离线3分30秒成片](media/v217/agentmall-v217-demo.mp4)展示产品，再用[评测汇总](EVALUATION_RESULTS.md)说明三个真实成功案例各自的Source与失败记录。产品代码验收提交为 `759391cd6c33a1bbc906df34e6de87126cb53dac`；最终Backend1824 PASS / 0 FAIL / 16 SKIP，不代表该源码已做新Live验证。AI辅助开发，个人贡献按实际实现、修改、复现与审查范围陈述。

1. **为什么使用LangGraph？** 需要显式表示路由、状态、中断、恢复和失败分支，持久图支持interrupt/Resume与Checkpoint。LangGraph不替代交易授权，也不证明订单已提交；[持久图](../backend/src/agentmall/agents/durable_graph.py)、[临时图](../backend/src/agentmall/agents/graph.py)、[恢复回归](../backend/tests/test_checkpoint_resume.py)分别说明边界。

2. **Supervisor怎样分派任务？** 模型提出结构化任务，服务端先校验角色、实体来源、依赖、批次与预算，再执行Specialist。Actor/Store与批准权限不能由模型声明；LangChain create_agent处理模型/工具middleware，业务写入仍在领域服务。[Supervisor](../backend/src/agentmall/agents/supervisor.py)、[Specialist执行](../backend/src/agentmall/agents/specialists/runner.py)、[同批重复派发回归](../backend/tests/test_v216_agent_runtime.py)。

3. **为什么Checkpoint之外还要业务回执？** Checkpoint记录图走到哪里，持久回执回答订单/Case究竟是否提交。响应丢失后先读取原回执，不能换请求身份重复下单；Thread锁、epoch/token fence与Journal防止失效执行者覆盖新执行。[持久化](../backend/src/agentmall/agents/persistence.py)、[Worker](../backend/src/agentmall/agents/worker.py)、[提交后故障](../backend/tests/test_commit_then_crash.py)。外部Provider请求仍没有任意崩溃下通用exactly-once保证。

4. **HITL如何与事务结合？** Proposal持有服务端快照；用户独立GET审查后创建绑定身份和具体提案的Confirmation，显式Resume再验证版本、时效及状态，事务内消费确认并提交业务。退货批准不能用于替换购买，购买批准也不包含付款退款。[动作服务](../backend/src/agentmall/actions/service.py)、[Resume](../backend/src/agentmall/agents/resume.py)、[双确认回归](../backend/tests/test_baseline_fairness.py)。

5. **如何防止重复下单和交易后误收尾？** 稳定请求身份、一次性确认消费和持久幂等回执保证重放不增写；UI禁用按钮只是辅助。最终修复移除“订单成功就结束整条请求”的捷径：原目标、回执、prior results继续Single流程，独立查询必须实际执行；重复prepare_checkout仍返回REPEATED_TOOL_CALL。[订单服务](../backend/src/agentmall/orders/service.py)、[P2回归](../backend/tests/test_final_p2_contract.py)。纯购买使用既有结构化结束信号，不提高预算。

6. **如何避免库存超卖？** 领域事务按固定顺序锁定商品行，重读状态、版本、价格及可用库存，在同一事务里预留库存、创建订单并记录幂等结果，失败整体回滚。[订单事务](../backend/src/agentmall/orders/service.py)、[并发回归](../backend/tests/test_order_concurrency.py)。这是受控数据库正确性测试，不能转述为生产QPS或吞吐提升。

7. **模型工具调用失败如何处理？** 在执行前检查JSON/Schema、工具白名单、角色、意图、写入批次与预算；非法批次不执行，已提交的事务回执仍保留。错误码、关联ID和Schema哈希帮助定位阶段，但证据不足不能强行归责模型。[模型控制](../backend/src/agentmall/agents/model_control.py)、[结构化诊断](../backend/src/agentmall/infra/model_diagnostics.py)、[失败反馈](../backend/tests/test_v215_failure_feedback.py)。不持久化Key或不必要的敏感请求内容。

8. **PostgreSQL和pgvector分别做什么？** PG承担关系事务、业务状态、Jobs和Checkpoint；pgvector存储本地BGE向量。检索是Jieba + PG全文ts_rank_cd与向量检索，经RRF融合，默认不启用Reranker；它不是Elasticsearch/BM25。[检索实现](../backend/src/agentmall/retrieval)、[真实检索边界](REAL_RETRIEVAL.md)。商品事实与最终价格库存必须来自服务端，不由用户报价或LLM补造。

9. **如何控制Token、费用与UNKNOWN？** Run预算限制models/tools/delegations/steps与输出Token，既有Live传输在发送前持久预留并核对Usage。用量或预算UNKNOWN时停止、保留预留，不自动重试；供应商实际账单UNKNOWN单列，不与SETTLED Usage混为一谈。[Run预算](../backend/src/agentmall/agents/budgets.py)、[Ledger](../evals/provider.py)、[费用测试](../backend/tests/test_eval_budget.py)。成功案例的保守峰值估算不是实际账单，也不是今天的报价。

10. **为什么当前不需要Redis？** 当前Jobs以PG行锁和skip_locked领取，Thread advisory lock与epoch fence隔离旧Worker；已有PG承担持久性，没有为未经测量的需求增加缓存失效和双写边界。[Jobs](../backend/src/agentmall/agents/jobs.py)、[锁](../backend/src/agentmall/agents/locking.py)。未来由实测瓶颈决定是否引入Redis，不声称它永远无用。

11. **怎样区分产品、模型与评测工具错误？** 先还原拒绝阶段、Schema、请求关联、SQL和原始证据。H01原SQL商品投影缺category，H02交易后重复写被守卫拒绝，H04跨商品属性被混合；修复后用开发回归验证，但原评分不改。L8第08题仍INSUFFICIENT_EVIDENCE/UNKNOWN，不能凭错误码归责；07是私有Host快照比较问题。[完整报告](EVALUATION_RESULTS.md)、[作用域实现](../backend/src/agentmall/agents/product_preferences.py)、[证据回归](../backend/tests/test_post_holdout_product_fix.py)。

12. **哪些能力有真实证据，哪些没有？** B成功用Source `115905a3cb45bfd2b70384fec7375be9243a6f92`，A/C成功用`8171e5576180e8827b78fff3d6c9f58051729f08`；C为81.333秒、11HTTP、Case/订单各+1、两份确认消费、支付退款+0。它们是分别执行的功能案例，不是同版3/3；首次A FAIL/B PASS/C NOT_SCORED、原四题与L8结果都保留。最终1824项Backend属于离线SDK Mock/Fixture；早期BGE13、Vitest146、Playwright129另有原回执，本次未重跑。[最终验收与Skip](V217_INTERVIEW_READY.md#最终源码验收)。没有独立盲测可靠性、生产部署、用户规模或SLA证明。

## 面试展示与安全边界

沿“用户输入 → 可信商品事实 → Proposal → 独立Confirmation → Resume → SQL回执 → Checkpoint”讲一条完整链路。遇到失败先说明哪些事实已提交、哪些目标未完成，再解释守卫为何拒绝；不要只展示成功聊天文本。

历史Docker Socket整改删除8个Exited风险容器，保留Volume/镜像；普通Worker仅使用安全Native入口，Docker管理留在可信Host。它不是生产安全认证，历史越权行为没有完整审计证据时保持UNKNOWN。[隔离与限制](KNOWN_LIMITATIONS.md#容器隔离与保留资源)。

项目为AI辅助开发，只陈述能独立解释的个人贡献。[简历稿](RESUME_PROJECT.md)与[演示指南](DEMO_GUIDE.md)提供公开展示入口；私有原始日志、Key、数据库密码、真实身份及Gold不对外上传。Release ON_HOLD，GitHub交付和新Live仍需单独授权。
