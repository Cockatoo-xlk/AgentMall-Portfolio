# V2.17 面试作品集 · 本地工程交付

本轮从V2.16准确main `8e21bdcad3170487626a17ccda0f624457bccd26` / tree `1d51671f38c49bfb0986cfb8182b8f81087c9f9b` 建立 `codex/v217-interview-ready`。**V217_INTERVIEW_READY_LOCAL_VERIFIED**：本地测试、媒体和自有资源清理已验证，最终提交身份以[机器回执](evidence/v217/verification.json)和任务最终Commit回执为准。没有Push、PR、Merge、Tag、Release、部署或真实模型消费。

## 基线验收与实际交付

[main CI 43783548437 / Attempt1 / push](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/43783548437)独立读取本次真实日志：Backend1603/14skip/3warnings、935.37秒；Vitest146、Playwright128；[Release Gate](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/43783548437/job/133031102179)出现RELEASE_GATE_PASSED，T16预期skipped。merge双父为 `d18161d1eb40667f4658e745d2f58369767d67f5` / `235f46fca326601aef14dcd2caf124209c92f152`，tree与原候选一致。

本轮复用已通过的产品链路，**未发现必须改动业务/Agent逻辑才能完成演示的缺陷**，因此不新增Agent、Prompt特例或交易规则。新增工作是：连续场景回归、3分30秒视频及可复现编辑源码、三题新Smoke静态契约与防泄漏投影、当前状态文档和12问/简历材料。

Git原生fetch在最小环境遇到证书链错误，原日志保留；使用正常验证TLS的GitHub API取得已签名commit，重建原始Git对象并在写入前核对准确SHA。没有关闭TLS、修改全局CA/remote或移动本地main。原V2.16分支和历史工作树保持原引用。

## 本轮新跑的完整回归

| 验证 | 实际结果 | 范围 |
|---|---|---|
| Backend pytest | **1626 passed / 0 failed / 14 skipped / 3 warnings，769.50秒** | 新独占真实PG17/pgvector，完整后端；含新23项Smoke契约 |
| 固定BGE专项 | **13 passed / 0 skipped / 52 deselected / 3 warnings，24.29秒** | 六文件SHA、固定Revision、CPU512维与SQL往返 |
| Vitest | **146 passed / 23文件** | 前端单元回归 |
| Playwright | **129 passed / 0 skipped / 0 retries，288.187秒** | 正式FastAPI/PG + SDK Mock；含新增连续演示 |
| Ruff / format | PASS，334文件 | backend/evals/scripts |
| TypeScript / ESLint / production build | PASS | 最终前端源码 |

13项BGE按CI_OFFLINE_CORE策略跳过，并在本轮独立真实执行；另1项历史私有原件不可用仍skip。3warnings来自既有jieba正则转义。Playwright中的Fixture checkout precommit rollback是成功的事务回滚负例，不隐去其异常堆栈。完整命令、退出码、耗时和日志SHA见[verification](evidence/v217/verification.json)。先前失败的红测和Ruff检查分别留证，不计为最终通过成绩。

## 连续A/B/C与独立SQL

新[连续浏览器场景](../frontend/tests/interview-demo.spec.ts)在同一演示会话中完成全部流程；每份提案实际GET审查后由明确的合成TEST_OPERATOR发出独立操作。属于CONTRACT_TEST_ONLY，不声称是人类可用性研究或真实模型评测。每个写入都通过正式业务API，SQL由独立数据库连接查询。

| 阶段 | 订单总数 | Case | 预留 | 已存在确认 | Checkpoint行 |
|---|---:|---:|---:|---:|---:|
| 合成Setup基线 | 1 | 0 | 0 | 2 | 0 |
| A推荐后 | 1 | 0 | 0 | 2 | 13 |
| B等待批准 | 1 | 0 | 0 | 2 | 26 |
| B购买与刷新读回 | 2 | 0 | 1 | 3 | 35 |
| C退货批准后、购买未批 | 2 | 1 | 1 | 4 | 74 |
| C独立购买批准后 | 3 | 1 | 2 | 5 | 77 |

