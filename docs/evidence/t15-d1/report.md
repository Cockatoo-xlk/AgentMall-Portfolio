# T15-D1 — 最终公开发布候选审查

**T15_D1_PUBLIC_RELEASE_CANDIDATE_READY**，仅为本地最终候选准入，不授予上传权限。本阶段只做内容整理、全历史审查和远程只读核验；本目录verification、暂存内容复核和提交后的独立完整清单共同确定交付身份。远程CI截至本阶段为 **REMOTE_CI_NOT_RUN**，当前源码新Live验收为 **NOT_RUN**。

## 基线与提交链

指定T15-C1工作树开始时干净，HEAD为`671ef7a4559ca19b8bc33c3cb6b9280fd0e3c219`。另建`codex/t15-d1-public-candidate`独立工作树，不改原Public main、Private、P0/P1/R1-A、T15-A和T15-C1文件。

GitHub CLI/API和保留TLS验证的`git ls-remote`交叉确认远程Public仓库`Cockatoo-xlk/AgentMall-Portfolio`的main仍为`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`。[网络及只读核验](ssl-and-remote.json)记录时间、证书身份和实际SHA；远程状态只代表该次观测，D2必须重新查询。

| 顺序 | 完整Commit | 内容 |
|---|---|---|
| 公开根 | `73872b6761dcd2e52344dd562bbdd8618fb4e83d` | 独立公开快照，无Private父链 |
| 已发布main | `17f72b8ccd6a86e083fd3206ea839dd28dc22bcf` | 公开作品文案 |
| P0 | `d8a18b0b56b0bdebe9a1ea1400849f82cecdbbef` | 模拟支付前端闭环 |
| P1 | `d81de4adc125c9ce019434fb338a52fe5282070c` | 购物车结算生命周期 |
| R1-A | `c06c5841af36a631b69462c035d6410f732af0db` | P0/P1公开候选整理 |
| T15-A | `617cdf29a4353673bbfe141d5c87eec1ce665ec3` | 受门禁保护的真实SDK Playground |
| T15-C | `1fb92b5bb0ecf23bfac71ecfb124eb8cab0a2a5f` | 交互、倒计时、历史B1摘要 |
| T15-C1 | `671ef7a4559ca19b8bc33c3cb6b9280fd0e3c219` | 独立稳定时钟环境完整验收 |
| T15-D1 | 本分支最终HEAD，完整40位SHA见Git记录及提交后本地交付回执 | 仅文档、忽略规则、脱敏审查材料 |

本轮不重写祖先、不创建新的根、不复制Private历史；上传方案仅允许未来获批的单一SHA/审核分支，不使用`--all`、`--mirror`、tags或force。

## 全历史与公开内容

[历史审查](history-audit.json)遍历全部8个祖先提交、**508个唯一Blob、2900个文件版本出现次数**，包含公开根，不只检查最终文件树。每个Blob的路径、大小、SHA-256及所属提交见[祖先Blob清单](ancestor-blob-inventory.json)。另扫描提交对象的身份和消息；均使用已批准的公开作者与GitHub noreply身份，没有替换引用或Private父链。

92项规则命中全部记录在[逐项分类](finding-adjudication.json)：20个DSN、68个凭据赋值/授权状态形状、1个“邮件”解析误报、3个`sk-`形状的显式合成脱敏阴性控制。检查了各自历史源码上下文，没有仅按“位于tests”就放行。未发现真实Key、JWT、Cookie、个人绝对路径、原始Live Ledger/授权/完整Checkpoint、未知二进制、模型权重或大于2MiB的Blob。

| 分类 | 本次处理 |
|---|---|
| SYNTHETIC_TEST_DATA | 明示合成的CI/例子DSN、Demo口令、动态Bearer前缀、无效DSN/假Key测试；不冒充生产凭据。 |
| REVIEWED_PUBLIC_EVIDENCE | 审阅后的历史JSON/Markdown、全部15张合成UI截图、有限B1摘要。 |
| PRIVATE_LOCAL_EVIDENCE | `.playground`、`.t15-c`、`.t15-c1`和本轮`.t15-d1`中的原始账本/授权/诊断/失败日志/临时签名材料；均不在可达文件树，不加入提交。 |
| SENSITIVE_OR_UNKNOWN | 在已扫描与逐项审查范围内无未解决项；若未来发现历史敏感Blob，必须停止，不能只删HEAD再声称安全。 |

普通源码与通用文档另标PUBLIC_SOURCE_OR_DOCUMENTATION，不伪装成测试数据或历史运行证据。规则扫描、结构核对和人工审阅的范围如上，不是对任意未知泄漏形式或生产安全的保证。[公开审计结论](publication-audit.json)保留方法和边界。

15张PNG各有唯一可达版本，包含R5三张、P0四张、P1三张Fixture及T15-A五张SDK MockTransport页面；全部核对PNG chunk和可见像素，无文本/EXIF附带数据、个人路径、真实身份、JWT或Key。没有新拍/加工图片，没有把MockTransport截图当Live截图。原P0截图购物车徽标属于修复前状态，保持历史身份。

## 许可与展示修订

MIT、Cockatoo-xlk版权与既有SOURCE_RIGHTS确认保持不变；Lucide ISC/Feather MIT完整通知及两份依赖锁均不变。修正第三方声明从历史10张到当前15张的数量，保留MPL/CC-BY/LGPL各自义务。范围只含源码、合成数据、文档、迁移、测试、锁、构建配方和已审截图；镜像层、dist、wheel、浏览器或模型另行审核。[许可及每张截图证据](license-and-images.json)。

