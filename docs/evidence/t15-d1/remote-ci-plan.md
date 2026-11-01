# T15-D2 — 审核分支上传与远程CI方案（未执行）

本文件是可审阅的未来方案，**不是Push、Actions、PR或公开发布授权**。D1只读观测的目标为Public仓库`Cockatoo-xlk/AgentMall-Portfolio`，main为`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`。不修改原Private仓库、已发布main或历史证据。

## 需要权利人独立批准

1. 准确目标`Cockatoo-xlk/AgentMall-Portfolio`及其Public可见性。
2. D1交付的**完整40位候选SHA**，包含公开独立根及本阶段已审父链；不是任意后续HEAD。
3. 允许仅将该SHA推送至新的`codex/t15-d2-release-review`分支；该分支必须不存在。
4. 允许该Push自动触发一次现有GitHub Actions。D1/D2默认均不创建PR、不合并main、不手动dispatch、不Release、不部署、不注入Provider Key。

若希望创建PR或合并main，需在真实CI完成并审阅后另行明确授权；不能从“允许审核分支上传”推断。候选内容变化也需新SHA审查与授权。

## 上传前只读门禁

- 确认工作区干净、HEAD精确等于获批SHA，完整文件清单/内容树SHA及源指纹与D1提交后回执一致；没有新增私有文件入索引。
- 使用GitHub CLI GET确认仓库身份/Public，重新核对main仍为上述SHA；如发生变化立即停止，不覆盖、rebase或自行换SHA。
- 查询审核分支尚不存在；遇到未知内容停止，不删除远程分支。
- 再做TLS证书验证。D1直接github.com自签名链被拒绝，既有系统loopback代理CONNECT提供有效公开CA链；仅在确认该代理仍属于用户当前配置时使用命令级`http.proxy`，不改变全局设置。分别通过API和Git交叉核对远程SHA。没有有效TLS就停止，不信任新未知根、不关闭校验。
- 再核对历史保护集合和忽略规则，不输出环境变量、Token或Key。GitHub认证按CLI现有安全凭据使用，不把Token写在URL/命令中。

## 唯一获批上传

以下是**授权后**的命令形状，D1没有执行；`APPROVED_SHA`和`VERIFIED_LOCAL_PROXY`必须由操作者在真实门禁后绑定，不能当作已有授权或直接复制占位符执行。

```sh
# 先设置为用户实际批准的40位SHA；缺失即停止。
: "${APPROVED_SHA:?需要真实用户批准的准确SHA}"
test "$(git rev-parse HEAD)" = "$APPROVED_SHA"
test -z "$(git status --porcelain)"

# 仅在已核验现有本机代理且HTTPS验证通过后；不写Git配置。
git -c "http.proxy=$VERIFIED_LOCAL_PROXY" push \
  https://github.com/Cockatoo-xlk/AgentMall-Portfolio.git \
  "$APPROVED_SHA:refs/heads/codex/t15-d2-release-review"
```

只上传这个ref，不使用force、all、mirror或tags。不添加/修改原项目remote，不给Private仓库写入。Push失败后保留原退出和原因，先GET确认远程分支，不盲目再次Push或换分支/SHA。

随后只读核对审核分支HEAD等于获批SHA且main保持原值，记录上传回执。该workflow对push触发，无需手动dispatch；不要额外创建PR引出第二组Run。

## 观察唯一Push Run

用`gh run list --repo Cockatoo-xlk/AgentMall-Portfolio --branch codex/t15-d2-release-review --event push --commit <获批SHA>`只读定位。按head_sha、branch、event和workflow筛选，保存Run ID、URL和Attempt；没有Run或有歧义就报告，不补发dispatch。允许有界等待观察，不rerun失败任务或选取后来的绿色结果。

原始job日志下载到Git忽略、权限受限的D2私有目录；公开仅追加经过审查的摘要。不要把下载的ZIP/原始日志、JWT、完整Trace、Checkpoint、模型对话或授权文件加入Git。

## 远程真实验收字段

| 类别 | 必须取自该Run的证据 |
|---|---|
| 身份 | RunID/URL、head SHA、event=push、审核分支、Attempt、开始/结束、耗时与结论 |
| 平台 | 实际Ubuntu版本及CPU架构；配置ubuntu-24.04不能代替实测，未输出字段记UNKNOWN |
| 依赖 | Python、uv、Node、npm实际版本，锁安装结果及无额外升级 |
| 数据库 | PG/pgvector实际版本、迁移与repeat seed、官方Checkpoint、专属test_/cp_生命周期 |
| 后端 | 实际passed/failed/skipped、14项已有skip逐项原因；T09恢复/SIGKILL、T11行锁并发/Oracle、T12预算/协议全部执行 |
| 前端 | typecheck、lint、Vitest、build真实数量及退出；完整Playwright收集/执行数量、0retry/skip/flaky要求及数据库判据 |
| 安全 | 无Provider Key/真实模型，contents:read、固定Action SHA；实际Artifact只含有界状态摘要 |
| 失败 | 原日志SHA、失败阶段、退出/取消、超时/OOM、重试次数；不得预填C1的713/14、80、87为远程成绩 |

C1只提供本地Linux aarch64 + Mac Chromium参考，不能代替amd64。当前workflow只上传状态摘要，精确测试数量要从原job日志提取；没有记录的数据填UNKNOWN，不伪造。D2未经新批准不改获批workflow来加遥测。

## 失败与停止

如失败，分类为平台兼容、安装/依赖、真实代码缺陷、时序或资源不足，保留同一Run/Attempt，不新增skip/retry、不放宽JWT/价格/库存/Checkpoint Guard、不自行修复生产代码再Push。任何新代码修复需要新本地提交、针对性回归和独立上传授权。

远程成功之前保持REMOTE_CI_NOT_RUN或REMOTE_CI_FAILED；成功之后也只可标记该SHA的REMOTE_CI_VERIFIED。main合并、GitHub Release、录屏发布、部署、镜像/模型分发和真实LLM仍是不同授权，不自动执行。
