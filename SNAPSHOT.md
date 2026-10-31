# 独立源码候选的来源与边界

来源固定研发Commit：7cabcca55d600341b26972a46de757f26a50f044。文件由已跟踪Git对象白名单导出，未clone、未复制.git或任何原Git提交历史；本目录没有新的Git根提交、作者元数据或remote。R4候选原293文件保持不变，本目录是其新的R5审核副本；R5仅更新许可和审阅文档，不冒称历史原件。

保留完整Backend/Frontend源码、原迁移与锁、原测试、合成Seed/政策、evals Python执行器及数据和冻结Manifest、离线CI及隔离Demo。原生产逻辑/Prompt/Oracle/Tool Schema/任务数据字节不变，没有为公开展示降低测试要求。

明确保留的历史声明：

| 文件 | 保留原因 |
|---|---|
| evals/evidence/t11/matrix-freeze.json | integration/conftest.py校验22案例预先冻结哈希，不是原执行日志 |
| evals/evidence/t12/provider-research.json | manifest.py读取冻结Provider配置/历史价格，不是本轮有效付费报价 |
| evals/evidence/t12/sealed-fixture-claim.json | 原封存题已消费的声明，防止删除声明后误当可重新评测 |
| evals/evidence/t12/sealed-development-disclosure.json | 原40题已参与开发的披露，不恢复独立Holdout身份 |
| evals/config/*.yaml、evals/data/*合成文件 | Mock协议、冻结哈希与任务/Oracle回归实际依赖；无授权原件或Key |

排除所有原始Live Ledger/锁/授权/Episode、私有Run/Checkpoint、未审日志/截图、历史证据目录中的操作脚本、压缩源码归档、本地.env/模型/缓存/数据库、Git历史和个人工作站路径。三张截图只从R2已审阅清单按SHA取用。

原研发历史审计和专用historical-report/audit CLI的私有证据未导出，因此这些历史诊断命令无法在本目录重读Private原件；只保留现有的1项缺私有Live原件skip，其合成安全阴性控制继续执行。真实BGE缺权重按现有13项skip；不得新增跳过T09/T11、预算、权限或事务核心来制造绿色。

Manifest保留原字节、SHA和已过期授权边界，只可作为历史声明或合成测试输入。创建新的Manifest需要新身份/来源和明确标记，不将本候选当作原实验重新执行入口。此目录没有新Live授权，默认演示和测试全部使用Fixture/Mock。原40题不重新跑封存实验。

导出清单、源blob/内容SHA与排除列表保留在Private交付证据；公开副本的独立运行与隐私结果见[结果](docs/RESULTS.md)。权利人已选择项目MIT及版权署名，详见[LICENSE](LICENSE)和[COPYRIGHT](COPYRIGHT.md)；不包含公开上传授权。PUBLICATION_AUTHORIZED=NO、PUBLIC_RELEASE_NOT_RUN。
