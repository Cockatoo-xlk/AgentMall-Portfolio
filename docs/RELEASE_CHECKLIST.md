# 正式GitHub发布前的权利人审核清单

## V2.14 发布候选检查（本地，不是发布授权）

- [x] 独立分支`codex/v214-portfolio-release-candidate`，产品基线`280ec90816ed3d70079b7fb89457f7f13a4d2278`；最终Commit由 `git log -1 --format=%H -- docs/evidence/v214/verification.json` 定位，准确40位值随最终交付。
- [x] 功能冻结：不进入L8，不增加角色/API/工具/支付或改变事务、HITL、预算、Oracle。
- [x] [能力矩阵](V214_RELEASE_CANDIDATE.md)与[历史真实模型投影](evidence/v214/live-summary.json)：9/10仅绑定b5d6a685；L7同产品源码仍PARTIAL，不宣称当前B2通过。
- [x] 本轮完整pytest/Vitest/Playwright与静态构建实际完成，14项原skip保持，命令/退出码/日志SHA已封存。
- [x] 当前Single / MockTransport / Fixture Demo入口实际跑通，用户独立确认前无订单、之后唯一待支付，重复读取不重复写入。
- [x] Git可达历史、当前JSON/截图、文档链接、MIT和第三方声明均完成审核；原件/Key/权重不进Git。
- [x] 新建自有测试资源已保全后清理并独立查无；不触及25个历史容器或旧Volume。
- [x] 只读核对远程main=`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`；最新已发布V2.5=`c8e9683502e8672d7c23ff9f9b17b79d019c0220`，Run42348866265 Attempt1 success。产品源码已多11个本地提交，RC提交将再加1；这不是当前远程CI成绩。
- [ ] 所有者独立批准准确新Commit、目标分支和一次Push（**OWNER_APPROVAL_PENDING**）。本轮没有Push/Dispatch/PR/Release/部署。

[本轮最终回执](evidence/v214/verification.json) · [一次性普通Ubuntu CI发布方案](V214_RELEASE_CANDIDATE.md#一次性受控发布方案未批准未执行)。当前 **NO_PUSH / REMOTE_CI_NOT_RUN_FOR_V214 / NO_LIVE_REQUESTS / NO_DEPLOY**，VIDEO_NOT_RECORDED。

## 历史T15检查清单（原文保留）

状态：T15-C原阶段因81通过/6失败而阻塞，该历史回执保持不变。T15-C1在新独立稳定Linux环境完成87/87、0skip/0retry/0flaky，当前 **T15_C_LOCAL_RELEASE_GATE_PASSED**，仅解除本地验收阻塞。原共享VM仍有时钟问题，未来使用该环境前必须重新准入；详见[T15-C1回执](evidence/t15-c1/report.md)。

本轮 **NO_PUSH / REMOTE_CI_NOT_RUN / NO_DEPLOY / PAID_REQUESTS_ZERO**。此清单不是发布授权。

T15-D1的最终公开内容、历史Blob、许可与素材审查见[D1报告](evidence/t15-d1/report.md)。本地候选准备与后续上传分开记录；未来Push后本页的阶段性记录仍不等于新远程CI回执。

- [ ] 审阅最终准确Commit SHA、父链及相对于已发布main的差异；远程main只读核对，如已变化停止，不覆盖/强推。
- [ ] 审阅 [D1最终公开审计](evidence/t15-d1/publication-audit.json)及保留的[T15-C历史审计](evidence/t15-c/publication-audit.json)：每次提交可达旧blob、作者身份、个人路径、秘密、原始账本/Checkpoint/授权、素材/版权均已分类；不能仅靠删除HEAD文件消除历史泄漏。
- [ ] MIT/Cockatoo-xlk署名和第三方NOTICE继续有效；本次只发布源码与审阅素材，不授权模型权重、镜像或二进制分发。
- [ ] B1公开汇总明确绑定617cdf29和旧指纹，仅一次指定场景；新指纹Live=NOT_RUN。原T12同开发集、Multi第二轮4/5、原40题非Holdout、账单UNKNOWN等披露保留。
- [ ] 审阅当前源码本地离线回归实际数量、14项skip逐项原因、所有失败与修复、Docker OOM/资源限制；不声称新版已通过远程CI。
- [ ] 审阅演示/恢复手册；默认Fixture无Key，Live需新环境/新Policy/新授权；VIDEO_NOT_RECORDED保持直到有真实录屏。
- [ ] `.playground`、`.t15-c`、`.t15-c1`、`.t15-d1`、`.env`、模型、数据库、私有日志、原始浏览器Trace在Git/构建上下文排除；Actions仅上传有界脱敏状态摘要，不增加Secrets或付费模型步骤。

权利人下一步须逐项明确授权：

1. 目标 `Cockatoo-xlk/AgentMall-Portfolio`、可见性Public，允许上传的准确新Commit SHA及目标分支。
2. 是推审核分支并创建PR，还是允许对main进行非强制快进；不得自动选择，远程有新内容就停止。
3. 是否允许Push自动触发Actions，是否允许创建/合并PR；仅一次上传，不挑绿色反复dispatch。
4. 是否另行允许Release/录屏发布；仓库Push不自动授权部署、镜像或模型权重。

获批后核对远程HEAD，再受控上传获批SHA，记录GitHub Run ID/URL、attempt、Ubuntu24.04 amd64、依赖版本、真实pytest/skip/Playwright数量及失败原因。未获真实成功回执前保持REMOTE_CI_NOT_RUN或FAILED，不能用ARM64本地结果代替。

优先采用[D2审核分支方案](evidence/t15-d1/remote-ci-plan.md)：只推获批SHA至尚不存在的审核分支，核验Push自动产生的唯一CI Run；创建/合并PR及更新main继续单独授权。TLS验证始终开启，不导入未经核实的证书。

本候选不要求运行新的付费Live作为本轮离线交付门槛；若希望宣称当前版本LIVE_AGENT_VERIFIED，必须另行批准完整源码/环境/价格/策略/预算/场景并真实执行，不能重用B1。
