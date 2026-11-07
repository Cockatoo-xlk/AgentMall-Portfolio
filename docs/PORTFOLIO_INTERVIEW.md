# 面试讲解：从自然语言到可恢复事务

本页解释仓库行为，不证明个人独立手写全部代码。面试时按事实说明自己负责的设计、修改、调试与AI辅助范围；不要把测试样例、Mock输出或历史实验说成生产经验。

## 为什么选择LangGraph？

流程会在提案处暂停、等待确认，再跨HTTP请求恢复；状态还可能经历页面刷新和进程故障。[StateGraph](../backend/src/agentmall/agents/durable_graph.py)把路由、专业任务、等待和确定性执行组织为显式节点，官方PostgreSQL Checkpointer保存图状态。[Run服务](../backend/src/agentmall/agents/run_service.py)同时处理持久身份、预算、Journal和Epoch Fence。Checkpoint不是事务替代品，业务仍由领域服务提交。

## 为什么需要Multi-Agent？

[Supervisor](../backend/src/agentmall/agents/supervisor.py)生成受校验任务；Shopping做商品检索，Order核对商品/订单并准备提案，AfterSales检查资格、引用公开政策并准备售后或人工工单。各角色的[工具白名单](../backend/src/agentmall/agents/specialist_tools.py)与严格Handoff契约减少不必要权限。分工有额外模型调用与延迟成本，项目保留Single模式，并不声称Multi普遍更优。

## 为什么不用纯LLM执行订单？

模型可能输出错误金额、商品、权限或重复工具调用。它只提出受校验的工具请求，不能生成Confirmation。[交易服务](../backend/src/agentmall/orders/service.py)从服务端不可变提案读取价格/数量，检查归属、独立批准、期限、库存和幂等。在Agent工作流中，由Resume内的确定性节点消费确认并提交事务，前端不再额外调用一次/orders；普通购物车则通过订单API调用同一领域服务。购买批准也不能授权付款或退款。

## Hybrid RAG如何实现？

[索引器](../backend/src/agentmall/retrieval/ingest.py)从真实目录生成文档、中文品类名、内容哈希和版本；[分词器](../backend/src/agentmall/retrieval/tokenize.py)产生词法token。检索组合PostgreSQL全文检索与pgvector向量召回，RRF融合排名。[SQL作用域](../backend/src/agentmall/retrieval/search.py)在LIMIT前校验店铺、价格、库存、状态及属性，重读当前事实后再次验证版本/内容哈希。真实BGE固定Revision、512维，相似度阈值0.45未为演示降低。本次浏览器Demo使用Fixture Embedding，只证明链路，真实向量质量不能由这次截图证明。

## 如何防止“第二款”错位？

[Thread Memory](../backend/src/agentmall/agents/memory.py)保存结构化偏好、context_version和经过校验的候选集合。集合有来源Run、rank、Product ID与Catalog Version；浏览器提交正在展示的candidate_set_id和版本，而不是让模型凭名字猜商品。条件变化使旧名单失效，服务端解析序号后仍重读最新商品事实。候选不是有效报价，价格/版本/库存变化不能直接沿用。

## 如何避免重复下单？

沿用稳定request_id、action身份和Idempotency-Key；重复请求返回原回执，冲突payload被拒绝。订单创建锁定提案、确认和商品行，库存预留、Confirmation消费、订单和幂等回执共同提交或回滚。响应未知先GET核对原资源，不用新随机Key盲目重做。购物车来源还校验服务端Cart版本，变化后保守保留；Agent独立下单不消费同SKU购物车。具体实现见[购买执行](../backend/src/agentmall/orders/service.py)和[购物车消费回归](../backend/tests/test_checkout_cart_consumption.py)。

## HITL和Checkpoint分别解决什么？

HITL划定权限：WAITING_INPUT前没有订单，用户审阅不可变快照并独立批准；测试自动点击必须标明TEST_OPERATOR。Checkpoint解决图状态暂停与恢复。两者还需配合持久业务回执、Journal和Epoch Fence，防止旧执行者写入。不得把它说成外部付费模型调用任意崩溃下的exactly-once；也没有证明生产SLA或任意灾难恢复。

## 遇到过哪些实际问题？

