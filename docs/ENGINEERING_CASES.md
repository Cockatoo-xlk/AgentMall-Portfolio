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
