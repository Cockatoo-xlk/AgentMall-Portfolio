# V2.6 Bundle Shopping：本地交付报告

基线：`c8e9683502e8672d7c23ff9f9b17b79d019c0220`。分支`codex/v2-bundle-shopping`。最终本地提交可由此报告所在Git提交确定；[验证JSON](verification.json)另绑定实际源码文件指纹，避免自引用Commit SHA。

## 已实现

- 2–5个唯一品类的严格结构化需求；各项规格、数量与整套整数分预算分离。
- Shopping按品类使用原Hybrid RAG；每类最多5条已校验事实，至多3125个组合。稳定排序为显式静音优先、整套价格、Product UUID；不是全目录最优性证明。
- 复用CandidateSet，经增量迁移0009保存组合及Thread/Run/买家/Store/版本/有效期绑定。旧名单和12件Legacy SKU保持兼容。
- Order只接受当前选中bundle_id；数量/地址来自当前用户输入或完整结构化选择。整套最新商品重读、提案快照比较、一份CHECKOUT、一份独立Confirmation和一笔多SKU订单。
- 原库存、订单、付款、售后、退款领域服务未修改。原有排序锁、全部校验后预留、事务回滚及幂等回执继续使用。
- React显示全部SKU、品类、规格、单价、小计、库存快照、全局预算、余量、来源/版本与有效性。SSE显示真实品类工具事件及组合计算。刷新重登、历史GET和原Confirmation组件继续使用。

## A–J结果

| 场景 | 实际结果与验证 |
|---|---|
| A 推荐不购买 | Expanded120中四类独立检索，完整可行组合；提案0、订单0。Single/Multi均测试。 |
| B 明确购买整套 | 四SKU一份CHECKOUT，确认前订单0；TEST_OPERATOR确认后唯一PENDING_PAYMENT订单，小计与总价匹配。另测五品类、每样2件。 |
| C 预算不足 | 预算1元时返回NO_FEASIBLE_BUNDLE；保留四个品类，无提案/订单。 |
| D 任一SKU缺货 | 推荐后/提案后缺货均拒绝；其他SKU不预留。双确认并发竞争仅一笔订单，另一笔PARTIAL，无部分库存写入。 |
| E 价格或版本变化 | 推荐后涨价、版本变化、下架及过期拒绝；提案后变化由原事务拒绝，订单0。 |
| F 选择歧义 | 两个当前方案、“买那个”、外Thread/旧方案引用被拒绝，不能猜测。 |
| G 重复/响应未知 | 相同Run请求与Resume重放复用原回执，订单增量1；现有响应丢失浏览器用例参与完整回归。 |
| H 越权/恶意参数 | 他人Thread404、错误Store绑定拒绝；工具Schema拒绝SKU列表/越权字段，真实Mock工具尝试另一bundle_id也无法创建提案或预留。 |
| I 旧版兼容 | 单SKU、退货、商家、付款/退款、SSE和Evaluation Studio参与完整回归；旧Single工具集合的Fixture断言修正后定向通过。Legacy评测注册表保持原协议，历史Manifest未修改。 |
| J 多品类真实检索 | 独占PostgreSQL17/pgvector，Expanded120，真实词法/向量SQL与事实复核；Embedding为Fixture，不冒充新真实BGE验收。 |

## 数据库与Checkpoint

公开脱敏原件：[Multi业务摘要](bundle-multi.json)、[Single业务摘要](bundle-single.json)。均为合成账户/商品，无真实用户数据。

四SKU组合实际总价142600分。每个架构各自独立环境中：唯一订单、4个OrderItem、付款0、消耗Confirmation1；全部120件库存逐项比较，目标SKU reserved各+1、on_hand不变，其余不变。独立REPEATABLE READ READ ONLY事务查询唯一execute_checkout完成回执及RunEvent连续性；官方Checkpointer重新打开，最终next=done、pending_writes=0。不能把这两个摘要中的不同订单累加为同一环境两单。

库存故障、涨价及模拟事务提交前异常均验证订单0、预留0、Confirmation未消费。没有修改交易规则，也没有模拟付款。node_journal/resume_journal直接原始字段快照未新增专项独立验收。

## 测试与失败保留

- 新增后端41项、Vitest4项、Playwright2项；当前后端960 collected，其中原14项skip（13项本地真实BGE依赖、1项私有Live原件比较）未扩大。
- 一次完整后端结果：917 passed /25 failed /14 skipped。5项为Schema阴性测试合成参数未补category/bundle_id；20项为组合工具污染旧全局注册表，触发FROZEN_EXECUTION_CONFIG_CHANGED。拆分Legacy SCHEMAS与按Thread使用的BUNDLE_SCHEMAS/ALL_SCHEMAS后，最后相关测试129 passed /10 skipped，覆盖全部失败及新增41项。历史数据/Manifest/授权Guard未放宽。
- Vitest完整99 passed。Playwright完整107 passed /1 failed，0 retries；旧Single Fixture用全局Schema推断可用工具，错误得到PARTIAL。改为精确核对原角色白名单后，最终组合/移动端/旧Single定向3/3通过，0 retries。
- Ruff、format、typecheck、ESLint、build及diff检查通过。未再次执行整套pytest/Playwright；这是完整回归后有界定向修复验证，不是一次全量绿色CI。
- 更早的在途后端回归曾因最终审查发现问题而主动中断，原日志保留，未计作通过。开发中保留解析/状态接入失败、金额千分位测试断言错误、静态检查失败、错误测试文件名（退出4、0项执行）等原始回执。
- 审查修复了预算/规格冲突被覆盖、数量继承、零预算未验证、文本/结构化地址冲突、澄清后旧组合残留。通过原RuntimeState delta传递可信map删除，不改变Checkpoint序列化版本或执行预算。

全部命令退出码、UTC、耗时及日志SHA保存在[回执索引](verification.json)，原始日志仅在本轮Git忽略私有目录，不覆盖旧失败。开发环境为Mac上Docker Desktop Linux aarch64/Chromium，非Ubuntu amd64新远程验收。

## 安全与限制

无真实Provider请求/Key读取、无Push/Dispatch/Rerun/PR/main变更、无真实支付。测试网络仅本轮容器网络命名空间内loopback；没有使用或删除历史Demo数据库。新增截图为MockTransport + Fixture Embedding、TEST_OPERATOR，已检查可读性与敏感信息。

MVP仅支持一店、一套、每类一个SKU；复杂未知规格和矛盾需求澄清。未指定数量仅估算推荐，购买当轮需再次明确；不同SKU的不同数量可经完整bundle_quantities结构化输入，当前页面主要演示“每样N件”。真实DeepSeek能力、新真实BGE专项、远程CI、性能指标、录屏均NOT_RUN。未来Live必须新源码指纹、独立环境/Session/Policy与用户预算授权。