README首页按技术栈、Single/Multi架构、Hybrid RAG/Tool Calling/HITL/Checkpoint、购物车与模拟支付闭环、模式身份和运行入口组织；历史内部审核详情移到结果/证据链接。COPYRIGHT/SNAPSHOT明确来源与阶段边界，不用“尚未建立Git根/尚未上传”描述未来状态。架构图标明Supervisor和三个Specialist，已有工程案例保持事实、来源和AI辅助范围。

[安全运行/恢复](../../REAL_AGENT_DEMO.md)、[3–5分钟录屏脚本](../../DEMO_RECORDING_SCRIPT.md)和[Demo](../../DEMO.md)继续要求新Live独立授权。**VIDEO_NOT_RECORDED**。T15-B1只属于旧617cdf29的单个真实Multi-Agent购物场景：7请求、50事件、本人确认、唯一PENDING_PAYMENT订单、付款0；平台账单UNKNOWN。本版不复用其许可或宣称新Live已通过。

## 测试复用与新检查

本轮产品源码、API、业务服务、Prompt、测试、锁文件和workflow均改动0，源码指纹仍为`7049db6ae8e334f82dc0b8de3083255e1c84a10ab4f3ec5e99b315fdf519a71a`。依用户允许，核对C1原日志SHA、JUnit和Playwright JSON后复用全量结果，**D1没有重新执行这些完整套件**。

| C1真实回归 | 已核对结果 | 原退出码 |
|---|---|---:|
| Backend CI_OFFLINE_CORE | 713 passed / 14 skipped / 0 failed | 0 |
| Vitest | 80 passed | 0 |
| 完整Playwright | 87 passed / 0 failed / 0 skipped / 0 flaky / 0 retries | 0 |
| Ruff、format、typecheck、lint、build | 通过 | 0 |

环境为独立Linux aarch64 VM + Mac完整Chromium headless，真实PostgreSQL17.11/pgvector0.8.7及官方Checkpointer。14项skip仅原13项BGE权重依赖和1项私有Live原件比较，逐项原因为[回执核对](test-evidence-reconciliation.json)中的原记录。

D1新执行actionlint、Ruff/format、Compose config、默认Playwright **87项/6文件收集**、两张Mermaid图的本机Chromium解析与渲染、文档链接/内容审查、源码指纹和原件哈希核对；实际命令/退出/日志SHA见[本轮回执](verification.json)。浏览器收集/图渲染不是新的完整业务E2E。

首次D1交付脚本先检查链接、后生成清单，因`payload-inventory.json`尚未产生而退出1。修正本轮私有工具的生成依赖顺序后，以新回执执行；仍检查全部链接，不忽略断链。原退出1和日志SHA保留，不影响或改动既有业务测试。

旧T15-C的81/6、旧环境5/1定向诊断、P1单容器OOM/143、T15-A OOM/137及旧P0进程退出UNKNOWN完整保留。旧共享VM约2.13秒回退未修复；一项JWT时钟因果在同用例复现确认，其余五项历史单请求原因仍未知。C1只给新独立稳定环境准入，不能把旧环境认证为安全。

## GitHub Actions与HTTPS

[CI静态契约](ci-readiness.json)：目标ubuntu-24.04，预期amd64/X64；固定Python3.12.10、uv0.9.18、Node24.21.0、npm锁、PG17/pgvector0.8.7固定Digest。bootstrap对新独占agentmall_test执行迁移/种子/官方Checkpointer核对；pytest包含原T09/T11/T12，不加skip。默认E2E使用loopback8001/5174和本Runner PG55433，1worker、0retry、不复用服务。Mac managed模式不是Hosted路径。

5个Action的完整SHA均通过官方仓库GET核对到注释标签；token权限contents:read，checkout不保留凭据，无真实DeepSeek Key注入。Artifact只上传不超过4096字节的白名单状态摘要，不上传失败日志、截图、Checkpoint或账本。30分钟Hosted任务的真实性能、资源及平台行为仍需远程验证；D1没有把ARM64成绩冒充amd64。

直接github.com返回Scholar自签名链，保持拒绝，没有信任新证书。现有系统loopback代理的CONNECT路径经默认CA/hostname独立验证为GitHub公开CA链；API也单独通过公开CA验证。只对一次命令设置proxy，未修改系统/Git全局配置；两种只读路径返回同一main。以后路由/证书/remote变化必须停止，不用SSL_NO_VERIFY。

## 清单、保护与下一阶段

公开[payload清单](payload-inventory.json)含本轮审查文档之外的全部分发文件、大小/SHA及内容树哈希，明确排除本目录以避免循环自哈希。**提交后的本地忽略目录完整清单**覆盖最终Git HEAD的每一个文件，包含本目录全部证据；附属回执提供最终40位Commit、完整父链及全树SHA。不能把payload子集哈希称为完整树哈希。算法：按相对路径排序，拼接UTF-8的`path + NUL + decimal_size + NUL + sha256 + LF`，再SHA-256。

[历史保护核对](historical-integrity.json)记录原件与旧工作树保护集合；所有历史失败、Frozen Manifest和Live账本不变，没有运行封存评测、读取真实Provider Key或新付费调用。D1没有启动业务容器或停止旧服务；图验证的本轮临时浏览器/localhost服务已回收。

[T15-D2具体方案](remote-ci-plan.md)只规划获批SHA推新审核分支及观察Push自动产生的CI，不执行。权利人需再次批准准确SHA、目标审核分支、Public上传和Actions；PR/合并main/Release/部署分别另批。D1结束后停止。
