# V2.11 · 商家AI运营助手本地交付

**AGENTMALL_V211_MERCHANT_COPILOT_READY**。本轮是SDK MockTransport + 真实独占PostgreSQL的工具/权限/业务事实验收，不是真实LLM能力评测。没有Provider/Key、Push、Dispatch、远程CI或部署。

基线`9424b7d6d0b0ccebb52f219282a93e03038c6120`，分支`codex/v2-merchant-ai-copilot`。完整回归实际源码内容树SHA256：`d797ebca350c3299d0496e835a75a0b6691b088c3a15bef479830d28a794878a`；运行时为修改工作树，最终包含本报告的提交保存对应代码，不将基线冒充新代码Commit。[逐文件、命令及日志SHA](verification.json)。

## 已交付能力

独立请求级LangGraph：计划 → 原领域只读工具 → 程序统计 → 模型选择已验证证据 → 引用/状态校验 → 建议与审核草稿。8个工具名、最多6个读取选择+确定性汇总、2轮模型、15秒；分页和Token/输出均有界。商家身份、Store和对象权限只取服务端认证；原买家Agent权限未改，没有新表、Worker或消息队列。

React工作台提供自然语言问题、真实已完成工具进度、已读范围统计、待办、证据/政策、版本重读与草稿。草稿只能填原表单，不能发货/审批/退款。原独立业务操作和expected_version继续生效。JWT只在内存头；原GET SSE保持兼容。

详细[架构、8工具映射、政策解释和3—5分钟演示](../../MERCHANT_COPILOT.md)。MCP默认直接映射复用原服务，可选官方Client Adapter对商品/Case执行真实localhost协议调用并比较权威数据；原Gateway9工具和认证字节不变。

## A—N实际验证

| 场景 | 实际结果/测试依据 |
|---|---|
| A 待发货 | 原购买及模拟付款生成PAID，另有PENDING_PAYMENT时只计PAID；get_order快照SKU/金额一致 |
| B 待审核 | 原独立退货Confirmation生成REQUESTED Case，统计1并引用实际ID/版本 |
| C 库存 | 真实on_hand/reserved差值计算0和1—5，SQL快照不变；商品描述不当作指令 |
| D 索引失败 | 原V2.7审核发布后缺Encoder的真实任务FAILED，被只读工具识别；没有运行/重试任务 |
| E 审核依据 | 所属Case、原订单policy_version和有效公开政策一致；历史eligibility与当前新申请资格分开；没有选Case则SELECT_CASE |
| F buyer | 未登录401，buyer403；网页也无商家分析数据 |
| G Store隔离 | 其他Store摘要为空，指定他店Case404；用户传入角色/Store或模型省略对象检查均不能绕过服务器授权 |
| H 注入 | 恶意商品描述、越权工具名/身份参数被忽略为数据或Schema拒绝，业务快照未变 |
| I 虚构ID/声明 | 未知ID、动作/证据不匹配、额外自由数字声明均拒绝，不能输出成功建议 |
| J 失败/中断 | 模型异常脱敏503、5秒调用超时504不重试、真实HTTP取消释放连接；实际PG READ ONLY拒绝注入的错误UPDATE |
| K 使用草稿 | 浏览器只填原审核说明，Case仍REQUESTED及原version；没有新的审核/退款请求；旧指纹变化阻止填入 |
| L MCP | 官方Client经过localhost编码/传输/解码读取非空商品和Case，等于相同Actor原领域结果；伪造客户端数据拒绝 |
| M 分页 | Expanded120，默认2页只读40；1页20仍有cursor时明确部分范围，不写成全店统计 |
| N 累计兼容 | 完整pytest/Vitest/Playwright覆盖原Multi-Agent、单SKU、Bundle重规划、商品运营、MCP、SSE、商家交易和Retrieval Quality |

27个新后端参数化测试位于[源码](../../../backend/tests/test_merchant_copilot.py)，另有8个新增Vitest与3个真实浏览器场景。

## 有数据依据的Fixture样例

[脱敏场景JSON](scenarios.json)取自本次完整pytest窗口内的唯一导出原件，SHA和sidecar已匹配；不是挑选历史高分结果。模型只选择工具和证据ID，真实工具返回本轮PG记录。

