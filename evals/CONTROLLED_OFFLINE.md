# V2.16 受控离线验证入口

此入口只运行 **OFFLINE_ONLY / CONTRACT_TEST_ONLY / SYNTHETIC_DEVELOPMENT** 契约测试。
使用正式 Agent / Proposal API、真实 PostgreSQL 事务和真实 DeepSeek SDK；模型 HTTP
响应来自 `httpx.MockTransport`。没有真实供应商请求或真实模型有效性结论。
不读取旧 DEV/TEST 任务集、Holdout/Gold 或未运行的 L8 任务，不依赖旧 L8 私有框架。
旧 `evals/run.py`、数据集和 Oracle 保持原有语义。

## 复现命令

从仓库根目录执行，使用已配置的本地测试数据库：

```bash
PYTHONPATH=backend/src:. backend/.venv/bin/python -m evals.controlled_offline
```

测试数据库沿用现有 `AGENTMALL_TEST_DATABASE_URL`；测试守卫要求本机
`agentmall / agentmall_test`，每个用例创建并清理独占业务和 checkpoint schema。
此命令不会启动 Docker、读取供应商密钥或连接真实供应商。缺少 PostgreSQL 时直接失败，
不能把跳过或环境错误记为通过。也可选择 `--scenario A`、`--scenario B` 或 `--scenario C`。

等价的原生 pytest 命令：

```bash
PYTHONPATH=backend/src:. backend/.venv/bin/python -m pytest --ci-offline-core -q \
  backend/tests/test_v216_controlled_eval.py backend/tests/test_v215_workflow.py
```

A 验证推荐不生成提案、确认或订单。B 分别验证明确批准和明确拒绝；读取提案、提交决定、
Resume 是三个独立调用，提交决定后仍无订单、无额外模型请求且 Run 仍为 `WAITING_INPUT`。
C 复用 `test_v215_workflow.py` 中的合成退货加替代购买契约：退货和购买各需独立确认，
确认不可跨提案复用；重复相同 Resume 不再执行业务或调用模型，已提交退货不能被后续解析失败抹去。
这些是固定开发场景，不是新增盲测集。

## 明确的操作接口

`Operator` 是薄的正式 API 辅助类，不解释任务、不决定是否批准、不重试、不自动推进，
也没有 Recover 方法。它在上述 pytest 离线边界内使用已认证 ASGI client。
真实应用的人工操作仍应通过应用页面/API，由操作者逐步执行。

```python
operator = Operator(env[0], buyer)
tid = await operator.create_thread()
run = await operator.start(tid, original_request_id, synthetic_user_message)

# 只读：找到指定 Run，读取当前提案快照；不会批准、拒绝、Resume 或 Recover。
inspection = await operator.inspect(tid, run["id"])

# 操作者先检查 inspection["proposal"]["canonical_payload"]。
# 然后明确选择一种决定；测试中的选择写在测试代码中，不从任务脚本自动匹配。
confirmation = await operator.decide(inspection, decision="approve")  # 或 "reject"

# 独立操作：使用该提案的确认和显式 request_id 才 Resume。
done = await operator.resume(
    tid, inspection, confirmation["confirmation_id"], resume_request_id
)
```

响应丢失或错误会交还调用者。辅助类不会推测成功，不会换 Run ID 重跑，也不会自动恢复。
需要观察状态时再次调用只读 `inspect`；相同 Resume 的显式重放须保留原 request_id。
C 的下一个提案必须重新 inspect、明确决定并单独 Resume。

## 冻结后评分与 Usage

运行阶段只读取正式 API。`freeze(scenario_id, run, events)` 将运行身份、状态和分页读取的
事件复制为不可变 JSON bytes，并计算 SHA-256。`score` 只读取这些 bytes、核验 hash，
不会访问 API 或执行业务。契约预期在调用端明确给定；没有调用者传入的成功布尔值。
`run_status` 和 `evaluation_success` 分开输出：等待输入可以满足等待契约；`COMPLETED`
也可以因不满足契约而评分失败。真实业务变化由集成测试独立查询已提交 SQL 事实确认，
这个小型状态/错误评分函数不替代原有业务 Oracle。

hash 只绑定本地观察，不提供签名或外部认证。调用者可将 `FrozenEvidence.payload` 与
`FrozenEvidence.sha256` 保存为审阅证据；本入口不会修改已有评测产物。

只有模型结束事件数量与该 Run 的模型调用计数一致，每条 Usage 为合法非负整数、
供应商 Usage 状态为 `OBSERVED_VALID` 且输出预算为 `RECONCILED` 时才累加模拟 token。
缺失事件、缺失 Usage、解析失败、Usage 状态 `UNKNOWN` 或预算 `UNRESOLVED` 均保留
`usage=UNKNOWN`、`billing_state=UNKNOWN`，不能以零 token 或 `SETTLED` 代替。
已知 MockTransport token 的账单状态是 `NOT_APPLICABLE`，不能作为实际费用或供应商结算。

## 旧 UserSimulator 的准确边界

源码依据为 `evals/simulator.py` 的 `UserSimulator.continue_run`、`recover`、
`deterministic_actions`，以及 `evals/run.py` 的 `_run_episode`；这里不修改这些行为。

- 旧 Simulator 是有限的预声明用户/商家脚本，不由 LLM 自由决定授权。没有匹配的声明决定时，
  它以 `UNEXPECTED_CONFIRMATION` 停止；声明 `wait` 会直接返回当前 Run。
- 但它确实会自动推进：最多六轮循环内，遇 `RUNNING` 或 `EXECUTION_INTERRUPTED`、
  `EXECUTION_TIMEOUT`、`DATABASE_UNAVAILABLE` 会自动请求正式 Recover API。
- 有提案时，它读取提案，并匹配尚未使用且 action_type 相同的脚本决定；批准 CHECKOUT
  时检查脚本数量和最高总价。随后自动发出 confirmation，并在同一个循环内自动 Resume。
  澄清也自动消费预声明回答再 Resume。所谓“不是 LLM 决定授权”不等于“没有自动确认”。
- Resume 返回 500 时它读取持久状态后进入下一轮；回执丢失/重放场景有专门注入。
- `_run_episode` 在 `continue_run` 后保存 agent answer 时的资源快照，再执行
  `deterministic_actions`：预声明付款/取消、退款/撤回、商家审核/收货或工单处理等。
  这些动作明确记录 `agent_autonomous=False`，不能归为 Agent 自主完成的业务。
- 旧 runner 最后才调用原 Oracle；新入口既不复用旧 Simulator 的自动推进，也不重写旧 Oracle。
