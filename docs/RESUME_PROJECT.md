# AgentMall · 简历与面试项目描述

## 可直接使用的简历段落

**AgentMall：可恢复的电商 Agent 工作流工程作品集**
Python / FastAPI / PostgreSQL / pgvector / LangGraph / React / TypeScript

- 将自然语言商品比较、购买与售后连接到正式业务API；模型仅产生工具建议和不可变提案，用户独立确认后由领域服务重验权限、价格、库存并提交交易。
- 基于LangGraph、PostgreSQL Checkpoint/Journal、Thread锁与epoch fence组织Single/Multi工作流；使用持久幂等回执处理响应丢失，验证库存预留、重复确认和恢复后的业务状态一致性。
- 建立SDK MockTransport、真实PostgreSQL、固定本地BGE的分层回归与证据归档；将真实模型实验中的业务失败、评测工具缺陷和证据不足分开报告，提供可复现产品演示和测试日志。

项目为**AI辅助开发**。以上是仓库可核验能力描述；投递者应只保留自己实际设计、修改、走读、复现和能够解释的部分，不能宣称整个项目独立手写。准确测试数量见[本轮交付](V217_INTERVIEW_READY.md)，不在此处维护容易过期的数字。

## 30秒口述

“我做的是一个把Agent建议接入真实电商事务的作品集。最关注的不是模型答得像成功，而是人审提案之后，数据库里是否只有一份订单、库存是否正确、断线后能否读回原结果。Single和Multi共享业务服务，Multi用Supervisor派发受限任务；Checkpoint记录执行位置，业务回执记录真实提交。我用真实PostgreSQL、离线SDK和固定BGE分开验证，也如实保留真实模型的失败与UNKNOWN。”

## 五分钟展开顺序

播放[3分30秒成片](media/v217/agentmall-v217-demo.mp4)，按[讲解稿](media/v217/agentmall-v217-demo-script.md)解释推荐事实、购买审批、双HITL和SQL投影，再打开[12问](INTERVIEW_TALKING_POINTS.md)的相应源码。面试官追问时优先展示源码和独立SQL/测试，不依靠页面成功文案。

## 不能写进简历的结论

没有线上用户数、生产吞吐/QPS、生产SLA、高并发压测或独立盲测可靠性证据。L8是自建前瞻性评测：计划15，8启动，只有5评分、1PASS/4FAIL，3NOT_SCORED/7NOT_RUN；08费用/用量UNKNOWN，E1契约问题保留，Independent Holdout=0。不能写“15题通过率”“真实DeepSeek可靠性提升XX%”或把离线演示说成在线实模。V2.17小规模Smoke仍未执行；Release ON_HOLD。
