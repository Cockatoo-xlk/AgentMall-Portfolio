# 六类技术深挖：代码、证据和限制

本页是基于源码的答题提纲，不证明个人独立手写全部代码。说明自己实际负责的设计/实现/调试及AI辅助范围；不虚构用户量、QPS、SLA或模型提升。[当前证据矩阵](V214_RELEASE_CANDIDATE.md)与[本轮回执](evidence/v214/verification.json)提供版本归属。

## 1. 50个并发请求争10件库存，为什么不会超卖？

- **入口**：[orders/service.py::_execute_checkout](../backend/src/agentmall/orders/service.py)，[actions/service.py](../backend/src/agentmall/actions/service.py)。
- **设计**：先验证Actor/Store与不可变payload hash；锁定提案和Confirmation，按UUID排序锁全部商品行。拿锁后重新读取available、版本、价格与数据库时间，整数分计算；订单、全部预留、确认消费、幂等回执同事务提交。任意SKU不足则整笔回滚，没有先给部分SKU预留再放弃另一件。
- **证据**：[受控双事务竞争](../backend/tests/test_order_concurrency.py)、[Bundle原子性](../backend/tests/test_bundle_shopping.py)、[购物车事务](../backend/tests/test_checkout_cart_consumption.py)。
- **限制**：“50争10”是按此锁顺序推演的面试场景，不是本轮50并发压测成绩。已有测试不构成吞吐/SLA证明。
- **简答**：“库存由数据库锁后的当前事实决定，不由LLM或前端决定；确认和库存与订单同事务，只会全部成功或全部失败。”

## 2. 为什么不能让模型直接创建已付款订单？HITL与幂等怎样配合？

- **入口**：[工具校验](../backend/src/agentmall/agents/model_control.py)、[specialist_tools.py](../backend/src/agentmall/agents/specialist_tools.py)、[确认服务](../backend/src/agentmall/actions/service.py)。
- **设计**：当前轮明确意图和完整参数只允许准备Proposal。用户审阅不可变快照后独立Confirmation，原Resume执行确定性事务；订单生成后仍是PENDING_PAYMENT。付款/退款使用各自新提案与批准。稳定request_id/action/幂等键恢复原回执，换键也不能重复执行同一提案。
- **证据**：[写入顺序](../backend/tests/test_agent_write_sequencing.py)、[L6真实PG/SDK测试](../backend/tests/test_v213_l6_budget.py)、[确认隔离](../backend/tests/test_resume_authorization.py)。
- **限制**：模拟支付不接真实资金。业务幂等不等于外部模型请求Exactly-Once；自动测试批准标记TEST_OPERATOR。
- **简答**：“模型能建议和准备，不能代替授权；确认消费与业务写入共同提交，所以重放返回原结果，而不是再下单。”

## 3. Checkpoint与业务事务分别负责什么？Commit之后崩溃如何恢复？

- **入口**：[run_service.py](../backend/src/agentmall/agents/run_service.py)、[persistence.py](../backend/src/agentmall/agents/persistence.py)、[worker.py](../backend/src/agentmall/agents/worker.py)、[jobs.py](../backend/src/agentmall/agents/jobs.py)。
- **设计**：Legacy Sync在HTTP内执行；Durable Async把Context/Run/Job持久化后返回202，由独立进程运行原Executor。原Thread advisory lock、epoch/token和实际锁状态限制当前写入者；节点Journal先保存已提交结果，官方Checkpoint保存图位置。恢复时查Journal/业务幂等回执，而不是猜测上次是否成功。
- **证据**：[真实进程故障测试](../backend/tests/test_worker_process.py)、[Commit后崩溃](../backend/tests/test_commit_then_crash.py)、[Checkpoint状态](../backend/tests/test_checkpoint_state.py)。[V2.12报告](evidence/v212/report.md)绑定45份历史进程回执；本轮不把旧回执冒充新实验。
- **限制**：Worker是at-least-once尝试；已发出的模型HTTP请求可能重发。202不是执行成功，也未证明生产SLA、跨地域容灾或通用Exactly-Once。
- **简答**：“Checkpoint回答执行到哪，领域回执回答写入了什么；锁与Fence拒绝旧Worker，恢复沿原业务身份读取已提交结果。”

