# AgentMall · 简历与面试项目描述

## 可直接使用的简历段落

**AgentMall：可恢复的电商Agent工作流工程作品集**

Python / FastAPI / PostgreSQL / pgvector / LangGraph / React / TypeScript

- 将商品推荐、购买和售后意图接入正式业务API；模型负责受限工具建议，服务端持有Actor/Store身份、商品事实及事务权限，通过不可变Proposal、独立Confirmation与显式Resume提交交易。
- 使用LangGraph Checkpoint/Journal、Thread锁和epoch fence管理中断与恢复；持久化幂等回执，并以真实PostgreSQL回归核对重复Resume、确认消费、订单唯一性和库存预留。
- 结合Jieba/PG全文、本地BGE/pgvector与RRF检索可信候选；修复推荐展示与Thread候选绑定、单价/总预算及跨商品属性作用域问题，保留探索记录与澄清边界。
- 将真实模型失败转成可复现开发回归：保留原评分和UNKNOWN，分别定位商品证据投影、交易后独立目标被跳过及人工命令交付问题，使用SDK MockTransport、正式API与独立SQL验证修复。

项目为**AI辅助开发**。投递者应只保留自己实际设计、修改、走读、复现和能解释的贡献，不能宣称整个仓库独立手写。准确测试身份与数量见[最终源码验收](V217_INTERVIEW_READY.md#最终源码验收)，不把离线测试数量写成真实模型样本数。

## 可以讲述的真实模型案例

三个分别执行的成功案例有真实DeepSeek、固定BGE和正式SQL证据：B购买使用Source `115905a3cb45bfd2b70384fec7375be9243a6f92`；A推荐与C双HITL使用Source `8171e5576180e8827b78fff3d6c9f58051729f08`。C在连续81.333秒内完成Case+1、待付款订单+1、确认消费+2、库存预留+1，支付/退款增量0，11次HTTP用量SETTLED；供应商实际账单UNKNOWN。[完整结果与失败记录](EVALUATION_RESULTS.md)。

这些案例不是同一版本3/3或独立盲测3/3。最终产品修复提交 `759391cd6c33a1bbc906df34e6de87126cb53dac` 完成离线验收，没有新的真实模型成绩。

## 30秒口述

“这个项目把Agent建议接到真实电商事务。模型可以找商品、提出购买或售后方案，但不能替用户批准。我重点处理的是：人审之后数据库只出现一份订单、库存正确预留、断线后能读回原结果，交易完成也不能跳过后续查询。Checkpoint记录图的位置，业务回执记录真实提交。我验证过真实模型的独立功能案例，也保留了失败和账本UNKNOWN，用正式API、PostgreSQL和合成模型回归定位可确认的问题。”

## 五分钟展开

播放[3分30秒离线成片](media/v217/agentmall-v217-demo.mp4)，按[讲解稿](media/v217/agentmall-v217-demo-script.md)说明商品事实、Proposal、两次独立确认和SQL。明确视频是OFFLINE MOCK DEMO；真实DeepSeek案例另用汇总回执说明，不把字幕当Live画面。再沿[12问](INTERVIEW_TALKING_POINTS.md)展开一条实际调用链，展示自己能解释的源码、测试和证据边界。

## 不应写入的结论

- 没有生产部署、线上用户数、生产QPS/SLA或高并发性能证明；Release ON_HOLD。
- 首次Smoke仍A FAIL / B PASS / C NOT_SCORED。后续成功不覆盖早期失败，不汇总成同一版本3/3或可靠性提升百分比。
- 原四题仍H01 FAIL、H02 NOT_SCORED、H03 NOT_RUN、H04 STATIC_ADMISSION_REJECTED / Oracle NOT_RUN；独立盲测数量0，后续修复只是开发回归。
- L8计划15、启动8、评分5：PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7；08 Ledger/实际费用UNKNOWN、E1_ORACLE_CONTRACT_MISMATCH保留。不能把15题说成全部完成或把NOT_RUN算作已观察失败。
- Docker Socket历史8容器整改是本地安全处置，不是生产环境安全认证。费用保守上界不是供应商账单。
