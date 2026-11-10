# AgentMall v2.14.0 — Portfolio Release

**DRAFT / NO_TAG / NO_GITHUB_RELEASE**。`v2.14.0`是建议版本号，不是已创建的Tag。产品代码已通过PR #2合并main；本轮文档尚待新PR与合并后的main CI，**RELEASE_COMMIT=UNBOUND**。正式发布前替换为最终冻结Commit，不能直接把旧产品Merge Commit当成最终发布Tag目标。

文档链接使用仓库main的完整URL，避免复制到GitHub Release后相对路径失效；这些新增文档须先经PR进入main。正式发布时可将文档URL中的main固定为最终发布Tag/Commit，并更新DRAFT及UNBOUND状态。

## 项目定位

AgentMall是一个AI Agent电商工程作品集，组合FastAPI、LangGraph、PostgreSQL/pgvector和React。模型负责检索、规划及准备提案；确定性领域服务负责权限、状态机、事务、库存和幂等。没有真实支付渠道或生产部署。

## 核心能力

- **购物与多轮规划**：Single / Multi-Agent、Shopping / Order / AfterSales分工；13品类120个合成SKU，2–5品类Bundle、整数分预算、版本化候选及增量重规划。
- **人工确认与交易边界**：不可变Proposal、独立Confirmation、原Run Resume；多SKU库存预留、订单、确认消费和幂等回执同事务提交，任一SKU冲突不部分下单。
- **持久执行**：同步HTTP和显式Durable Async共存；PostgreSQL Job、Thread advisory lock、Epoch Fence、Journal与官方LangGraph Checkpointer支持受控故障恢复。SSE仅推送已提交的脱敏事件。
- **商家运营**：订单/售后工作台、CSV/JSON合成资料导入、来源可追溯的草稿、明确审核发布、索引状态与有界重试。Merchant Copilot保持只读，当前能力由MockTransport验证。
- **Hybrid RAG**：Jieba、PostgreSQL `ts_rank_cd`全文检索、固定本地BGE/pgvector和RRF；可选CPU Cross-Encoder默认关闭。过滤及当前商品事实校验不能被模型绕过。
- **MCP Gateway**：9个角色受限工具，stdio / localhost HTTP复用领域服务；唯一写扩展是待审核商品草稿，不提供批准购买、付款、退款、无审核发布或任意SQL。
- **Evaluation与CI**：静态Evaluation Studio区分Fixture、真实检索和历史Live来源；Backend / Frontend独立PG并行运行，Release Gate拒绝失败、取消和意外跳过的必需结果。

架构为React → FastAPI → LangGraph / Durable Worker → 领域服务与PostgreSQL；MCP是独立外部入口，不是所有Agent工具必经链路。[完整架构图与代码边界](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/ARCHITECTURE.md)。

## 已核验的产品基线

- 产品Merge Commit：[`59f84ebbfdfb1d87287ad6c4ae83a1748183d30c`](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/commit/59f84ebbfdfb1d87287ad6c4ae83a1748183d30c)。
- 审核候选：`900bf3dda50eec4d2d9583f46001991ac39fb707`，与Merge Commit代码树一致。
- [main Run42770031624 / Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42770031624)：push / main，Backend、Frontend、Release Gate均success。
- pytest **1291 passed /14 skipped**；Vitest **127 passed**；Playwright **119 passed /0 retries**；Ruff、format、TypeScript、ESLint、build成功。

这些结果来自已独立读取的main CI日志和三个摘要ZIP，**不是本轮重新运行的测试，也不自动覆盖未来文档合并后的新Commit**。[Post-merge核验与SHA](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/evidence/v214-r4/report.md)。首次单Job取消、R2改造及各次Push/PR CI仍保留在[结果索引](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/RESULTS.md)。

## 运行与演示

使用[README Quick Start](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/README.md#quick-start默认无key演示)和[Demo手册](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/PORTFOLIO_DEMO.md)。默认路线为SDK MockTransport / Fixture Embedding、合成buyer1、Single / Legacy Sync及TEST_OPERATOR独立确认；订单终态PENDING_PAYMENT，付款0。普通FastAPI默认MODEL_DISABLED，不需要Provider Key。

Docker路线固定Python3.12.10、Node24.21.0、uv0.9.18、PostgreSQL17/pgvector；仅loopback暴露演示服务。构建下载锁定依赖，权重不分发。冷机器完整构建/网络可用性未在R4重跑。旧截图是历史合成Demo，不是新的实时DeepSeek演示，**VIDEO_NOT_RECORDED**。

## 已知限制

- **真实复杂B2 Multi仍未通过**：L7同产品源码为PARTIAL / CONTEXT_SCOPE_VIOLATION，未完成第二次购买确认。
- V2.12历史五题开发集Single5/5、Multi4/5、总9/10绑定旧源码；L6的10–11调用成功路径为MockTransport。不能合并为当前版本或生产成功率。
- V2.10真实BGE/Reranker是本地Linux aarch64/CPU、固定40条合成查询和单标注者；并非真实LLM能力评测。普通CI保留13项权重依赖与1项私有原件比较的skip。
- 没有生产用户规模、QPS、SLA、灾备或通用Exactly-Once声明。Worker恢复不保证已发出的外部模型HTTP请求只发生一次。
- MCP **REMOTE_AUTH_NOT_IMPLEMENTED**；本地Bearer和合成账号不可当成公网认证。
- 本次没有生产部署或真实资金行为；不自动授权Live、部署、镜像/模型权重分发。

## License与发布步骤

项目原创源码、文档及合成素材采用[MIT](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/LICENSE)，Copyright (c) 2026 Cockatoo-xlk。[COPYRIGHT](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/COPYRIGHT.md)、[权利人决定](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/LICENSE_DECISION.md)与[第三方通知](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/THIRD_PARTY_NOTICES.md)继续适用；Lucide/Feather和依赖各自许可不被项目MIT替代。本次不分发模型权重、依赖二进制、浏览器或Docker镜像。

[正式发布清单](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/blob/main/docs/RELEASE_CHECKLIST.md#正式tag与release流程尚未授权执行)：所有者审核文档Commit → 新PR → 合并后新main CI → 冻结准确发布Commit → 另行批准注释或已核验签名Tag → GitHub Release → 校验目标与Notes。**当前只提供草稿，没有创建Tag或Release。**