Setup的原订单1、模拟付款1、确认2不算Agent增量。三份新确认分别消费；两份Multi确认ID不同；退货确认冒用购买Resume得到409且订单不增。最终新增待付款订单2、Case1；付款/退款增量0。刷新没有重放交易。人工拒绝、跨Actor/Store、库存不足、幂等、Checkpoint/Fence、模型错误和UNKNOWN负例来自完整套件，[9条既有产品场景](../frontend/tests/product-demo.spec.ts)继续通过。上述计数是当前新回归，不是剪辑字幕反向生成的事实。

## 可播放作品集

[agentmall-v217-demo.mp4](media/v217/agentmall-v217-demo.mp4)：**3:30 / 1440×1080 / 25fps / H.264 yuv420p / 2,728,972 bytes**，静音字幕版，13章节、faststart。[讲解与复现脚本](media/v217/agentmall-v217-demo-script.md)、[逐段EDL](media/v217/edit-list.json)、[编辑工具](../scripts/render_interview_video.py)。成片SHA256：`143c029a324632309ded3a03d1847e0944d5718d3034bb351ebf390e25cbe24e`。

保留原6:55 WebM及SHA `c2becdda2b5b33d467d3ff789a83af79d94ca1aa32d775a0bd3c90c5c70e45e1`，原录制器收尾exit1不改为成功。业务画面来自V2.16 RC1，新增说明卡为明确标注的架构/SQL投影，非新终端录屏；原片的静态尾部被移除。整片成功解码、无检测到的黑屏段；16代表帧覆盖全部章节，人工检查清晰度与来源标注，OCR模式扫描未发现用户名绝对路径、Key/JWT/授权头。抽样检查不是对每个压缩像素的绝对隐私保证。没有伪造Provider画面、业务动作或SQL。

## 面试与新Smoke

[README](../README.md)、[架构](ARCHITECTURE.md)、[工程亮点](ENGINEERING_CASES.md)、[12问](INTERVIEW_TALKING_POINTS.md)、[简历项目描述](RESUME_PROJECT.md)和[限制](KNOWN_LIMITATIONS.md)均按实际源码说明LangChain/LangGraph、PG/pgvector、HITL、库存锁、持久回执、Checkpoint和fence；不虚构线上用户量、QPS、SLA或个人独立手写全部代码。

新[三题Smoke方案](V217_LIVE_SMOKE.md)为EXPLORATORY_PRODUCT_SMOKE，固定A/B/C顺序和新需求/初始状态/断言，**尚未执行**。静态CLI只校验与绑定，没有Live启动命令、Key loader或授权能力。最终Source/Tree、任务/协议/断言/BGE/价格SHA在CLEAN本地提交后另封存，避免自指Git哈希。下一次需要Owner单独授权真实Provider、费用、逐项HITL、匿名FD与精确自有资源处理，并在启动前核验现有Runner的全部硬门禁；未验证的接线不能用静态测试冒充。每题上限2.50元，三题7.50元只是预案，本轮授权/实费0。价格24h门禁保留，模型别名不证明不可变权重。

## 保留的限制和审查

L8永久PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7，只有5评分；08 Ledger与实际费用UNKNOWN、E1_ORACLE_CONTRACT_MISMATCH、Independent Holdout=0，原09—15未运行。新Smoke不覆盖旧统计。Release继续ON_HOLD，RELEASE_COMMIT=UNBOUND，MCP REMOTE_AUTH_NOT_IMPLEMENTED。

独立只读审查发现一项最终化状态表述问题，已将预提交阶段的Smoke绑定明确标为PENDING，完成绑定只能由真实post-commit回执证明；无未解决Critical/Important问题。一个Minor为编辑工具的原录制器exit1元数据针对本次固定源素材；当前值与已核验原件一致，若未来换素材需同步其元数据，不能当作通用影片来源验证器。本轮不为该无当前影响事项扩展媒体框架。审查没有把未执行Live或主观视频质量当作通过事实。

所有测试使用显式最小子进程环境和允许清单源码副本；旧.env、私有L8/Gold、旧Host包不挂载给Guest。Runner非root、无Docker Socket/补充group0/privileged，read-only rootfs；PG网络none，Runner只共享该隔离namespace，源模型只读。证据导出并校验后仅允许清理本轮准确Owner/ID的3容器、5Volume，已完成清理并按ID独立确认不存在，机器回执记录3容器/5Volume及258个既有容器稳定元数据；历史对象不处理。最终本地Commit后停止；任何Push/PR/Merge/Release/Deploy仍需新的授权。
