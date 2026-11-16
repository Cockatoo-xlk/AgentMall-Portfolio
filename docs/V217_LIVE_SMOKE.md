# V2.17 exploratory product smoke · 冻结方案

状态：**LIVE_SMOKE_READY_AWAITING_AUTH** 表示输入和离线准备已完成，**不表示获准执行**。本轮 Live 授权0、Key读取0、Provider请求0、实际费用0。目的为 `EXPLORATORY_PRODUCT_SMOKE`；自建、非盲测、非第三方、非生产可靠性认证。独立Holdout=0。

## 身份与顺序

Source基线为已合并的 main `8e21bdcad3170487626a17ccda0f624457bccd26`，最终执行Source须绑定本轮CLEAN本地提交。任务、初始状态、预期变化和顺序在[不可自动执行的提案](../evals/proposals/v217-product-smoke.json)中，顺序固定 **A Single比较 → B Single购买两件 → C Multi质量退货与有线替换购买**。这些是新建产品Smoke输入，不加载L8 TaskSpec、Gold或09—15，不改写原统计。

每题使用全新独占PG业务/Checkpoint Schema、Run/Thread/Execution、Ledger及测试身份命名空间。合成seed的稳定UUID可相同，数据库和业务状态不得共享。C仅在正式API完成合成原订单、模拟支付、发货和送达后取基线；Setup的订单1、模拟付款1、确认2须逐项记录并排除于Agent增量。`delivered_order_id`只能来自该题Setup的正式API回执，核对Actor/Store后将解析后的实际输入在Episode开始前再次冻结；不接受旧订单ID。

静态校验与最终提交绑定命令（不会创建Run、Outer、Ledger或Sender）：

```sh
PYTHONPATH=.:backend/src backend/.venv/bin/python -m evals.product_smoke validate evals/proposals/v217-product-smoke.json
# 仅在本地最终提交且CLEAN后，将回执写入新的Git忽略路径：
PYTHONPATH=.:backend/src backend/.venv/bin/python -m evals.product_smoke freeze evals/proposals/v217-product-smoke.json --output .playground/v217-smoke-binding.json
```

`freeze`回执包含准确Commit/Tree、提案原始字节SHA256及任务顺序。它是自建预注册记录，不是授权、签名或独立性证明。最终外部绑定还记录操作员协议、本文件、断言源码、固定BGE六文件、模型与价格来源快照的SHA；避免Git文件自包含自身Commit造成循环。

## 模型与费用

