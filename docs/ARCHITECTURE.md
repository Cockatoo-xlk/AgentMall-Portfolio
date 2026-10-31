# 实际架构与数据职责

本页为公开候选新编技术说明，不是原研发架构文件或历史原件。

```mermaid
flowchart LR
  UI[React 商城与工作区] --> API[FastAPI 认证和对象授权]
  API --> Graph[LangGraph 持久图]
  API --> Domain[确定性领域事务]
  Graph --> Agents[Single 或 Supervisor 与三个 Specialist]
  Agents --> Tools[工具白名单与严格参数]
  Tools --> RAG[公开范围 Hybrid RAG]
  Tools --> Domain
  Graph --> HITL[提案与独立确认 Resume]
  HITL --> Domain
  Domain --> PG[(PostgreSQL 业务与幂等回执)]
  RAG --> PG
  Graph --> CP[(官方 PostgreSQL Checkpoint)]
  Graph --> Journal[节点 Journal 与 RunEvent]
```

- [订单事务](../backend/src/agentmall/orders/service.py)：锁后重验价格/版本/库存/数据库时间，价格整数分。待支付订单预留库存，退款不自动回补。
- [确认](../backend/src/agentmall/actions/service.py)与[Resume](../backend/src/agentmall/agents/resume.py)：登录主体、店铺、提案、interrupt和confirmation绑定；第一份确认不能批准第二份提案。
- [持久化](../backend/src/agentmall/agents/persistence.py)与[Run服务](../backend/src/agentmall/agents/run_service.py)：同Thread锁、Epoch Fence、节点Journal和业务回执协调。Checkpoint与业务事务分别提交。
- [工具边界](../backend/src/agentmall/agents/specialist_tools.py)：模型不能注入Actor/Store、确认、退款金额或直接SQL；混合写入批次整体拒绝。
- [检索](../backend/src/agentmall/retrieval/search.py)：词法/向量召回以RRF合并；公开范围、店铺、政策版本和实体当前状态由服务器验证，引用不覆盖领域资格。
- [Trace](../backend/src/agentmall/infra/observability.py)：RunEvent的白名单投影，无原始对话或思维链，导出器失败不回滚已完成合法业务。

Python依赖以[uv.lock](../backend/uv.lock)、前端以[package-lock](../frontend/package-lock.json)为准。迁移在[backend/migrations](../backend/migrations)，API以实际[路由源码](../backend/src/agentmall/main.py)与运行时OpenAPI为准。
