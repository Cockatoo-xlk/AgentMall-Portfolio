# V2.10 · 真实本地BGE / Cross-Encoder验证

状态：**AGENTMALL_V210_REAL_RAG_RERANKER_READY**。仅本地代码、实验及回归；无Push、远程CI、真实LLM或付费Provider。

Git基线`5bdf717280dbd623da8e842905e1757c098774f6`，新代码运行于修改工作树。实际检索相关源码内容SHA256：`6ca413a0c0fd051b0544b0c109511d6c5e070ff390aae30cc71d81640c28eb66`；[逐文件绑定、命令与退出码](verification.json)。包含本报告的本地提交提供最终Git身份，不能将基线当作修改后版本。

## 真实模型与环境

固定BGE六文件及Reranker七文件SHA和大小全部通过，512维L2向量实测通过。模型、许可证、复现入口和安全边界见[指南](../../REAL_RETRIEVAL.md)。Linux aarch64、CPU、Python3.12.10、Torch2.9.1+cpu、Transformers4.57.6、PG17.11/pgvector0.8.7；Guest4CPU/5GiB、PG1GiB，不是新Ubuntu amd64验收。首次进程加载：BGE 3250.48ms、Reranker 3124.40ms。OS文件缓存可能已热；不称为冷磁盘性能。

Reranker`BAAI/bge-reranker-base@2cfc18c9415c912f9d8155881c133215df768a70`，weights SHA256 `ced967c45fd1902eb92716c9ceeca7c95a936770ea9db611f5a841b926e33fbd`。最大256Token、batch4、候选20、load60秒/inference10秒；CPU logits只用于排序。

## 最终固定Test结果

20条计划查询，每架构16有答案/4无答案；四条Pipeline均完成20/20。Recall/MRR/NDCG宏平均只以16条有答案查询为分母；无答案正确率分母4。非法结果0、过期索引泄漏0，所有分类结果和逐查询Top5在[公开静态投影](../../../frontend/public/evals/retrieval-v1.json)。Lexical为`ts_rank_cd`，不是BM25。

| Pipeline | 完成/计划 | Recall@5 | MRR@5 | NDCG@5 | 候选Recall@20 | 候选NDCG上限 | 无答案正确率 | P50/P95 ms | 平均重排 ms | 模型调用/查询 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical | 20/20 | 89.41% | 87.50% | 86.79% | 92.19% | 92.70% | 25.00% | 3.45/4.55 | NOT_APPLICABLE | 0.00 |
| dense | 20/20 | 89.41% | 92.71% | 91.05% | 95.31% | 98.43% | 25.00% | 22.49/28.31 | NOT_APPLICABLE | 1.00 |
| hybrid | 20/20 | 92.53% | 96.88% | 95.82% | 95.31% | 98.43% | 25.00% | 22.35/37.02 | NOT_APPLICABLE | 1.00 |
| hybrid_reranker | 20/20 | 91.84% | 100.00% | 97.40% | 95.31% | 98.43% | 25.00% | 654.77/1315.71 | 708.22 | 1.95 |

## Dev结果与标注局限

每架构14条有答案/6条无答案，标签为SINGLE_ANNOTATOR，不是独立人类标注。40条冻结标签覆盖13类，商品为120+1合法发布+7探针。**dev-01漏标动态27英寸QHD显示器**；保留原分母与标签，不补答案提高成绩。Test未修改、没有根据测试结果调参。两个运行原件都保留；最终代码重跑是为了验证独立Oracle/模型启动修复，不能称独立Holdout。动态商品新ID只影响dev-01的词法平局顺序；Test质量数字与首轮相同。

| Pipeline | 完成/计划 | Recall@5 | MRR@5 | NDCG@5 | 候选Recall@20 | 候选NDCG上限 | 无答案正确率 | P50/P95 ms | 平均重排 ms | 模型调用/查询 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical | 20/20 | 86.31% | 88.10% | 83.50% | 98.21% | 98.80% | 16.67% | 3.69/4.94 | NOT_APPLICABLE | 0.00 |
| dense | 20/20 | 91.67% | 96.43% | 90.75% | 97.02% | 98.80% | 16.67% | 24.43/57.95 | NOT_APPLICABLE | 1.00 |
| hybrid | 20/20 | 95.24% | 89.88% | 88.33% | 98.21% | 98.80% | 16.67% | 23.45/37.05 | NOT_APPLICABLE | 1.00 |
| hybrid_reranker | 20/20 | 91.67% | 91.67% | 89.39% | 98.21% | 98.80% | 16.67% | 907.77/1307.38 | 844.11 | 1.95 |

## 结论与失败查询

**DEFAULT_OFF**。重排对本次Test的MRR/NDCG略有收益，Recall下降，CPU延迟增加约29倍（按P50）；不足以在默认检索路径启用，也不能推导统计显著优势或生产SLA。原Agent/Bundle继续原路径。候选Recall20的95.31%是重排无法补救的召回缺口；无答案正确率25%，重排只排序不构成拒答机制。

