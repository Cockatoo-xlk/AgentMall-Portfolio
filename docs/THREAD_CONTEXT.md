# Thread 内的多轮结构化上下文

T16-A 在现有 `/agent/workspace` 上增加版本化偏好与候选编号。默认演示仍是 Fixture；本轮工程验证另有明确标记的 SDK MockTransport。两者都不是新的 DeepSeek Live 证据。

## 三轮操作

登录 buyer1，创建 Multi 或 Single Thread，然后依次输入：

1. `推荐一款300元以内静音键盘`
2. `改成无线的，预算提高到400元`
3. 在当前编号名单中选择可用商品，例如 `就买第二款，一件，送演示宿舍`。

第三轮只准备最新提案。核对商品、数量、地址、金额和有效期后，用户单独点击批准并 Resume；服务端创建待支付订单。付款仍从订单详情进入独立模拟支付确认，不复用购买确认。普通 Fixture 目录不保证存在三款无线键盘；测试专用 MockTransport 环境会建立三款明确标记的合成商品，不改变默认 Seed。

偏好摘要显示品类、预算、噪声、连接方式、版本和更新来源。可用预算表单、清除按钮或下一轮明确输入修改偏好。刷新后重新登录，使用原 URL 的 Thread ID 恢复；JWT 仍只在内存。历史 Run 可展开查看事件和业务资源，但历史引用不是当前报价。

## API 协议

所有路径使用 `/api/v1`，Actor 和 Store 由服务器认证与配置确定。

- `GET /agent/threads/{id}`：原 Thread/Runs，加 `context={version,preferences,provenance,updated_at,candidate_sets}`。只返回本人本店铺上下文。
- `POST /agent/threads/{id}/runs`：原 `request_id,message,constraints` 加 `expected_context_version`、可选 `candidate_set_id`。浏览器首次发送版本0，随后发送刚读到的版本。编号引用必须同时绑定正在展示的名单ID。已启用上下文的 Thread 不允许省略版本。
- `PATCH /agent/threads/{id}/context`：`{request_id,expected_version,operations:[{op,field,value?}]}`。`SET` 只填空值或重复相同值；`REPLACE` 明确替换；`CLEAR` 删除，不能带 value。字段只允许 category、max_price_cents、noise_preference、layout、connection、keyboard_type、usage。值仍通过严格 Constraints 枚举与范围校验。该接口不调用模型。
- Run 返回 `context_snapshot`：创建时接受的结构化版本、偏好、当前新鲜意图、选中实体及名单来源。后续更新不改写该快照。补充输入通过原 Resume Journal 保存新的版本化绑定，原 Run 快照仍不变。

相同 request_id、相同输入先重放原 Run/更新回执，再检查当前版本。输入不同返回 IDEMPOTENCY_CONFLICT。旧客户端未启用上下文的 Thread 保留原无状态契约及原请求哈希；旧历史 Run 的空快照兼容。不会将旧请求自动升级成新的购买意图。旧无状态客户端的新请求若包含编号、指代或候选名单ID，必须先采用版本化协议；不会把“买第二款”交给模型猜测。

## 存储与恢复

迁移 `0007` 增加 `agent_thread_contexts`、`agent_candidate_sets`、`agent_context_mutations` 和 `agent_runs.context_snapshot`。候选的复合外键保证产生 Run 与 Thread 一致；上下文版本非负，Mutation 请求唯一。迁移不改既有商品、订单、库存或 Checkpointer 表，Checkpoint 继续使用独立 `cp_` schema。

偏好更新和新 Run 快照在同一个 PostgreSQL 事务提交。Thread Advisory Lock、行锁和版本比较防止并发覆盖；RUNNING、WAITING_INPUT 或可恢复 PARTIAL 阻止新冲突请求。节点仍通过现有 Epoch Fence、Journal、官方 Checkpointer 和持久预算执行。检索产生的候选写入可恢复节点状态；只有当前合法执行者在最终事务中发布名单，且必须匹配接受的偏好版本。旧执行者和旧名单不能覆盖新上下文。

候选只从经过 Actor/Store 校验的检索 DTO 产生，固定保存 rank、product ID、catalog_version 和价格基线。多个名单并存时界面要求明确选择。偏好变化使旧名单失效；缺少名单、越界编号、陈旧版本或模糊引用要求澄清。选择时和准备提案前再次读取商品；即便 get_product 刷新了临时事实，也不能覆盖用户所见的不可变价格/版本基线。下架、涨价、版本变化或无库存均不能沿用旧报价。

## 语义边界

结构化偏好仅保留白名单字段。明确的新预算替换旧预算；不会对跨轮300→400继续取较小值。同一条消息出现不同预算、冲突连接方式，或文字与结构化约束冲突时拒绝写入并要求澄清。`忘记之前的预算`、`不要无线了` 有确定性清除行为；其余字段可通过严格 PATCH 明确清除。未识别的自然语言不成为新的可信偏好，应使用明确数值、枚举或表单补充。

数量、地址、购买/退货意图、Confirmation、Interrupt、费用授权都不作为跨轮偏好继承。商品询问或比较不等于购买。同一未结束 Run 的补充输入保留尚未撤销的当前意图，并逐步补齐数量、地址；这与不同 Run 不继承意图区分。明确“不购买”会撤销当前购买意图并清除其数量、地址。澄清消息不拼接旧预算文本；澄清入口没有浏览器候选名单绑定，涉及编号时必须先明确实体，不能猜测。

模型超时不撤销已提交的用户偏好，检索成功不代表 Run 完成，提案存在不代表订单已提交。“只重试推荐”使用当前 Thread 偏好，不把旧 Run 的预算、数量或地址偷偷带回。响应未知时先 GET 同一个 Thread/Run/Proposal，必要时只用原 request_id 恢复或重试，不创建新付费操作。

## 版本与 Live 边界

T16 改变源码指纹。旧 Frozen Manifest、Pilot、B1 账本及授权没有改写或重封存。T15-B1 的7次调用与单场景证据仅对应历史提交617cdf29；T16 真实模型调用为0。后续真实多轮 Smoke 必须重新绑定源码、环境、价格、政策和持久预算，由用户独立批准，购买仍需单独确认。
