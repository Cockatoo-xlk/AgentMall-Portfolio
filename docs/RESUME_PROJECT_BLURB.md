# AgentMall｜简历与面试介绍草稿

面向AI Agent、Python后端和应用AI实习。以下是**项目事实型文案**，不自动证明本人独立完成全部代码。按本人实际参与的设计、实现、调试和AI辅助范围取舍，只保留能现场解释、定位源码并复现的内容；不虚构公司经历、线上用户或生产交易量。

## 中文简历项目描述

**AgentMall｜可恢复Agent工作流与事务电商｜个人工程作品集（AI辅助开发）**

- FastAPI + LangGraph + PostgreSQL/pgvector + React，实现Single/Multi-Agent购物、2–5品类Bundle及多轮约束重规划，使用版本化Context与候选集合绑定商品引用。
- 将模型工具调用与交易执行分离：不可变提案、独立HITL Confirmation、行锁和数据库事务共同保障多SKU原子库存预留；幂等回执处理重放和响应丢失。
- 提供PostgreSQL持久任务与独立Worker，通过Thread advisory lock、Epoch Fence、Journal及官方Checkpoint恢复受控失败；SSE展示已提交事件，不因重连重复购买。
- 集成受角色限制的本地MCP工具、商家工作台和只读运营助手；评测页面区分Fixture、真实检索与历史模型证据。最终产品main离线CI：pytest1291/14skip、Vitest127、Playwright119/0retry。

证据绑定main `59f84ebbfdfb1d87287ad6c4ae83a1748183d30c`、[Run42770031624 / Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42770031624)，不是个人绩效或生产规模指标。当前真实L7复杂B2仍PARTIAL；不把离线成功称为真实LLM生产可靠性。

## English résumé description

**AgentMall — Recoverable Agent Workflows and Transactional Commerce**
Personal engineering portfolio developed with AI assistance. Keep only responsibilities personally performed and explainable.

- FastAPI, LangGraph, PostgreSQL/pgvector and React application with Single/Multi-Agent shopping, multi-SKU bundles and versioned multi-turn replanning.
- Explicit boundary between model tool calls and business execution: immutable proposals, independent human confirmation, atomic inventory reservations and durable idempotency receipts.
- PostgreSQL-backed asynchronous jobs and an independent worker using thread advisory locks, epoch fencing, journals and persistent checkpoints; resumable SSE progress from committed events.
- Role-scoped local MCP tools, merchant workflows and read-only operations analysis. Product-main offline CI verified 1,291 pytest passes / 14 skips, 127 Vitest passes and 119 Playwright passes with zero retries.

Results belong to main commit `59f84ebb…` and the linked CI, not production usage or current real-model accuracy. Complex real-LLM B2 remains PARTIAL. No real payments, production deployment or general exactly-once guarantee is claimed.

## 30秒介绍

“AgentMall是一个AI Agent电商作品集。模型负责推荐和提案，下单必须独立确认，由PostgreSQL事务校验库存与权限。它支持组合购物、Worker恢复、SSE和本地MCP。main离线CI已通过，真实复杂B2仍失败；模型能力和交易安全分开验证，个人贡献也会明确说明AI辅助范围。”

## 2分钟技术介绍

“AgentMall的核心问题是：模型能给购物建议，但不能直接控制交易。React展示商品和提案；FastAPI从认证身份建立Store范围；LangGraph运行Single或Supervisor加Specialists，服务端校验工具、任务依赖和商品引用。

用户可以先推荐办公组合，再只改耳机预算或键盘连接要求。Context绑定候选顺序、SKU和版本；购买时必须重新核价、验库存并独立确认。领域服务按固定顺序锁全部SKU，将订单、库存预留、确认消费和幂等回执同事务提交；任一商品失败都不能部分下单。

同步HTTP与持久异步模式共用执行器。Worker用Thread锁、Epoch Fence、Journal和官方Checkpoint恢复。Checkpoint保存执行位置，业务回执确认实际写入；重复Resume返回原结果，不新建订单。它不保证外部模型请求Exactly-Once。SSE只读已提交事件，MCP是受角色限制的外部接口，不替代业务授权。

检索结合PostgreSQL全文、BGE/pgvector和RRF；Reranker因CPU延迟代价默认关闭。最终main离线CI通过1291项pytest、127项Vitest和119项Playwright，保留14项skip。但真实L7 B2仍为PARTIAL，不能把Mock或旧开发集成绩包装成生产可靠性。我会结合源码讲工程取舍，并按真实参与说明个人工作和AI辅助范围。”

口播为可编辑提纲，时长随本人语速调整；不是已经完成的录音或录像。

## 现场证据入口

[一页介绍](PORTFOLIO_ONE_PAGE.md) · [架构与源码](ARCHITECTURE.md) · [技术深挖](PORTFOLIO_INTERVIEW.md) · [无Key Demo](PORTFOLIO_DEMO.md) · [main回执](evidence/v214-r4/report.md)

默认演示为MockTransport / Fixture / TEST_OPERATOR，付款0；历史截图不是真实DeepSeek录像，**VIDEO_NOT_RECORDED**。本稿不是已发布Tag或GitHub Release，也不是对本人贡献的第三方证明。