- test-19：出差酒店烧水。Lexical无结果；Dense/Hybrid只召回2个正相关ID中的1个，重排不能补回漏召回。
- test-20：查询过期分词索引Z907。过期目标未泄漏，但返回其他合法手机，语义无答案判定失败；安全过滤与语义质量分开记录。
- test-07：100元手机。四条均空，硬预算得到遵守。
- dev-01：动态显示器标签遗漏是已知测量局限，不归咎于模型。

## A—L实际检查

| 场景 | 实际证据 |
|---|---|
| A 真实BGE | 六文件SHA、512维范数断言、120+商品实际索引，非Fixture质量成绩 |
| B Revision与当前文档 | 固定Manifest、ProductSearch模型/分词版本、content hash/current Catalog Version；旧索引探针拒绝 |
| C 四种合法召回 | 每查询独立按ID读取Product+Index做Oracle，不复用召回SQL scope作为唯一检查 |
| D 重排范围 | 每查询C/D候选ID集合相同，输出仅来自合法候选；打分后重读当前事实 |
| E 同一分母 | 冻结20dev+20test、四架构160执行；失败不缩分母；前端拒绝共同删题 |
| F 预算/属性/库存/Store | 真实PG探针及竞态测试覆盖price/version/active/stock/foreignStore，无非法结果 |
| G 调价/下架/重新上架 | 原商家审核发布路径执行，旧索引隐藏，显式重建后可见；6项生命周期断言通过 |
| H 动态商品 | TEST_OPERATOR独立提交/审核/发布/索引，绑定真实Product ID；不是硬编码检索答案 |
| I 模型缺失 | 明确503或显式HYBRID_FALLBACK；不声称真实重排 |
| J 超时/异常 | 真实子进程超时终止，不自动重启；业务只读快照一致，无提案/订单/付款 |
| K 旧Agent/Bundle | 完整离线pytest和跨模块Playwright确认旧约束、单SKU/Bundle、HITL/幂等兼容；不是新真实LLM能力验收 |
| L 页面 | 桌面/手机真实浏览器，四条对比、分类、失败和Top5，畸形报告拒绝；无业务写请求 |

## 数据库终态与清理

质量查询全在READ ONLY事务中；独立安全Oracle读取当前商品/索引。业务snapshot前后均`c500809f78dd477323545ce1c6ec09d18141f77a3640ef5c1ba3c091471f675d`，orders0/payments0/action_proposals0。质量采集后单独执行合法商品生命周期测试，再清理仅本轮Schema。

清理前独立PG查询无剩余test_/cp_ Schema；本轮PG、Volume、新runner tag及瞬态Guest均删除后查无。原25个历史容器ID/状态未变，默认Docker context仍colima，无历史数据库/Volume删除或BuildKit prune。模型缓存及失败下载片段留在忽略私有目录，非已清理资源；详见回执。完整运行峰值内存没有连续测量，**PEAK_MEMORY=NOT_MEASURED**，不宣传内存余量或吞吐保证。

## 定向与完整回归

- 新后端18项，最终专项18通过；相关旧检索、商品、Bundle累计定向80通过（集合重叠不相加）。
- **完整离线pytest 1056 passed / 14 skipped**，原13项BGE依赖及1项私有Live原件比较边界保持。真实模型实验另行实际执行160查询，不能把skip算模型通过。
- **完整Vitest118 passed**（新增14）；**定向Playwright16 passed /0 retries**（新增2）。浏览器不是完整套件回归。
- Ruff、format --check、TypeScript、ESLint、生产build全部退出0；原始日志SHA见回执。

## 所有保留失败与安全边界

首次公开权重流中断于702711011字节，Range续传又中断于804209244字节；本地依赖安装遇代理CONNECT拒绝。诊断后只对该下载进程禁代理，最终一次固定URL剩余Range206及全文件SHA校验通过；未改系统代理/CA，未关闭TLS，不下载第二个模型。原失败片段和日志保留。首次隔离构建network-none导致缓存/缺依赖失败，受控修正后复用缓存构建；没有删除原件。

TDD RED及中间失败全部保留：缺端点404、缺指标模块、前端不合法百分比/Fixture标签、worker启动EOF、Oracle非独立、移动端溢出、分母和缺失字段判定。一个新测试的monkeypatch目标修正、Ruff条件合并及首次跨运行指标相同断言失败也单独保留。清理脚本最后把相对临时指针与绝对路径直接比较而失败；资源删除已完成，后续仅规范化本轮指针并独立只读查无，没有重复删除或触及其他资源；原失败记录保留。没有删除测试、增加skip/retry、改标签或原业务规则来挑选绿。

公开仅脱敏合成数据和截图；私有原始日志、缓存、DSN、认证和Checkpoint不入Git。原支付/退款/库存/HITL、MCP权限、旧评测/Manifest/订单逻辑全部保持。Provider请求0、Provider Key读取0、托管Embedding0、远程写0。没有真实LLM评测、生产压力/SLA或新的远程CI。