| 场景 | 实际工具（含汇总） | 模型调用 | 工具调用 | 总耗时ms | 无证据声明 / 业务写入 |
|---|---|---:|---:|---:|---:|
| OPS-A-B | list_merchant_after_sales、list_merchant_orders、summarize_operations | 2 | 3 | 30.68 | 0 / 0 |
| OPS-C-D | list_catalog_index_jobs、list_merchant_products、summarize_operations | 2 | 3 | 35.32 | 0 / 0 |
| OPS-E-K | get_applicable_policy、get_merchant_after_sales、summarize_operations | 2 | 3 | 33.08 | 0 / 0 |

3个受控样例的工具集合3/3符合明确预期；已展示建议引用全部通过ID/状态及指纹校验，权限违规0。这里只能证明Fixture合同，不推导真实模型准确率。Latency为Mock SDK、数据库及程序耗时，不是实际LLM推理速度。浏览器Mock额外延迟0.5秒用于证明真实工具回执先于完成展示，不作为性能成绩。

## 独立数据库对照

分析前后：订单 **2→2**、模拟付款 **2→2**、退款 **0→0**、Case **1→1**、提案 **5→5**、Confirmation **5→5**。付款总数不是0；Copilot的新增业务写入为0。已有PAID/DELIVERED和REQUESTED数据由TEST_OPERATOR经原独立确认及生命周期准备，不是Copilot执行。

原独立读取的orders/order_items/products/payments/refunds/aftersales_cases/business_events快照前后均为`fdc0da248d032cdcd1b853643b4608732b1a8a277230c87f10c684eb81511738`。只读事务、错误写入拒绝、取消和超时另有真实数据库断言。

## 完整累计回归

- **pytest1083 passed /14 skipped**；新27项。原13项BGE权重依赖与1项私有Live原件比较skip不变，没有新增skip或修改旧Oracle。
- **完整Vitest126 passed**；新8项。
- **完整Playwright118 passed /0 retries/0 skipped**；新3项。
- Ruff、format --check、TypeScript、ESLint和生产build全部退出0。只进行一次完整累计回归；此前均为定向开发检查。
- 环境：本地Docker Desktop Linux aarch64，独占PG17/pgvector，Guest4CPU/5GiB、PG2CPU/1GiB。峰值内存未连续测量；不声称生产资源/吞吐/SLA或Ubuntu amd64远程验收。

## 保留失败、审查与限制

原始RED/中间失败私有保存：缺端点404；空计划误报完成、未选Case未澄清、模型省略对象读取未授权；模型异常及新前端缺模块/POST流测试失败；首轮浏览器整页跳转丢失内存JWT（测试导航错误）、结果div缺region语义、textarea定位方式错误；初次静态格式尚未整理。没有提高超时/重试或放宽断言。原受控渲染故障注入在完整浏览器日志中仍有异常文本，其对应测试通过，不隐藏。

一次独立新上下文审查发现P2旧/check响应覆盖新分析：确定性延迟真实核对回执复现RED，改为共享请求锁和禁用控件后GREEN；另修正输入Token上界漏计系统/工具Schema的问题，按完整SDK序列化正文计数。两项均有RED/GREEN及后续整套回归。

实现选择及代价：请求级无持久分析避免买家权限扩张及重复持久框架，代价是刷新无分析历史；受控引用/模板而非任意模型事实，代价是语言灵活度有限；MCP仅两个可选只读Adapter，未强制全部迁移，也没有远程OAuth。没有真实LLM验证、生产负载、后台Worker、900秒监控或新BGE质量实验。后续真实模型接入仍需独立安全/预算授权。

## 安全及清理

受保护原领域事务、Agent核心、MCP认证、模型Manifest与历史评测字节未改，源代码对照按基线逐文件核验。公开只含合成场景、白名单事实和经审阅截图，无买家原始留言、JWT、DSN、Key、Prompt、内部Checkpoint或私有日志。

清理前独立READ ONLY查询剩余test_/cp_ Schema为0；本轮Guest、PG、Volume、临时缓存/凭据及新runner tag均删除后查无。原25个历史容器ID/状态未变，默认context仍colima；没有停止或删除旧资源，没有BuildKit prune。原始日志/失败及SHA私有保留。
