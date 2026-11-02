# T16-A2：多轮意图与目录兼容修复

状态：**T16_A2_BLOCKERS_FIXED_OFFLINE_VERIFIED**。实际源码指纹 `60008bee53f74496afdf4ae3df49c7741d20e2a018f1c56bf2d916b64d8177a6`。基线 cbc6e19，独立分支 `codex/t16-a2-intent-catalog`，本地工作树 `AgentMall-T16-A2-Intent-Catalog`。本报告随最终本地提交交付；完整SHA见交付回执。没有Push、PR/main写操作、部署、真实Key读取或付费请求；真实多轮Live仍为 **NOT_RUN**。

## 根因与最小修复

P0完整数据流：当前用户文本 → `purchase_intent`/`user_constraints` → `resolve_preferences` → `accept_context` 与 Run的不可变 context_snapshot → runtime规范约束 → Supervisor逐字段校验 → Order工具 → `prepare_checkout`。原缺陷位于memory的二次正则覆盖：旧user_constraints已否定，memory又将“买第…”设为true；全句序号收集也会将被拒绝商品当作选择。

- 新增 `agents/purchase_intent.py`：区分正向购买、指定对象否定与全局撤销；中文/数字序号归一化；“不买第二款，改买第三款”只绑定第三款。同对象矛盾、多对象或作用域不明先澄清。插入副词的否定和UUID二选一也有复现与防护。
- 删除memory布尔强制覆盖。购买意图、数量、地址和授权不进入偏好白名单；当前轮明确否定不能被typed输入、Handoff或工具参数恢复。相同未完成Run的澄清仍可补充合法条件，明确撤销会移除当前意图和选择。
- 原HITL、Confirmation、业务幂等、库存、Thread Lock、Epoch Fence、Node Journal和官方Checkpoint内核未改写。旧字段缺省时不序列化新增空排除数组，保留旧payload/hash形状；版本化Thread的prompt边界更新，不能将旧运行静默升级为新授权。

P1根因：旧目录只有连接标签，没有明确定义多模能力；Agent严格相等匹配会拒绝合法的抽象无线需求；旧流程先TopK再过滤，还可能让合格SKU无法进入结果。

- 新增 `catalog/capabilities.py` 和新种子记录的 `connection_capabilities`。合成目录明确规定K87/K98/K108具备wired/wireless能力，原“双模／三模”标签、价格、SKU均保留；没有推断Bluetooth、2.4GHz或真实商品性能。
- 缺元数据的旧多模记录继续保守拒绝无线匹配；显式旧“无线”标签兼容。存在能力字段时类型和值域严格校验；仅有线拒绝矛盾的无线能力。用户排除双模/三模时保留独立约束，UI可查看和清除。
- 店铺、上架、库存、预算、噪声、尺寸、连接能力、键盘类型、排除SKU进入PostgreSQL召回scope，先过滤再候选截断/RRF，随后重新读取当前版本并通过领域工具核验。控制反例证明移除前置过滤会失败。
- **无新增迁移**，仍为0007；扩展的是JSONB偏好与商品元数据。seed仍只插入缺失记录，不回填旧库。旧商品若要补元数据，须单独审核、增加Catalog Version并重建索引；本轮没有修改历史演示库。[目录契约](../../CATALOG_CONNECTIONS.md)

## 安全与业务证据

新增60项后端用例（38项纯约束/能力、22项真实PG/SDK/Checkpoint），1项Vitest、2项Playwright；旧断言未降低，未增加skip/retry/force click。

五条指定否定及扩展否定均有真实PG工具守卫断言：新增提案、订单、Confirmation、付款均为0，甚至伪造Handoff/typed购买标志仍被拒绝。多UUID歧义在Run/Context变更前返回CONTEXT_CLARIFICATION_REQUIRED。购买提案需要当前意图、唯一合法对象、数量和演示地址，模型不能补写授权。

默认12件种子商品完成Single/Multi三轮SDK路径测试，未为该场景注入专用无线SKU。受控MockTransport根据结构化输入和真实工具返回产生不同路径，明确属于离线工程验证，不证明真实模型语义成功。

Linux浏览器连续三轮：300元静音且不买 → 支持无线、400元 → 最新第二款、一件、演示宿舍。实际名单为K87、K98、K108；目标ID来自当前服务端名单，刷新重登后不变。该次第二款是静音K98，39900分；先前名单不能成为新报价。

| 阶段 | 提案 | 订单 | Confirmation | 付款 | Checkpoint行 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 第二轮推荐 | 0 | 0 | 0 | 0 | 32 |
| 独立批准前 | 1 | 0 | 0 | 0 | 47 |
| 批准及Resume后 | 1 | 1 | 1 | 0 | 52 |
| 否定购买场景 | 0 | 0 | 0 | 0 | 32 |

最终唯一PENDING_PAYMENT订单、库存预留1；3个Run完成，Graph next=done、pending_writes=0。85条持久事件按各Run seq连续去重。重复Start/Resume不重复订单，旧名单、版本变化、清除偏好、并发CAS及T14购物车/模拟支付合同由完整回归验证。

[数据库终态](database-state.json) · [安全事件摘要](run-events.json) · [400元候选](screenshots/preferences.png) · [独立确认](screenshots/waiting.png) · [订单回执](screenshots/completed.png)。截图与这些Linux数据来自同一最终浏览器运行，显式标注MockTransport；未提交完整Checkpoint、Prompt或私有账本。

## 最终完整离线回归