固定请求 `deepseek-flash`、`thinking.type=disabled`、`temperature=0`、非流式。官方文档当前映射为 DeepSeek-V4.1-Flash-1017；这只是文档映射，实际回包模型必须记录，不能伪造不可变权重身份或缺失的fingerprint。[模型/价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[更新日志](https://api-docs.deepseek.com/zh-cn/updates/)、[模式参数](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。

每题上限：HTTP12 / Models12 / Tools16 / Delegations4 / Steps24，累计输入3145728、输出12000 Tokens，Episode90秒、Outer300秒，**CNY2.50**；三题累计 **CNY7.50**。Episode包含全部HITL等待，Resume不重置；Outer从实际资源初始化前开始，授权等待不计入；过期后仅只读取证。

本次官方核验的峰值费率为输入缓存未命中2元/百万、输出8元/百万；闲时1/4，缓存命中峰值0.04/闲时0.02。北京工作日非节假日9–12及14–18为高峰。预留始终按峰值、全部未命中计算，不承诺享受优惠。完整1,048,576上下文加单次2048输出的发送前预留为 **CNY2.113536**；费用门禁可先于HTTP12终止，不能承诺2.50元可完成12次。实际执行前逐题重新核验24h有效期及官方参数，变更须记录新身份，不刷新旧时间戳。禁用付费Search/Fetch/文件解析及未声明服务端工具。

## 复用执行路径与实际权限

复用普通 `create_app`、现有 `evals.provider.BudgetLedger/MeteredTransport/live_model`、正式Agent路由与 `evals.controlled_offline.Operator` 的逐次读取/决定/Resume接口，真实BGE与既有SQL/业务断言。**不调用旧 `evals.run` 的自动UserSimulator，不使用L8私有Host平台。** 普通应用默认MODEL_DISABLED；没有Owner许可不得构造真实模型或Sender。

下一次获授权的具体执行前，仍需按现有组件核验：每题/批次累计上限、当前价格、输入Token门禁、90秒/300秒跨HITL时钟及专属资源身份。当前新增CLI只校验/冻结，**没有Live执行命令，也没有声称新Live接线已通过真实集成验收**。授权后如发现现有组件不能落实任一上限，应停止并如实报告，不以文档替代硬门禁。

Owner授权须绑定最终Source/Tree、提案与协议SHA、BGE、模型/价格快照、三题顺序、每题2.50/累计7.50、操作员身份和独占资源范围。凭据只在有效授权与本轮初始化/BGE核验后，由可信Host一次读取，可信内存持有，经匿名FD交付；不发到聊天、argv、文件、子进程环境或日志。旧L8/R5许可不继承。

## HITL与API/SQL断言

Agent输入只用 `agent_input` 的 `mode/message` 投影；Host Fixture和评分条件不传Prompt、工具结果或Supervisor。原始用户需求中的商品/预算事实不能删除。每份提案独立GET并检查Actor、Store、Run、Thread、Interrupt、动作、canonical payload、hash和有效期；操作员明确批准/拒绝后检查Confirmation成功，再单独Resume，保留不同request_id；不自动批准、批量批准、Resume或Recover。

| 任务 | 正式API事实与独立SQL断言 |
|---|---|
| A | 正式产品GET核对两个不同商品的价格≤40000分、静音属性、连接能力与当前库存；候选集合覆盖wired/wireless；Proposal/确认/订单/付款/退款增量0 |
| B | 批准前订单与预留增量0；K68数量2、单价19900、总价39800、地址demo_dorm；批准后唯一PENDING_PAYMENT订单+1、reserved+2、on_hand不变；原request_id读回不新增订单 |
| C | 确定性资格先核验；RETURN_REQUEST独立确认消费后Case REQUESTED+1、替换订单尚无；第二份CHECKOUT确认后K68数量1、总价19900、PENDING_PAYMENT+1、reserved+1；两个确认ID不同且消费；付款退款增量0 |

可执行断言出处：[产品API/SQL场景](../frontend/tests/product-demo.spec.ts)、[连续场景](../frontend/tests/interview-demo.spec.ts)、[独立检查/决定/Resume](../backend/tests/test_v216_controlled_eval.py)。这些本轮执行为CONTRACT_TEST_ONLY，不是三题新Smoke的模型成绩。Live评分时只能复用断言逻辑与正式API/独立SQL事实，不把Mock程序安装为真实决策器。Run COMPLETED仅必要条件；任何业务条件不满足仍FAIL。

## 停止与证据

每题正式Episode只启动一次。普通业务或模型FAIL保留原结果，在费用/写入明确且安全封存后继续下一题；不可重试、换模型、换Run、调Prompt、改题或改断言。Provider Usage、费用或业务写入UNKNOWN，以及权限/身份/预算/时间异常，立即停止整个Smoke；未启动题NOT_RUN，三题分母保留。

逐题 `RUN → FREEZE → EXPORT → VERIFY → score → owner-scoped cleanup`。保存准确Source/Task/Execution、脱敏RunEvent、Checkpoint元数据、Proposal/Confirmation消费、SQL前后差异、Ledger状态、HTTP/模型/工具/派发/steps、Token与时钟、原业务判定及失败分类。原始Prompt、Key、授权头、地址隐私和Checkpoint内容不公开；模型诊断的规范JSON哈希不是原始HTTP字节或Provider账单。证据/所有权/关闭状态不足则保留本轮资源，禁止清理历史对象。

三题仅报告准确分子/分母、NOT_RUN、耗时、费用估算与真实账单UNKNOWN字段；一次成功不证明可靠性或架构优势。新结果独立版本，不覆盖L8 PASS1/FAIL4/NOT_SCORED3/NOT_RUN7。