| 问题 | 实际处理及边界 |
|---|---|
| “不想买”被当成购买意图 | 当前轮明确否定阻断购买门禁；购买意图不跨Run继承。见[意图/目录回归](../backend/tests/test_t16_a2_intent.py)。 |
| 通用品类“键盘”召回空 | 从可信category加入中文品类名并版本化索引；没有降低0.45阈值或固定返回某个SKU。[T16-A3历史报告](evidence/t16-a3/report.md)保留失败，后续R8远程验收补齐工程链路。 |
| 非root验证器读不到源码、Jieba缓存不可写 | CI辅助修正公开源文件可遍历权限及独占Runtime缓存挂载；私有证据仍0700/0600，未改成root执行。见[CI入口](../scripts/ci/t16_admission.py)与[缓存预检](../scripts/ci/t16_cache.py)。 |
| Mac采样吞吐不足和历史墙钟回退 | 保留失败，没有改JWT或时钟门槛；独立Ubuntu R8通过不代表本地Live已准入。本次Fixture演示不重跑60/900秒验收。 |
| 购物车下单后仍残留商品 | 购买提案绑定Cart来源和版本，订单创建时同事务安全消费；变化后的购物车保留。 |
| 本次Docker Hub元数据超时 | 使用可信本地依赖缓存与当前源码完成离线镜像构建；没有修改网络、依赖锁或业务逻辑。 |

## V2 如何把功能连成可演示的产品？

商家工作台补齐订单履约与售后界面，复用原领域API和店铺授权。买家Agent生成订单，用户独立模拟付款后，商家才能发货；版本冲突读取当前状态，退款保留提案、批准、执行三步。[跨模块浏览器测试](../frontend/tests/v2-rc.spec.ts)覆盖推荐、购买确认、模拟付款、商家送达和只读评测展示。

动态编排的问题最先暴露在固定AfterSales→Shopping→Order的Mock脚本。生产Supervisor原来已有动态路由提示，修复进一步把购买意图、必要信息与交接范围变成服务端前置校验。推荐不自动转成购买，真实推荐失败仍保留PARTIAL；旧确认不能授权另一次购买。

## SSE如何在同步POST未结束时工作？

Run先独立提交，页面根据同一request_id用Thread GET找到它，再建立fetch SSE连接。SSE只是已提交RunEvent的只读投影。服务端按seq分页、短事务、有限连接窗口；客户端用最后接收的seq补读和去重。JWT放在内存和Authorization头，退出登录会取消连接。新状态事件还触发Thread核对，防止跨窗口跳过短暂RUNNING后仍显示旧的人工确认。

## 如何让评测工作台的数字可信？

导出器使用现有scheduled_rows和paired_report，未运行项继续留在计划分母。机器延迟取已有测量，新增业务副作用取Oracle前后快照的ID差集计数，公开JSON不带实体ID和原始Trace。页面分别显示Oracle判定与Run状态，安全拒绝或预期部分成功可以通过Oracle。Fixture只能证明此批链路与业务检查，历史Live Pilot的开发集成绩不能外推成当前版本的真实模型提升。

## 可以讲的实测结果

当前 RC 的完整本地回归、平台、源码绑定和失败修复见[RC 回执](evidence/v2-rc/verification.json)及[结果索引](RESULTS.md)。讲述时以对应版本为单位，下面的R8与原三轮Demo继续作为历史证据。

- 历史[R8 Ubuntu CI](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/41972687787)：CI/执行器提交`e60ee792d6809dad696f27aac1e40272dd04f141`，冻结产品提交`77b215878edbce50ce107c6e77e31de4d2044ff9`；pytest834/14skip、Vitest85、Playwright96，Stage B真实BGE/14检索/三轮Mock/只读Oracle通过。
- [历史三轮浏览器记录](evidence/portfolio-demo/verification.json)：三轮2→3件候选、预算300→400、TEST_OPERATOR批准后唯一¥399待支付订单，目标库存预留1，付款0；刷新登录和Thread恢复后不重复下单。
- 该历史演示的12次SDK MockTransport交互不是真实Provider调用；真实Provider请求及Key读取0。历史T15-B1仅在旧617cdf29做过一个真实购物Smoke，不能冒充当前T16真实多轮成功。
- 没有本次性能基准、真实支付/退款、生产部署、模型泛化结论或正式录屏；Journal两个字段直接快照仍不在冻结验收范围内。
