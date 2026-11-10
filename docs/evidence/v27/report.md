# V2.7 — 商家商品运营本地验收

状态：**AGENTMALL_V27_AI_CATALOG_OPERATIONS_READY**（本地离线）。基线 `cb70ebb6687490db7b21794eb8257a1078d6939d`，分支 `codex/v2-ai-catalog-operations`。V2.6远程CI仍未运行，不借用历史R8或V2.5远程结果。

## 已实现范围

- merchant/Store隔离的商品、草稿、导入和索引任务列表，UUID游标和状态筛选。
- CSV/JSON受限文本导入、行级错误、原始输入/证据引句、手工创建和修订。
- 默认MODEL_DISABLED，受控演示显式使用SDK MockTransport；建议不能执行业务工具或直接写正式商品。
- 审核与发布分开；内容版本/摘要绑定、拒绝和撤销审核、已发布草稿不可变。
- 单商品有界索引任务；保留既有0.45阈值、Store/active/版本/哈希保护。
- 原CHECKOUT、独立Confirmation、库存事务、官方Checkpoint、SSE、幂等与Bundle路径复用。

## 独立审查与修复

| 实际问题 | 最小修复 / 证据 |
|---|---|
| 中文“IPS面板”边界未识别IPS | 使用ASCII词边界，验证六字段原文引句 |
| 旧修订可恢复付款已消费库存 | Product锁内比较base_on_hand；真实模拟付款后的RED/GREEN测试 |
| 否定、未知或冲突规格被当作正向事实 | 分句保守拒绝并标记uncertain，数字边界禁止后缀截断 |
| 待审表单未保存编辑与实际审核数据不同 | 审核/批准快照只读，显式撤销审核后编辑 |
| 新表外键阻止测试重置 | 只在专属测试入口将四张表加入既有精确Schema重置清单，无CASCADE |
| 旧Migration head断言不含0010 | 增加新head和四表预期，旧迁移内容与业务断言不变 |

## 验证结果

最终源码在独占Linux aarch64的PG17/pgvector中完成串行验证。实际命令、UTC、退出码、原始日志SHA、源码树身份和截图SHA见[脱敏回执](verification.json)。最终Commit可由包含本报告的本地提交定位，基线SHA不冒充新增代码身份。

| 检查 | 实际结果 |
|---|---|
| 完整CI_OFFLINE_CORE pytest | **981 passed / 14 skipped**（原946 + 新35） |
| 完整Vitest | **102 passed**（原99 + 新3） |
| 完整Playwright | **111 passed / 0 retries / 0 skipped** |
| 最后商品运营专项 | **4 passed / 0 retries**（含全量已覆盖的3项，不相加为115） |
| Ruff / format / TypeScript / ESLint / build | 全部退出0 |

原14项skip未增加：13项真实BGE权重依赖、1项未公开Live原件比较。完整浏览器111之后增加了只读审核回退用例，最终4项覆盖全部新增浏览器场景；最后一次修改仅为该测试的严格combobox定位，生产/后端测试源码未改变。没有虚报112项已完整重跑。

实际数据库断言覆盖：未发布Product增量0；同请求导入并发一次；跨Store不可读写；独立审核/发布；新旧索引版本/内容哈希；新商品单SKU购物车订单；Single/Multi两种Agent模式的新品Bundle双SKU订单；确认前订单0，确认/重放后唯一PENDING_PAYMENT订单、付款0及准确库存预留；旧订单快照不变；付款后旧库存草稿拒绝；原有Bundle、售后、商家履约/退款、SSE、评测页面回归。

业务/Checkpoint测试Schema已由受控Fixture清理，独立只读查询确认无本轮test_/cp_残留；随后停止并删除本轮独占PG及Volume，独立查无，25个历史容器ID和状态保持不变。临时合成凭据已移除，私有原件目录0700/文件0600保留。清理时显式rm报告容器已不存在，已通过独立inspect确认，不把该返回码忽略或假报为删除成功。

## 保留失败

- 首轮RED16失败，确认新能力尚不存在，保留原件；后续解析边界和测试投影字段修正均有独立日志。
- 首轮扩大pytest误用了默认LOCAL_FULL_WITH_BGE入口：14 failed / 969 passed / 2 skipped。12项因该镜像未安装Torch/真实BGE，1项在并行测试使用同一独占数据库时碰到Schema集合变化，1项在测试执行期间源码继续变更而触发冻结指纹拒绝。该轮不作为最终验收。
- 浏览器早期3项重置失败已修正专属Harness的FK清单；随后2项因测试整页导航清空内存JWT而失败，改用正常SPA导航/登录流程。没有放宽认证或持久化JWT。
- 库存旧草稿RED实际返回PUBLISHED，证明已售库存可能被恢复；修复后以STOCK_CHANGED拒绝。
- 最后增加的手工草稿场景使用getByLabel精确定位select失败，改为同等严格的combobox角色/名称定位；4项最终全通过，无生产改动。
- 私有清理预检最初假定Volume使用scope标签、以及stderr大写，检查拒绝后按实际owner标签严格验证；未放宽归属。
- 早期Ruff/路径格式化失败和上述原始日志均私有保留；没有增加skip、retry或改写历史结论。

## 边界

本轮仅离线MockTransport和Fixture Embedding；真实PG与pgvector、LangGraph、官方Checkpoint和交易执行不被模拟。没有真实LLM或语义Embedding准确率结论，未启动Live、读取Provider Key、Push、Dispatch或部署。有限解析器不支持的规格由商家人工补齐。索引是显式单商品操作，无后台自动队列。截图中的人工确认为TEST_OPERATOR，付款0仅指本轮新品购物场景；完整回归中包含原有合成模拟付款/退款测试。
