# V2.16 产品演示与 Multi-Agent 可靠性交付

本地分支 `codex/v216-product-demo-reliability`，准确父基线 `d18161d1eb40667f4658e745d2f58369767d67f5` / tree `548b2f8e3180027bb179c2b42a1c4367984ff489`。V2.15已合并，基线 main CI43718887411 success；本轮未Push、未创建PR、未运行远程CI。V2.14 Release ON_HOLD；RELEASE_COMMIT=UNBOUND。

## 实际改进

- 正式页面展示本次约束、候选数量、商品价格/库存/属性对比、可见的工作流答复。只接受服务端商品引用与事实，不补造缺少数据；对比快照和独立GET的当前资源分别标注。
- Proposal展示数量、金额、地址、政策、快照、独立Confirmation消费及业务回执。保留原手动审批、重放核对与过期保护，不自动批准或恢复。
- Multi批次内等价只读Handoff整批拒绝，在原子delegation预算预留前停止；不同订单引用仍合法并行。正式产品后端行为Diff只涉及runtime.py的4行，未改Prompt、权限、状态机、库存事务或Fence。
- [受控离线入口](../evals/CONTROLLED_OFFLINE.md)复用固定pytest/正式API/SDK MockTransport；没有旧Simulator的自动审批或Recover循环。冻结后状态/错误契约评分不是原业务Oracle；UNKNOWN Usage不写0或SETTLED。

## 浏览器与数据库证据

[9条场景](../frontend/tests/product-demo.spec.ts)均通过浏览器调用正式API；测试控制端仅负责新Schema合成初始化、故障注入和独立SQL事实读取，不向页面伪造交易结果。每个测试重置的是本轮专属环境。

| 场景 | 成功 | 拒绝 | 安全失败 |
|---|---|---|---|
| A 推荐 | 3款无线静音候选与真实价格/库存事实一致 | 用户明确不购买，Proposal/订单/付款均0 | 缺Usage后PARTIAL、1次模拟请求，保留UNKNOWN |
| B 购买 | 明确批准后1张PENDING_PAYMENT、库存预留1；重复恢复和刷新不增写 | 独立reject，无订单/预留 | Proposal后商品下架，拒绝过时交易 |
| C Multi退换购 | Case+1，再经第二份独立确认订单+1；两确认均消费 | 拒绝退货后，购买仍需新的独立决定；再次拒绝则不新增订单 | 后续非法wire响应停止，保留Case/退货确认，不新增订单/退款 |

C初始化包含模拟付款并发货的合成DELIVERED原订单；上述业务增量以初始化后为基线，未进行真实资金交易。购买确认不可跨两份Proposal复用（409）；跨Actor读取Proposal为404。完整套件继续验证跨Store隔离、Checkpoint/Fence、事务幂等、权限和恢复。

本轮截图为SDK MockTransport / Fixture Embedding，不是真实DeepSeek：

- [推荐事实对比](screenshots/v216/recommendation.png)
- [购买与刷新读回](screenshots/v216/purchase.png)
- [双审批后的Case与待支付订单](screenshots/v216/return-replacement.png)

截图及代码文件哈希见[验收JSON](evidence/v216/verification.json)。**VIDEO_NOT_RECORDED**。截图的SDK会话账本上限沿用旧Mock演示策略；每Run正式模型12/工具16/派发4/步24/输出12000/90秒限制未增加，截图不是付费实验预算授权。

## 本轮实际验证

[可审计统计、命令、退出码、耗时、日志SHA及源码文件哈希](evidence/v216/verification.json)。测试在本轮新建PostgreSQL17/pgvector环境、非root Runner、只读rootfs、无Docker Socket、无外部路由下运行；所有凭据为本轮合成配置。

- 完整轻量后端：1603 passed / 14 skipped / 3 warnings。13项real_bge按轻量策略跳过，本轮另行真实执行；1项私有历史原件不可用仍skip。3项warning来自已存在jieba正则转义。
- 真实BGE专项：13 passed / 0 skipped，52 deselected。固定Revision `7999e1d3359715c523056ef9478215996d62a620`，六文件SHA一致，CPU512维和SQL检索合同；没有下载替代模型，Provider仍为Mock。
- 受控离线入口：11 passed；批次派发专项及既有路由：57 passed。专项数字已包含在完整后端，不累计成额外总数。
- Vitest：23文件 / 146 passed；完整Playwright：128 passed / 0 retries / 0 skipped。首轮完整Playwright保留1项定位器歧义失败：新增答复使同一句拒绝出现两处，现分别核验持久提案通知和工作流答复，未放宽拒绝或SQL条件。另将拒绝场景改为等待实际持久化中断：拒绝退货不会授权购买，但独立购买意图仍会生成新的PENDING提案，须再次明确拒绝；拒绝回执保留，consumed_at为空，不冒称已消费交易。
- Ruff/format、TypeScript、ESLint、production build、diff、Markdown链接/JSON与新增内容隐私审查均需通过后才形成提交。

独立代码审查未发现阻塞项，指出一项低风险测试数据形状与真实business_receipt不一致，已改为实际EXECUTED/无action_type，订单付款状态仍只从独立GET读取。中间RED、工程错误与最终GREEN日志分别保留，不借用历史成绩。Playwright日志中的Fixture checkout precommit rollback堆栈来自显式注入的事务回滚负例，最终用例与SQL回滚断言通过；不是被忽略的未处理业务失败。

## 复现与5–7分钟演示

[运行和清理指南](DEMO_GUIDE.md)使用既有Compose/scripts/demo.py，不新建评测平台；[受控API验证](../evals/CONTROLLED_OFFLINE.md)可直接运行。浏览器测试：`cd frontend && npm run test:e2e -- tests/product-demo.spec.ts`，前提是新专属测试PG及锁定依赖已准备；普通服务不提供`/__test`控制端。首次构建可能下载基础依赖，不能承诺冷机器完全离线启动。

讲解按架构40秒、A推荐50秒、B审批/幂等90秒、C双审批150秒、失败与历史证据60秒组织。使用实际API返回ID，不复制历史截图ID，不展示Token/DSN或原始Checkpoint。

## 仍然保留的限制与下一阶段

L8原15题：PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7；只有5题完成评分，1/5=20%，不是15题完成率。08 Ledger与实际费用UNKNOWN，RCA=INSUFFICIENT_EVIDENCE，CNY2.113536为预留而非实费；E1_ORACLE_CONTRACT_MISMATCH未解除，独立Holdout0。没有重跑、重评分或读取09—15调试。

本轮真实Provider请求0、真实Key读取0，真实LLM改善NOT_RUN，没有生产部署/真实支付/退款/SLA；MCP REMOTE_AUTH_NOT_IMPLEMENTED。真实BGE专项与Fixture页面是分开的证据，不能合成宣称真实模型端到端通过。

下一步先由Owner单独授权准确Commit的一次普通Push，读取自动CI；成功后再授权PR。没有自动Push/PR/Merge/Tag/Release/部署。若准备真实模型评测，应冻结V2.16源码及新协议、模型/实际价格、任务/Oracle、逐题预算与独立HITL及UNKNOWN全局停止；结果另建版本，不覆盖L8分母或原成绩。不在本任务执行。


本轮证据导出、内容与SHA校验后，已按精确Owner身份停止并删除3个新容器、5个新Volume，逐项核验不存在；原本地合成配置已恢复，临时合成凭据文件已移除。历史容器元数据和Volume名单在本轮观测窗口内一致；没有授权或实施历史资源清理。