## 4. Prompt Injection、跨Store和MCP工具越权怎么阻断？

- **入口**：[Actor认证](../backend/src/agentmall/identity/service.py)、[runtime.py](../backend/src/agentmall/agents/runtime.py)、[MCP Gateway](../backend/src/agentmall/mcp_gateway/server.py)。
- **设计**：服务端从认证身份建立ActorContext，不接受模型提供user_id/role/store_id。TaskSpec、引用来源、角色白名单、严格Schema和整批校验先于工具执行；商品描述/检索文本是数据，不是系统命令。MCP每次调用复用同一领域服务，Discovery按角色收窄；没有批准、付款、退款、发布或任意SQL工具。
- **证据**：[商品注入](../backend/tests/test_prompt_injection.py)、[非法批次](../backend/tests/test_v213_l2_batch.py)、[独立SDK Client与租户隔离](../backend/tests/test_mcp_gateway.py)。
- **限制**：MCP只承诺stdio/localhost演示，**REMOTE_AUTH_NOT_IMPLEMENTED**。本地Bearer不是完整OAuth，也不能把Prompt提示词当安全边界。
- **简答**：“MCP解决接口协议，不提供业务授权；最终权限由已验证身份、工具校验和数据库领域规则共同决定。”

## 5. 全文检索与BGE如何结合？为什么默认关闭Reranker？

- **入口**：[ingest.py](../backend/src/agentmall/retrieval/ingest.py)、[search.py](../backend/src/agentmall/retrieval/search.py)、[reranker.py](../backend/src/agentmall/retrieval/reranker.py)。
- **设计**：真实目录字段生成文档、中文品类名、内容哈希和版本；Jieba分词，PostgreSQL `ts_rank_cd`全文检索与BGE/pgvector并行召回，RRF融合。这里**没有实现BM25**。Store/属性/预算/库存/状态过滤在LIMIT前，最后再读取当前事实。旧索引不能冒充最新商品。Cross-Encoder只重排有限候选，不能补回未召回结果。
- **证据**：[V2.10报告](evidence/v210/report.md)、[固定40条合成查询与模型版本](REAL_RETRIEVAL.md)。Test Hybrid→Reranker：Recall@5 92.53%→91.84%，NDCG@5 95.82%→97.40%，P50 22.35→654.77ms。
- **限制**：本地Linux aarch64/CPU、单标注者、小型合成查询；“test”分片不代表独立外部Holdout。无答案处理仍差，不能只展示排序收益。当前默认Demo是Fixture，不加载这些真实模型。
- **简答**：“重排有有限排序收益，但没提高整体召回且CPU成本明显上升，所以默认关闭；保留对比数据而不宣称普遍提升。”

## 6. 为什么Multi不一定优于Single？B2的真实失败怎么排查？

- **入口**：[Supervisor](../backend/src/agentmall/agents/supervisor.py)、[return_handoff.py](../backend/src/agentmall/agents/return_handoff.py)、[read_completion.py](../backend/src/agentmall/agents/read_completion.py)、[evals Oracle](../evals/oracles.py)。
- **设计**：分角色缩小权限、形成可验证交接，也增加规划、依赖与调用预算成本。退货评估/退货写提案/替代检索/购买写提案是四个独立语义任务，退货与购买要两份Confirmation。L6凭完整只读回执省去无必要结束轮次，复用可信assessment但仍持锁重验，Order仍由模型选品并读取最新商品；没有提高12次模型调用上限。
- **证据**：`b5d6a685…`真实五题配对Pilot：Single5/5、Multi4/5，56请求；L1/L3批次与只读交接失败，L5预算耗尽，L7同L6源码6请求后CONTEXT_SCOPE_VIOLATION。L6离线11/10调用路径通过，不等于L7实模通过。[逐版本来源](V214_RELEASE_CANDIDATE.md#真实模型历史)。
- **限制**：五题属于开发集、每架构一次，不是可靠性统计；L7具体非法字段未保存，不能编造完整模型输出或据诊断数字断言发生越权写入。本轮冻结功能，不进入L8。
- **简答**：“我把真实失败拆成模型选择、编排/约束、工具和环境证据来查。模型预算内的离线路径证明可行性；真实B2仍失败，就保留失败和信息缺口，而不增加预算或降低Oracle。”
