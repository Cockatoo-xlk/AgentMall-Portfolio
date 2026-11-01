# 首次真实 Playground Smoke — 待批准，NOT_RUN

这不是执行许可。T15-A 新增真实付费请求 0，没有读取真实 API Key、创建正式授权回执或正式 Live 预算账本。历史 T12 授权已消耗，不能复用。

拟使用 DeepSeek `deepseek-flash`，官方标识 DeepSeek-V4.1-Flash-1017；固定 `https://api.deepseek.com/chat/completions` 标准 function tools，禁用 thinking/streaming，temperature0、max_tokens2048、retries0。不使用 hosted Search/Fetch、beta strict 或第三方端点。官方资料与核验时间见 [provider-reference.json](provider-reference.json)；执行前必须重新核对模型和24小时有效价格快照，不能静默延长。

建议待批准硬上限：最多人民币5元、30次模型请求、1200秒、累计输入4,194,304 tokens、累计输出24,000 tokens。按峰值 cache-miss 输入2元/百万、输出8元/百万预留；缓存/低谷只作为可能折扣，不提前放大预算。每 Run 原12次/90秒/12k输出预算同时生效。超过上限立即停，不自动追加；用户可批准更低上限。

仅限三个合成场景，是否执行及具体次数须用户明确批准：

| 场景 | 输入范围 | 独立验收 |
|---|---|---|
| Single 本人订单读取 | 查看本人订单，不写业务 | 真实Provider元数据与list_orders；无新提案/订单/付款 |
| Multi 商品与购买 | 300元以内静音键盘、演示宿舍 | Supervisor模型路由、检索/商品事实、合法购买提案，先WAITING_INPUT无订单；用户点击独立批准后仅一笔PENDING_PAYMENT；详情页再独立批准模拟付款 |
| Multi 退货+替代购买 | 已经由人工通过原API准备的合成DELIVERED订单，质量问题退货及500元以内替代键盘 | 订单事实/资格/政策来源；退货和购买两张独立确认；Case仅REQUESTED，付款另批；不自动退款 |

环境仅新项目 `agentmall-playground-local`、127.0.0.1:55441/8017/5187、agentmall_test、新test_/cp_及独立environment UUID。不得写历史55432/55433实例、历史账本或封存证据。准备与容量检查见 [启动说明](../../LIVE_PLAYGROUND.md)。本轮没有构建含真实BGE的Live镜像或验证其容量；这是首次Smoke前置，不可省略或偷偷改Fixture。

授权必须绑定最终源码指纹、环境UUID、全新session_id、最新价格时间和policy SHA。用户确认后才可记录私有新授权引用；本方案不预填真实授权。本地服务端环境安全加载Key，浏览器/Trace不接触。公开回执仅保留Provider request/response ID、model、HTTP状态、Usage、耗时、费用上界、数据库/Checkpoint不变量摘要；真实平台账单不可得仍UNKNOWN。

Provider错误、超时、响应丢失、缺失Usage、格式错误、非法工具、未知费用保留发送前预留并停止整份账本。先GET Thread/Proposal/Order/Case检查已完成业务；禁止换request_id/Run/session补跑，禁止用新账本延长费用。已经发出但Checkpoint尚未保存的模型节点可能MODEL_REPLAY_BLOCKED，需要保留失败证据，不宣称任意崩溃下模型exactly-once。

验收必须包含真实网络与Provider元数据、浏览器Live服务端身份、实际模型工具路径、独立人工确认、PG独立连接终态、Checkpoint和预算账本一致性。MockTransport成功仅OFFLINE_SDK_VERIFIED；只有真实Smoke之后才评定LIVE_AGENT_VERIFIED。失败/未运行项完整保留，不因安全拒绝变少就宣称任务成功。

该方案不授权Push、远程Actions、Release、云部署、真实资金、正式评测或后续任务。
