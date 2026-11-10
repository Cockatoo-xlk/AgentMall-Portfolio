# V2.14-R4：合并后发布文档与main CI核验

状态：**AGENTMALL_V214_R4_RELEASE_DOCS_READY**。产品V2.14已合并main，且main CI已成功；本轮文档尚未Push/PR/合并，正式Tag和GitHub Release尚未创建。准确本地文档Commit由 `git log -1 --format=%H -- docs/evidence/v214-r4/verification.json` 定位，避免在记录中自引用提交SHA。

## 产品、提交与保护

- 仓库Cockatoo-xlk/AgentMall-Portfolio，main **`59f84ebbfdfb1d87287ad6c4ae83a1748183d30c`**。
- [PR #2](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/pull/2)合并于2026-11-10 06:39:56 UTC；parent为旧main17f72b8与候选900bf3d。
- Merge Commit与审核候选`900bf3dda50eec4d2d9583f46001991ac39fb707`代码树均为 **`cd817c61858095f7d57baa0abf619baf88f4ec88`**。真实L7产品代码未因发布收尾改变。
- 旧PR #1随后在06:39:58被GitHub标记Merged，其head bd0f583原已包含于PR #2；这是已包含提交进入main后的自动状态处理，**不是又一次人工合并操作**。R4没有操作任何PR。
- 只读GET200核对main已保护：Require PR、Backend/Frontend/Gate三项检查、审批0、禁止强推/删除。当前strict up-to-date=false，按实际记录；没有把R3的建议当成已启用配置，本轮未修改Settings。

## 最终main CI：独立于PR CI

[Run42770031624 / Attempt1](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/42770031624)为 **push / main / head59f84ebb / completed / success**，不是用旧PR成绩推断。

| 实际main Job | ID | 核验 |
|---|---:|---|
| Backend | 129675413979 | success；pytest **1291 passed /14 skipped**，3warnings，引擎1250.17秒 |
| Frontend | 129675414218 | success；Vitest **127 passed**、Playwright **119 passed /0 retries** |
| Release Gate | 129683041288 | success；日志有RELEASE_GATE_PASSED |
| T16专用Admission | 129675415086 | 非专用branch/非dispatch，预期skipped，不是必需Job缺失 |

所有必需安装、初始化、Ruff、format、TypeScript、ESLint、build和测试步骤success。原14项skip未增加：13项真实BGE权重依赖，1项私有Live原件比较。普通CI使用SDK MockTransport/Fixture，不是加载真实BGE或真实DeepSeek的验收。日志中故障注入异常不能直接当作断言失败；实际测试footer无failed，必需Job无取消或异常skip。

下表三个ZIP均重新独立读取、按服务器size/digest校验，只接受唯一的白名单JSON、不解压任意路径；JSON小于4096字节，准确绑定Merge SHA、Run、Attempt1、固定字段和成功outcome。Gate最终Job/日志另行核验，不以“上传成功”代替CI通过。每份解码日志和JSON原件的SHA见[机器回执](verification.json)，解码日志SHA不是服务器ZIP digest。

| 阶段 | Artifact ID | ZIP字节 | ZIP SHA256 |
|---|---:|---:|---|
| backend | 13742312421 | 469 | `5ba308e1e6b1c384a7606a62c509d7c5f62c1399a0b1121162f4a5b35670ec96` |
| frontend | 13742125962 | 507 | `5b5a1fcf79bd583e80f70774d0cc9cf6c7ffa00e41edaf8155e54288b1ecc713` |
| gate | 13741929111 | 420 | `c07a8f21cd899dbe7d5082b4a929ed65394ac0196b525ba5e12cf4ecb380c9f7` |

首个二进制GET因HTTPError失败、0字节，原状态码未单独保存，保持UNKNOWN；同一引用后续HEAD诊断为403，签名se时限已过，诊断与失败回执均保留，未进入解包。重新取得有效引用，在独立attempt2目录完成三份下载与SHA核验。未降低校验，也未把空文件、旧PR Artifact或summary自身当成main成功证明。

## 文档收敛

README已移除把R2本地候选/首次cancelled当作“最新状态”的首屏，改为已合并产品与最终main CI；仍区分本轮待合并文档、未创建Tag/Release、无生产部署和真实B2失败。

RESULTS、V214_RELEASE_CANDIDATE、RELEASE_CHECKLIST、ARCHITECTURE、PORTFOLIO_DEMO、PORTFOLIO_INTERVIEW仅追加当前状态，六份历史正文原字节保留为后缀。所有旧验收JSON/Manifest、L7失败、首次超时、R2及Push/PR成功记录均未覆盖。

新增[Release Notes草稿](../../RELEASE_NOTES_v2.14.0.md)、[一页介绍](../../PORTFOLIO_ONE_PAGE.md)、[中英文项目描述及口播](../../RESUME_PROJECT_BLURB.md)。不杜撰用户规模、公司经历、独立个人贡献、生产SLA、QPS或模型可靠性。

## 本轮执行范围与验证

- 本轮是文档任务，**没有重新执行1291项pytest或119项Playwright**；所有测试数量来自准确main CI的新下载原件。
- 实际运行Markdown路径/锚点检查、JSON解析、引用SHA/时间线/保护/Tag事实核对、新文件秘密模式检查、Git Diff与暂存范围检查。实际检查11份Markdown的219个文档目标与13个锚点，缺失0；JSON/引用SHA、facts、Diff和公开内容扫描通过。独立复核Critical/Important/Minor均0；最终Commit与CLEAN由执行者在提交后再核对。退出码及原件SHA见verification.json。
- 两张Mermaid架构图使用可信缓存Mermaid11.12.0和真实headless Chromium重新渲染为SVG，退出0；临时容器只读根文件系统、无网络、只挂载图和vendor，--rm后owner查无。不操作任何历史容器/Volume。
- Quick Start沿用同产品源码的MockTransport/Fixture脚本；静态Compose和入口/命令检查，不启动Live、不读取Key。R4没有重跑冷机器构建、完整浏览器Demo或录屏；**VIDEO_NOT_RECORDED**。
- 用户明确要求新worktree，原生工具因当前聊天sourceRoot范围拒绝；核对SSH主机pin后只读fetch准确Merge对象，用git创建独立分支`codex/v214-r4-postmerge-release`。原审核分支HEAD900bf3d及其工作区未改变，本地旧main未被reset或强制同步。

## 真实模型与发布边界

V2.12历史五题配对开发集9/10仅绑定b5d6a685（Single5/5、Multi4/5）；L6 10–11调用完成路径是MockTransport；L7同当前产品源码仍 **PARTIAL / CONTEXT_SCOPE_VIOLATION，未完成第二次购买确认**。不合并为当前成功率。V2.10真实检索仅固定40条合成查询、本地aarch64 CPU；main离线CI成功不能推导真实LLM生产可靠性。

本轮新增Provider请求和Key读取均0；无真实资金、无部署，MCP REMOTE_AUTH_NOT_IMPLEMENTED、Worker非通用Exactly-Once等限制继续保留。

## Tag/Release及许可

只读查询时Tag列表、Release列表均空，`v2.14.0`未发现冲突；这不是永久保留名称。当前未配置可用签名身份，不访问签名私钥。未来先审核本轮文档Commit、新PR和合并后main CI，再冻结 **RELEASE_COMMIT**；另行批准注释或已核验签名Tag和GitHub Release，不现在对旧59f84ebb打Tag。[完整步骤](../../RELEASE_CHECKLIST.md#正式tag与release流程尚未授权执行)。

本轮无新图片、第三方代码或依赖；MIT/Cockatoo-xlk和既有第三方许可保持。只分发源码、文档、经审查的合成截图和脱敏摘要，不分发模型权重/依赖二进制/镜像。本轮扫描增量并绑定既有可达历史审查，不把无模式命中称为绝对无泄漏。

**NO_PUSH / NO_PR / NO_MERGE / NO_SETTINGS_CHANGE / NO_TAG / NO_RELEASE / NO_DISPATCH / NO_RERUN / NO_LIVE_REQUESTS / NO_KEY_READ / NO_DEPLOY**。仅创建一笔本地文档Commit，工作区CLEAN后停止，等待所有者对文档PR和正式版本发布的独立授权。