最终验收把FastAPI、PostgreSQL、Node、Chromium都放在本轮新建的Linux aarch64 VM内：2CPU、4GiB，容器上限2560MiB、PG上限768MiB。Python3.12.10、Node24.21.0/npm11.19.0、PostgreSQL17.11、pgvector0.8.7、官方checkpointer3.2.0；锁文件和依赖版本未变。

| 命令组 | 结果 | 退出码 |
| --- | --- | ---: |
| pytest backend/tests --ci-offline-core -q -ra | **802 passed / 14 skipped** | 0 |
| npm --prefix frontend test | **85 passed** | 0 |
| npm --prefix frontend run test:e2e | **96 passed / 0 retries / 0 skips** | 0 |
| Ruff check / format --check | 通过 | 0 |
| typecheck / lint / build | 通过 | 0 |

14项skip仍是13项真实BGE权重依赖和1项私有Live原件比较。R1环境另行验证了真实BGE。保留3条既有jieba SyntaxWarning，未升级或屏蔽依赖。逐命令、源码绑定、退出码、日志SHA见 [verification.json](verification.json)。这不是GitHub Ubuntu amd64远程CI。

最终Linux时钟窗口约584.39秒，54,476样本，wall/monotonic增量残差最大约1.81ms，重大异常0；先60秒准入，保持原1ms回退、100ms残差及单调时钟阈值。所有验收进程使用该Linux内核，不以Mac时钟签发或验证JWT。没有修改JWT/预算/安全Guard。

**完整保留环境失败：** 早期Mac+Linux混合窗口虽然功能测试全绿，但Mac在北京时间20:07:15发生约60.53ms墙钟回退，原门禁失败，未事后豁免；原因仍未知且未修复。首次转全Linux时缺少本轮项目合成.env.rag，771通过/31失败/14跳过；补齐独占配置后才重新执行完整流程，未改变产品源码或测试答案。三项旧payload兼容回退、审查RED及所有命令日志摘要也保留：[failure-ledger.json](failure-ledger.json)。没有反复重跑时钟不稳定的共享VM挑绿色。

一次独立只读审查发现“不要再买”及UUID多对象两处问题。均先RED复现，再以工具/真实PG断言及完整回归修复；另补同序号数字别名、typed否定冲突及未决否定作用域。未进行第二次独立审查，也不声称获得独立终审批准。[review.json](review.json)

## 新T16-B0-R1草案

新Compose项目 `agentmall-t16-b0-r1` 与A2验收共用本轮专属Linux VM，拥有独立PG集群、Volume、环境记录和Schema；不复用旧B0或B1环境。宿主PG55449/API8038均只绑定127.0.0.1，前端5208预留但未启动；Live服务未启动。

- Environment：`627b3432-1077-4de9-bb5a-9c1e45129ce1`。
- Session：`2087320f-1280-4fcf-a30b-563f706595ec`。
- Policy SHA：`bdbdba17bd5bf348cff66f0fd679db48da843c4964b8b481709a50bce7202a4b`。
- 源码指纹：`60008bee53f74496afdf4ae3df49c7741d20e2a018f1c56bf2d916b64d8177a6`。
- 草案：¥5、最多24请求、900秒、累计输入2,097,152/输出36,000 tokens；三Run所有Agent共享账本，发送前预留，UNKNOWN/超时安全停止。按高峰cache-miss单价计算token极值¥4.482304，调用上限不是成功保证。
- 官方价格快照：2026-11-02T11:52:05.041341+00:00，有效至2026-11-03T11:52:05.041341+00:00。[官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)及[非思考Tool Calling](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)只读核验；deepseek-flash、V4.1-Flash-1017、高峰输入2/输出8元每百万token，显式thinking=disabled，未调用Provider。
- 真实BGE固定Revision六文件尺寸/SHA一致，CPU512维、真实pgvector索引12商品/10政策chunk；第二轮返回3件当前领域校验合格的商品。预检排序不是未来Live模型必须展示的名单，不预定未来第二款。

[新目录/模型实测](catalogue-preflight.json) · [新Policy草案与剩余门禁](live-preflight-draft.json)。R1业务订单/提案/确认/付款/Run/Checkpoint仍0。缺授权启动实测APPROVAL_REQUIRED且key-loader未调用；旧B0 Policy实测SOURCE_MISMATCH，原文件不变。

**R1仍只是待重新准入的未批准草案**：Mac墙钟回退未修复，实际Live执行前须核对当次时钟/资源/有效价格及最终源码，并取得新的准确范围授权。核心Policy不原生强制三句文本/单买家白名单，固定场景还需要受控操作者核验；没有将此限制包装成已有技术能力。未创建approved=true回执、未读取Key、未创建Live账本。旧B0草案、T12/T15授权和Frozen证据不能沿用，也未重新封存。

## 保护与资源

152个既有公开保护文件、原B0报告与73个证据文件（合计74项）SHA完全一致；原T16工作树仍为cbc6e19且干净。历史Private/Public main、T14/T15目录、旧Live账本和授权没有写操作。[historical-integrity.json](historical-integrity.json)

测试结束后，独立连接核对A2 test_/cp_ Schema0、Advisory Lock0、其他DB会话0；只停止本轮两个项目与新VM，保留Volume及R1已准备Schema，释放本轮进程级保醒断言。原共享Docker/旧容器不动，未重置任何Volume。各容器OOMKilled=false、重启0；Linux验收容器累计峰值约2049MiB，低于2560MiB限额。旧Mac约1.91GiB资源限制与历史OOM没有被改写成已修复。[environment-and-cleanup.json](environment-and-cleanup.json)

完成后停止；不Push、不修改PR/main、不部署、不调用真实DeepSeek。后续真实多轮Smoke需要独立授权与执行时准入，本轮不宣称真实模型多轮能力已验收。
