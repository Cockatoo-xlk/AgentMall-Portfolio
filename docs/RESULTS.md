# 验证结果与证据边界

本页是公开作品版的脱敏验证摘要，不包含原始Live账本、授权或私有模型对话。历史研发原件留在Private仓库；其远程CI成绩不代表独立作品版在GitHub上的运行结果。

| 原研发RC环境 | 实测 | 身份 |
|---|---|---|
| Mac完整后端 | 656 passed | R1本地完整验证，含真实BGE |
| Linux ARM64 CI等价 | 642 passed / 14 skipped | R1容器验证，不与Mac相加 |
| GitHub Ubuntu24.04 amd64 | 642 passed / 14 skipped；Vitest38；Playwright43 | Run41170933236，Attempt1，2026-10-31，SHA7cabcca55d600341b26972a46de757f26a50f044 |

[脱敏远程摘要](evidence/private-rc-ci.json)记录具体Step、初始化和Artifact核验。独立候选已在新的Linux ARM64 Debian容器中无缓存安装并完成离线CI：后端642passed/14skipped，Vitest38、Playwright43，总流程退出0；这与原Private Ubuntu amd64的执行分别记录。[本候选实际回执](evidence/candidate-verification.json)。独立Fixture浏览器Demo两次确认、刷新重登、SQL与Checkpoint核对通过（1→2张订单、REQUESTED Case1、Refund0、Checkpoint41、RunEvent69、Provider请求0）。这里记录的候选验证发生在本地Linux ARM64；独立公开仓库的远程CI须以其真实Run ID和对应SHA另行核验。

| 同一开发集Pilot | 第一次 | 第二次 |
|---|---:|---:|
| Single / Multi Oracle成功 | 1/5 / 4/5 | 5/5 / 4/5 |
| 实际模型请求 | 43 | 53 |
| 输入 / 输出Token | 92,638 / 8,277 | 130,259 / 10,159 |
| 冻结高峰价格估算 | ¥0.251492 | ¥0.341790 |
| 平台真实账单 | UNKNOWN | UNKNOWN |

[脱敏Live摘要](evidence/live-pilots.json)。第二轮Multi B2仍失败/PARTIAL，仅合法REQUESTED Case、无替代订单；外层误判SIGINT与退出130/-2保留。L6后没有第三次真实复测，修复效果LIVE_EFFECT_NOT_VERIFIED。原40题已参与开发，两轮同五题，不是独立Holdout、统计显著的架构优势或生产质量证明。

上述原Private RC远程CI不等于本作品版自己的远程CI。没有真实支付/退款、云部署、生产负载、SLA或任意崩溃的外部调用exactly-once保证。VIDEO_NOT_RECORDED。

## R5最终审核副本

R5新的独占数据库和无缓存构建已完成完整离线CI：后端642passed/14skipped、Vitest38、Playwright43，总流程退出0；[本轮回执](evidence/r5-verification.json)绑定实际测试内容树，不能当作新的远程CI。R5阶段的项目源码范围已通过本地人工审核门禁（PUBLIC_SNAPSHOT_READY_FOR_OWNER_APPROVAL），项目MIT已由权利人选择；R4与原Private远程成绩继续保留各自身份。该阶段性审核不替代作品版后续的GitHub发布及CI回执。

## T15-B1历史真实运行与T15-C候选

[经过审阅的B1汇总](evidence/t15-c/b1-public-summary.json)：历史617cdf29，真实deepseek-flash单场景7请求，12,048输入/1,109输出，费用估算上界¥0.032968而实际账单UNKNOWN；用户本人确认后唯一PENDING_PAYMENT订单、付款0、持久事件50、Checkpoint done。没有Single/Multi公平质量比较或泛化结论。

[T15-C验收](evidence/t15-c/report.md)是新源码的本地离线回归及发布审计。源码指纹变化后Live=NOT_RUN，远程CI=NOT_RUN；旧B1授权、账本与历史Manifest保持不变。

## T15-C1：独立稳定时钟环境重新准入

[逐项归因与新回执](evidence/t15-c1/report.md)：在独立Colima Linux VM中，后端713/14skip、Vitest80、完整Playwright87通过，0失败/skip/retry/flaky。生产源码指纹7049db6a保持不变。旧环境同用例复现了JWT未来iat→401，但其余5项历史单请求信息不足，仍标原因未确定；并未把6项全部归为环境异常。旧81/6及原始日志不覆盖。

新环境连续时钟观测无重大异常，准入状态T15_C_LOCAL_RELEASE_GATE_PASSED只适用于该受验证环境。旧共享VM未修复或重启；当前源码Live=NOT_RUN、远程CI=NOT_RUN、新增付费请求0。

## T15-D1：最终公开内容审查

[D1审查报告](evidence/t15-d1/report.md)核对公开独立父链、全部可达历史Blob、15张合成截图及第三方声明，整理首页与运行/恢复入口。产品源码、锁文件、既有测试与workflow均未改变；复用经原始日志和JUnit/Playwright JSON哈希核对的C1回归，没有重新执行Live或封存评测。

截至D1，当前版本Ubuntu24.04 amd64远程CI为NOT_RUN；actionlint、官方Action固定SHA、87项浏览器收集与默认启动路径的静态检查不等于真实远程运行。[D2待授权方案](evidence/t15-d1/remote-ci-plan.md)只计划推审核分支，不授予Push、Actions、PR或main合并权限。后续实际结果应按准确Commit与RunID追加，不能覆盖各阶段历史回执。
