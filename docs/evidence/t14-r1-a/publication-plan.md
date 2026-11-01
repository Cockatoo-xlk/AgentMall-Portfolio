# 后续T14-R1-B方案：尚未授权，未执行

本阶段没有GitHub写许可。当前仅允许只读查询与本地候选准备，GitHub账户具备写权限不等于用户授权。

权利人审核本地最终回执后，下一阶段必须重新明确：

- OWNER/REPO：`Cockatoo-xlk/AgentMall-Portfolio`，现有Public仓库，不创建新仓库，不改变可见性。
- APPROVED_SHA：本轮提交后回执中的完整40位SHA，不能使用分支名称、占位符或“最新版本”代替。
- SOURCE_BRANCH：本地`codex/t14-r1-a-release-candidate`。
- TARGET_BRANCH：远程`main`。
- EXPECTED_REMOTE_MAIN：`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`；若已变化，停止并报告，不覆盖。
- PUSH：是否明确允许仅上传上述SHA及其已审核公开祖先链，不推送全部分支/标签，不Force Push。
- ACTIONS：是否明确允许该Push自动触发现有workflow，并只读观察实际Ubuntu24.04 amd64结果；不额外dispatch或重跑挑绿色。
- HISTORY：保留公开独立根、已有文档、P0/P1及本轮必要审核提交；不引入Private研发历史或未审文件。

授权后建议的顺序（本轮均不执行写操作）：

1. 只读核验候选HEAD/工作区、远程仓库身份/可见性、远程main及最终内容树哈希，核对确切授权SHA。
2. 确认现有origin完全匹配，候选包含原main的线性祖先。不要修改本地Public main或原Private。
3. 仅执行普通fast-forward Push，把获批SHA送至现有main；任何拒绝或未知远程变化先停止分析，不加force、不换SHA或补推。
4. 只读核验远程HEAD等于获批SHA，并观察此次Push自动产生的一次CI；不主动重复dispatch。
5. 保存Run ID/URL、Head SHA、Attempt、Ubuntu/CPU、Python/uv/Node/npm、PostgreSQL/pgvector、迁移/seed/Checkpoint、真实pytest通过/失败/skip原因、Ruff/前端/Playwright结果、耗时和退出码。数字取实测，不能预填670/14或74作为回执。
6. 远程原日志先放本地忽略目录，经过隐私检查后才形成可公开摘要。核查Artifact仍只有白名单状态，不上传原Trace、模型对话、环境或Checkpoint。
7. 失败时保留原Run/Attempt和全部失败证据，区分平台/安装/真实代码/时序/资源；不擅自修改代码后再次Push，不重复运行只选绿色。

本阶段没有授权创建Release、部署、发布镜像或模型、付费调用，后续Push授权也不自动包含这些操作。当前状态始终REMOTE_CI_NOT_RUN；本地Gate通过不是远程CI成功或生产就绪。
