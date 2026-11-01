# 公开作品的来源与分发边界

以下导出方式、字节不变和三张截图描述的是R4/R5历史起点。T14-P0/P1/R1-A与T15-A/C是在公开独立历史上的后续修订，不能把这些历史起点声明解释为当前候选源码从未变化。

来源固定研发Commit：7cabcca55d600341b26972a46de757f26a50f044。文件由已跟踪Git对象白名单导出，未clone、未复制原.git或任何原Git提交历史；本作品版在已审核快照之上建立独立、无父提交的Git根，不携带原Private仓库的提交历史。R4原293文件候选及R5审核副本均为独立阶段产物；R5仅更新许可和审阅文档，不冒称历史原件。

保留完整Backend/Frontend源码、原迁移与锁、原测试、合成Seed/政策、evals Python执行器及数据和冻结Manifest、离线CI及隔离Demo。R4/R5初始导出时生产逻辑/Prompt/Oracle/Tool Schema/任务数据字节不变；此声明仅指初始导出，后续功能修订以各自提交/测试为准，没有为公开展示降低测试要求。

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

导出清单、源blob/内容SHA与排除列表保留在Private交付证据；公开副本的独立运行与隐私结果见[结果](docs/RESULTS.md)。权利人已选择项目MIT及版权署名，详见[LICENSE](LICENSE)和[COPYRIGHT](COPYRIGHT.md)。本文记录源码来源、排除范围和R5审核事实；独立公开仓库的实际发布与远程CI状态须以对应GitHub记录核验。


T14发布候选保留原公开独立根、已有文档提交、P0模拟付款及P1购物车生命周期提交，并追加公开文档和审核材料；没有混入原Private研发历史。T14阶段截图共10张，此后T15-A增加5张SDK MockTransport离线截图，当前共15张，第三方边界见[声明](THIRD_PARTY_NOTICES.md)。P0/P1原验收及Frozen Manifest保持原样；历史Manifest不被重封存为新源码的Live授权。T14阶段源码对应关系、文件清单和本地验证限制见[T14-R1-A](docs/evidence/t14-r1-a/report.md)，上传状态以获批SHA和GitHub回执为准，此历史描述不授予上传权限。

T15-C复用上述公开父链，增加服务端提案时钟、展示交互与脱敏B1摘要。B1真实Smoke绑定历史617cdf29和旧源码指纹；当前源码改变后Live=NOT_RUN，未重封存旧Manifest、未复用历史授权。原`.playground`账本、授权及完整Checkpoint不随本作品分发。本轮公开内容审查见[T15-C](docs/evidence/t15-c/publication-audit.json)，新的发布须另行批准准确SHA。

T15-C1在未改变生产源码和既有测试的前提下，使用独立稳定Linux aarch64 VM和Mac Chromium完成完整87项浏览器回归；旧共享VM时钟问题及81/6历史失败保留。T15-D1继续沿用这条公开父链，仅整理展示文档、忽略规则和审查证据，不修改功能或历史原件。[最终审查范围与清单规则](docs/evidence/t15-d1/report.md)明确区分候选准备、远程CI和实际发布；本文的来源说明不因后续上传而改变。
