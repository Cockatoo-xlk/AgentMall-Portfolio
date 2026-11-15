# V2.16 RC1 产品发布候选审核

本页为RC1本地验收快照，不授予GitHub写权限。正式main `d18161d1eb40667f4658e745d2f58369767d67f5`；审查产品候选 `ae10b253819e08f468f18e60cf4c46b674b95a5c` / tree `4aeeca6743293f132811626007b5f9ba58774306`。原34项代码、测试、文档、截图和验收文件逐项审查及SHA核验完成，未发现需修复的新增产品问题。RC1只增加文档、录屏状态与新验收摘要；最终提交须保留该产品代码文件哈希。

## 代码审查结论

- 推荐事实只由服务端replacement商品引用与事实快照关联；缺失保持UNKNOWN，当前库存独立GET；界面文字不替代订单或Case。
- Proposal、Run、Interrupt、Confirmation独立绑定，退货批准不授权购买；拒绝回执不冒称已消费交易。响应丢失重放保留原request_id，不自动批准、Resume或Recover。
- 批次内相同完整签名在delegation预算预留与派发前整批拒绝；不同订单引用仍可并行。原Actor/Store、角色、依赖、工具白名单、事务、库存、Epoch/Fence和Checkpoint未改变。
- Mock标签由服务端运行身份确定，不能靠前端开关伪装成Live；完整Usage不足保持UNKNOWN，已知模拟Token也不是供应商结算。
- 原Oracle、DEV/TEST、L8记录、迁移、CI、依赖锁、Prompt和权限均未修改。审查为AI辅助静态审核及本地回归，不是生产安全认证。

[逐文件SHA与实际测试回执](evidence/v216-rc1/verification.json)。完整原Diff SHA256：`7ad7ae085138193b4f34a0d2798a40589848e6a3c63d341732d0810fcf66786e`。

## 本轮实际回归

| 项目 | 实际结果 |
|---|---|
| Backend / 新专属PostgreSQL17、pgvector | 1603 passed / 14 skipped / 3 warnings；pytest704.16秒 |
| real BGE / 固定Revision六文件 / CPU512维 | 13 passed / 0 skipped / 52 deselected |
| Vitest | 23文件 / 146 passed |
| Playwright | 128 passed / 0 skipped / 0 retries |
| Ruff / format / TypeScript / ESLint / build | 全部通过 |

轻量后端13项real_bge按既有策略skip，本轮另行真实执行；另1项私有历史原件不可用仍skip，不伪造通过。3项warning来自既有jieba正则转义。Playwright日志中的Fixture checkout precommit rollback为显式事务故障注入，相关用例及SQL断言通过，不隐藏实际异常。

所有成绩绑定上述产品源码和本轮新资源，不借用V2.15或旧V2.16成绩。普通工程与录制失败日志单独保留；没有Provider自动重试或修改测试Oracle。

## 三条业务场景与SQL

| 场景 | 实际验收 |
|---|---|
| A 推荐 | 三款400元以内无线静音商品；数量/价格/库存快照与SQL一致；明确不购买时没有写入；缺Usage安全PARTIAL |
| B 购买 | 先审阅再独立决定；批准前无订单，批准后唯一PENDING_PAYMENT及库存预留；拒绝/过时商品不写订单；响应丢失重放、刷新读回不增写 |
| C Multi退换购 | 第一次批准Case+1、订单尚不新增；第二次不同批准才订单+1；旧确认409；拒绝退货后新的购买提案仍需独立决定；后续非法响应保留Case |

浏览器另验证跨Actor读取拒绝；正式Resume API的跨Store、旧Interrupt、错误Confirmation、过期、停用用户负例均实际执行，通过后订单增量0。跨Store证据来自后端API回归，不冒称UI切换已演示。SQL数据来自独立连接而非页面成功文字。

## 实际录屏与质量限制

本地私有原件 `agentmall-v216-rc1-offline-demo.webm`：**6:55 / 1440×1000 / 25fps / WebM VP9 / 无音频 / 45,894,328 bytes**。

SHA256：`c2becdda2b5b33d467d3ff789a83af79d94ca1aa32d775a0bd3c90c5c70e45e1`。录制源码为上述ae10b253候选，后续RC1文档提交不改变产品代码。原件未上传GitHub，不将私有路径写进公开页面；[时间码与讲解稿](DEMO_GUIDE.md#rc1-实际录屏)可复现操作。

真实浏览器画面，固定标注OFFLINE DEMO / SDK MOCK MODEL / REAL BUSINESS API / REAL POSTGRESQL。记录A推荐、B购买及刷新、C两份独立HITL、时间线与缺Usage安全停止；每次批准前显式读取实际服务端快照并人工发出独立操作指令。向量为Fixture Embedding；真实BGE专项分开运行。初始化有1张合成已送达订单、1次模拟付款及2份setup确认，不能把它们算Agent新增业务。录屏B新增订单1，C新增Case1/订单1，三份新批准分别消费；真实付款退款均0。

录制器在上述阶段均完成后等待结束指令，于415秒触发自身时限，退出码**1**，不是NORMAL_FINISHED；该失败不改写。原始WebM自动保存，后续独立读取容器时长并在45/112/127/145/170/245/414秒解码通过，抽帧人工检查画面与标注。媒体可播放与录制进程成功是两个结论。没有旁白、剪辑，最后静态停留较长；只能称原始演示材料，不称精剪面试影片。此前录制目录、整页导航丢失登录和旧指令残留错误也分别留证，不归咎于Agent。

## 冻结边界和下一步

L8永久PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7，只有5题评分；08 Ledger及实际费用UNKNOWN，E1_ORACLE_CONTRACT_MISMATCH保留，Independent Holdout=0。未运行09—15、未重评历史结果。真实Provider请求0、真实Key读取0、实际费用0，无真实付款退款。Release继续ON_HOLD，RELEASE_COMMIT=UNBOUND，MCP REMOTE_AUTH_NOT_IMPLEMENTED。

本地验收时远程目标分支不存在，main准确；只读ls-remote出现HTTP2错误，GitHub连接器独立核验成功，未尝试Push。Push CI、PR CI当前NOT_RUN，不引用旧main CI代替。下一步须Owner按最终Commit/Tree批准一次普通非强制Push；仅准确Push CI的Backend、Frontend、Release Gate均success后，才在明确授权内创建一个PR并分别验收PR CI。不Merge、Tag、Release、部署、Dispatch或Rerun。


## 本轮资源封存

导出、内容与SHA校验后，仅清理本轮Owner归属的3个新容器及5个新Volume，按ID/Label逐项核验删除；历史容器元数据及Volume名单未变，原本地配置已恢复，临时合成凭据文件已移除。证据原件、录屏各次失败与最终媒体均在本地私有材料中保留，未删除历史资源。
