# 验证结果与证据边界

本页是脱敏公开候选摘要，不包含原始Live账本、授权或私有模型对话。历史研发原件留在Private仓库；这里的摘要不能充当候选Public仓库的远程CI回执。

| 原研发RC环境 | 实测 | 身份 |
|---|---|---|
| Mac完整后端 | 656 passed | R1本地完整验证，含真实BGE |
| Linux ARM64 CI等价 | 642 passed / 14 skipped | R1容器验证，不与Mac相加 |
| GitHub Ubuntu24.04 amd64 | 642 passed / 14 skipped；Vitest38；Playwright43 | Run41170933236，Attempt1，2026-10-31，SHA7cabcca55d600341b26972a46de757f26a50f044 |

[脱敏远程摘要](evidence/private-rc-ci.json)记录具体Step、初始化和Artifact核验。独立候选已在新的Linux ARM64 Debian容器中无缓存安装并完成离线CI：后端642passed/14skipped，Vitest38、Playwright43，总流程退出0；这与原Private Ubuntu amd64的执行分别记录。[本候选实际回执](evidence/candidate-verification.json)。独立Fixture浏览器Demo两次确认、刷新重登、SQL与Checkpoint核对通过（1→2张订单、REQUESTED Case1、Refund0、Checkpoint41、RunEvent69、Provider请求0）。本轮仍没有候选远程CI。

| 同一开发集Pilot | 第一次 | 第二次 |
|---|---:|---:|
| Single / Multi Oracle成功 | 1/5 / 4/5 | 5/5 / 4/5 |
| 实际模型请求 | 43 | 53 |
| 输入 / 输出Token | 92,638 / 8,277 | 130,259 / 10,159 |
| 冻结高峰价格估算 | ¥0.251492 | ¥0.341790 |
| 平台真实账单 | UNKNOWN | UNKNOWN |

[脱敏Live摘要](evidence/live-pilots.json)。第二轮Multi B2仍失败/PARTIAL，仅合法REQUESTED Case、无替代订单；外层误判SIGINT与退出130/-2保留。L6后没有第三次真实复测，修复效果LIVE_EFFECT_NOT_VERIFIED。原40题已参与开发，两轮同五题，不是独立Holdout、统计显著的架构优势或生产质量证明。

本候选未上传任何远程，PUBLIC_RELEASE_NOT_RUN。没有真实支付/退款、云部署、生产负载、SLA或任意崩溃的外部调用exactly-once保证。VIDEO_NOT_RECORDED。

## R5最终审核副本

R5新的独占数据库和无缓存构建已完成完整离线CI：后端642passed/14skipped、Vitest38、Playwright43，总流程退出0；[本轮回执](evidence/r5-verification.json)绑定实际测试内容树，不能当作新的远程CI。项目源码范围可进入权利人最终发布审核（PUBLIC_SNAPSHOT_READY_FOR_OWNER_APPROVAL），本目录尚未公开上传，项目MIT已由权利人选择；R4与原Private远程成绩继续保留各自身份。
