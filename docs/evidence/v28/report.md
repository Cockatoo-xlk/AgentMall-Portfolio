# V2.8 MCP Gateway：本地定向验收

**AGENTMALL_V28_MCP_GATEWAY_READY**。基于V2.7 `5f197611d6e4cb93a0a39c3882456f196c84551e`，本地分支`codex/v2-mcp-tool-gateway`。修改源码的身份由包含本报告的Git提交、[验证JSON](verification.json)中的源文件内容树和命令/日志SHA绑定；基线SHA不冒充修改后的源码。

## 实现与实测范围

官方`mcp==2.3.0`、`mcp-types==2.3.0`，九个工具复用原领域服务。Public/Buyer/Merchant发现列表分别3/6/6个，调用时仍重新认证数据库Actor。HTTP仅127.0.0.1、本地自定义Bearer，严格peer/Host/Origin和版本门禁；**REMOTE_AUTH_NOT_IMPLEMENTED**，不是远程OAuth。

现代协议实测2026-07-28的`server/discover`和逐请求元数据，无`initialize`或协议会话；stdio另实测2025-11-25兼容路径。HTTP旧版故意返回426，不把SDK未验证的兼容范围当成本服务承诺。[官方规范](https://modelcontextprotocol.io/specification/2026-07-28)及[官方SDK](https://py.sdk.modelcontextprotocol.io/)。

| 本轮实际验证 | 结果 |
|---|---|
| 后端定向回归 | 181 passed，含35项新增MCP参数化用例；不是完整pytest |
| 完整Vitest | 102 passed |
| 选定Playwright | 11 passed / 0 retries；不是完整浏览器套件 |
| Ruff、格式、TypeScript、ESLint、build | 全部退出0 |
| 独立官方Client | 6个进程，stdio/HTTP × Public/Buyer/Merchant，共54次Tool Call |

环境是Mac Docker Desktop内的新独占Linux aarch64容器，PostgreSQL17.11/pgvector0.8.7、官方Checkpointer和原有隔离Schema Fixture。现有Agent回归使用MockTransport/Fixture，不调用真实模型。没有修改skip、retry、历史Oracle、Agent编排、订单/支付/退款/库存事务、Migration或工作流。

## 数据库与协议证据

[客户端脱敏投影](clients.json)保留六份原始stdout/stderr的SHA及工具调用摘要。客户端确实经过独立进程、编码、stdio/HTTP传输、SDK解码和领域读取；不是直接调用Python处理函数代替协议验收。[回执图](../../screenshots/v28/mcp-client-receipts.png)由这些实际JSON生成，为只读展示，**不是Inspector UI截图**。

测试操作者先通过原独立Confirmation路径建立一笔合成待支付订单，再开始MCP调用；MCP没有下单能力。独立数据库连接比较调用前后：

| 业务记录 | MCP调用前 | 调用后 |
|---|---:|---:|
| 商品 | 120 | 120 |
| 订单 / OrderItem | 1 / 1 | 1 / 1 |
| 购买提案 / Confirmation | 1 / 1 | 1 / 1 |
| 付款 | 0 | 0 |
| 库存预留数量合计 | 1 | 1 |
| 商品草稿 | 0 | 1 |
| 索引任务 | 0 | 0 |

唯一新增草稿状态DRAFT，approved_by及published_product_id为NULL。同request_id在stdio与HTTP重放仍返回同一草稿，无审批、发布或索引副作用。客户端断开后普通商品API仍返回200。原件与各文件SHA仅私密保存，不公开令牌、内部DSN、原始事件或Checkpoint。

## 安全及兼容性断言

35项MCP用例覆盖真实协议发现/调用、严格输入/输出Schema、非法参数、角色过滤及猜名拒绝、买家本人订单、其他买家不可读、商家本店商品/Case、Store重新分配、数据库账号撤销、伪造签名Token中的role/Store与元数据不能替代真实身份、未发布草稿不公开、Prompt Injection不能取得写权限、当前公开政策和来源、原API字段一致性、只读事务、结果上限、超时释放、真实取消与未知写入幂等恢复。

独立代码审核指出两项实际缺口，均先RED再修复：SDK默认stdio整行读取在参数校验前分配无界内存；原DTO输出包含不必要的身份/审核关联。现在SDK解码前限制整帧64KiB及未完成帧5秒，订单/Case按原DTO类型投影最小字段。保留字段逐项对照原API，不删除失败断言。

只读工具数据库事务为READ ONLY，参数最多32KiB，结构化结果最多64KiB，工具执行含排队最多5秒、并发最多4个。写入超时/未知错误保留UNKNOWN，不能自动换request_id重发。不存在批准、付款、退款、发布、库存修改或任意SQL工具。固定允许的工具名称和经过验证的Actor决定权限，目录文字不会变成执行指令。

## 保留的失败与修正

- 最初缺少Gateway模块的TDD运行14失败，随后协议实现通过；追加边界运行曾因测试辅助函数名称错误失败，修正为原有合法Case创建流程。
- 真实客户端取消RED证明SDK JSON-only HTTP分支不能及时传播取消，改用SDK请求级流式响应后通过；未改业务执行。
- 混用旧HTTP路由头和现代正文的边界RED揭示SDK兼容路径行为；本HTTP服务现在只接受现代协议，拒绝降级。
- 两项审核RED及中间的旧完整DTO比较失败均保留，最终改为比较每个允许输出字段，最后181项定向回归通过。
- 浏览器首轮10通过/1失败：旧商品运营测试假设随机UUID的新品必在第一页。通过既有搜索框定位实际新品后，相同11项用例全部通过；未修改产品行为或增加重试。
- 宿主数据库引导因55433冻结Checkpoint端口合同失败，保留原件；测试改在本轮Guest网络命名空间使用原55433，不改保护校验，不占用宿主已有监听。
- 清理前第一次只读psql检查漏传55433而退出2，没有发生删除；后续显式指定本轮数据库端口核验成功，再执行清理。私有报告生成器的字段名错误未产生通过回执，修正后重新校验实际JSON及SHA。

## 清理与公开内容

清理前独立READ ONLY事务确认残留test_/cp_ Schema为0。仅删除本轮归属的Guest、PostgreSQL容器、Volume及新增镜像tag，随后逐项inspect查无；原25个历史容器ID与State均未变化，默认Context仍为colima，未清理共享BuildKit。临时合成凭据文件删除，原始证据继续留Git忽略私有目录，目录0700/文件0600。

132份既有Agent/交易/权限/商品运营/迁移/evals/工作流及V2.7公开证据文件逐字节对照基线未变。新增依赖只增加SDK所需包，没有升级既有锁定包版本。公开只包含源码、合成测试、经过审阅的摘要和回执图；私有原件未加入Git。第三方SDK许可及素材来源见[第三方声明](../../../THIRD_PARTY_NOTICES.md)。

## 尚未验证

真实Provider调用及Key读取为0。真实LLM能力、真实BGE效果、完整后端/完整浏览器回归、远程CI、Inspector UI、公开远程OAuth、部署、生产SLA及真实支付均为NOT_RUN或不在范围。历史Live Pilot不能作为本版本模型验收。MCP不会替代原LangGraph工具，也不授予任何用户购买/退款授权。

[连接与3—5分钟演示指南](../../MCP_GATEWAY.md)。
