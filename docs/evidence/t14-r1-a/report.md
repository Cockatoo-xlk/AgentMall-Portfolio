# T14-R1-A：P0/P1公开发布候选准备

状态：**PUBLIC_RELEASE_CANDIDATE_READY_FOR_OWNER_APPROVAL**。仅本地准备，没有GitHub写操作、远程Actions、Release、部署、付费模型或历史封存评测重跑。本结论是允许权利人审核候选，不是公开上传授权、远程CI通过或生产就绪声明。

## 候选及历史

独立目录名`AgentMall-T14-R1-A-Public-Candidate`，分支`codex/t14-r1-a-release-candidate`。原P0/P1目录、原Private、R5审核目录及已发布Public main保留。本地原生worktree工具因sourceRoot不属于聊天工作目录而拒绝；随后按本轮明确要求使用Git worktree建立隔离候选，没有改用Private进行开发。

只读远程准入确认`Cockatoo-xlk/AgentMall-Portfolio`是Public、默认分支main，远程main为`17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`。本地明确线性祖先：

1. `73872b6761dcd2e52344dd562bbdd8618fb4e83d` 独立公开根。
2. `17f72b8ccd6a86e083fd3206ea839dd28dc22bcf` 既有公开文档提交。
3. `d8a18b0b56b0bdebe9a1ea1400849f82cecdbbef` P0模拟付款闭环。
4. `d81de4adc125c9ce019434fb338a52fe5282070c` P1购物车生命周期。
5. 包含本报告的必要文档/审核提交；最终SHA、Git tree ID、全文件清单/字节数及完整内容树SHA由提交后的**本地外置回执**标识，交付回复提供其绝对路径，避免哈希自引用。

本轮产品代码、测试、依赖锁、CI工作流、迁移、Frozen Manifest、任务及Oracle均与P1一致。只修订README、COPYRIGHT、THIRD_PARTY_NOTICES及SNAPSHOT的当前/历史阶段表述，增加本审核目录。所有P0/P1旧版本和失败保留，没有历史重写、删除提交或仅从HEAD移除秘密的操作。

## 内容、隐私与许可

[git-history-audit.json](git-history-audit.json)审查P0/P1涉及的70个路径及100个不同文件版本，包含公开main的前像；另扫描P1可达的全部382个blob和四个提交的作者/提交者身份。范围是拟发布祖先链，不把无关ref或reflog对象当成上传内容。

未发现真实Key/Token、个人Mac路径、个人工作邮箱、原始Live Ledger/授权/Episode、完整模型对话、私有Checkpoint序列化或模型权重。首次模式扫描有一项把旧测试中的合成DSN主机反例识别成邮箱，按确切blob/行和源码上下文分类SYNTHETIC_TEST_DATA；另一邮箱为权利人已批准公开的GitHub noreply身份。没有通过删除历史或全面忽略邮箱规则使结果通过。其余静态扫描配合源码、JSON字段及图像人工检查，不能被解释为数学上的秘密不存在证明。

[screenshot-audit.json](screenshot-audit.json)记录七张新增PNG，逐张视觉复查，只有合成商品、随机测试订单/动作ID及演示地址标签，没有文本/EXIF元数据、真实身份/地址、JWT或设备标识。P0四张是P1修复前的历史证据；旧购物车徽标不代表当前P1行为，原图/哈希不改写。

[license-privacy-review.json](license-privacy-review.json)区分：

- **SYNTHETIC_TEST_DATA**：明确公开的buyer/merchant演示账号、模拟支付、一次性CI/Compose数据库与JWT值、测试控制标签、合成数据库终态。
- **REVIEWED_PUBLIC_EVIDENCE**：白名单事实、命令/日志哈希、已审PNG和本地核验摘要。
- **PRIVATE_LOCAL_EVIDENCE**：原Private Live资产及本轮忽略的`.t13/t14-r1-a`原始日志、工具、依赖缓存、工作基线；不进入Git树。
- **SENSITIVE_OR_UNKNOWN**：拟上传内容中无未解决项。Private内部ref历史摘要差异另行如实披露，不输出其内部UUID或原始元数据。

MIT、Cockatoo-xlk版权和已确认noreply作者身份保留；SOURCE_RIGHTS沿用权利人的明确确认，不推断新许可。项目MIT不覆盖Lucide/Feather ISC/MIT、Lightning CSS MPL、caniuse-lite CC-BY及Psycopg LGPL。现分发仅源码/合成数据/文档和10张已审截图（历史3、P0四、P1三）；完整图标许可和署名不变，未新增依赖或第三方图片。安装目录、dist、wheel、浏览器、审计工具、模型和Docker镜像不进入提交；以后分发二进制/镜像/权重须分别审查，不冒称本次已完成。

测试控制入口只有`backend/tests/web_e2e_server.py`注册，普通`create_app`不挂载；有loopback中间件、host校验、公开测试标签及独占agentmall_test/test_/cp_保护。公开标签和合成口令不构成生产安全措施，不能暴露该测试入口到公网；README明确这一边界。模型环境键名过滤和外网transport/socket阻断保留，Fixture不冒充DeepSeek。

## 测试证据对应

[test-evidence-reconciliation.json](test-evidence-reconciliation.json)重新核对P0的42条原命令日志、9个CI步骤及210个旧执行文件；P1的70条命令日志、8个后端/静态步骤、最终前端/浏览器原始回执和结果JSON哈希。231个原执行源码/后端测试/锁文件匹配；最终配置/驱动文件哈希和四份origin逆替换证明匹配；当前278个运行与CI文件完全等于P1。README的明确授权修改独立列为文档差异，不错误要求新README等于旧源码快照。

| 检查 | P1最终实测，本轮核验哈希复用 | 本轮实际执行 |
|---|---|---|
| 后端离线全量 | **670 passed /14 skipped**；本地Linux ARM64、真实PG17.11/pgvector0.8.7/Checkpoint | 不重跑数据库套件 |
| Vitest | **65 passed** | 新候选再次65 passed |
| Playwright | **74 passed**；Mac完整Chromium headless+容器服务，1 worker/0 retries | `--list`收集74项/4文件，**未重新执行浏览器场景** |
| Ruff/format/typecheck/lint/build | 全部0 | 新候选全部0 |
| CI语法与启动配置 | 原工作流保留 | Actionlint、YAML及默认/managed/非法端口合同检查0 |
| Compose / Git diff / 文档链接 | 相同安全边界 | config及diff检查0；链接和最终树检查见[verification](verification.json)及[文档检查](documentation-check.json) |

14项skip没有增加：13个真实BGE权重依赖及1个私有Live原件比较。T09恢复/SIGKILL、T10 Trace、T11真实数据库并发/Oracle、T12预算/权限/协议仍在原670项中，没有降低断言、增加retry或修改安全Guard。

P1单容器一体化CI因约1.91GiB、无swap的Docker引擎OOM退出**143**，该失败和后续独立浏览器容器中断保留；不能称其为整套单容器CI成功。P1最终检查集合分阶段通过，本轮按明确要求复用，未重复已知OOM方案。当前候选未执行新的Ubuntu amd64远程CI，旧Public/Private CI回执不能替代它。付费请求0、Live Pilot/封存评测重跑0。

## GitHub Actions准入分析

[ci-readiness.json](ci-readiness.json)结论为**STATIC_COMPATIBLE_REMOTE_CI_NOT_RUN**，未发现需要更改产品或CI的确定缺陷。默认配置仍是8001/5174上的Python/Vite两个本地服务、真实PG服务的127.0.0.1:55433，未设置managed标志，不会调用P1专属Docker项目、端口或内存限制。Mac managed模式独立使用完整Chromium headless，只作为本地资源分离入口。

Ubuntu24.04目标为x64/amd64，Python3.12.10、uv0.9.18、Node24.21.0、锁文件及固定PG17/pgvector镜像保留，Alembic/seed/官方Checkpoint预检不变。4个Action完整SHA固定，token只有contents:read；无Provider Secret，安装不含BGE extras。Artifact只上传小于4096字节的状态枚举摘要，不上传Trace、环境、原日志、截图或数据库。

依据[GitHub runner说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)的Public Ubuntu资源与[Playwright浏览器说明](https://playwright.dev/docs/browsers)区分本机资源故障和默认CI启动路径；实际硬件、依赖安装及测试成功仍必须由将来的远程Run日志验证。不得把静态可兼容推断写成远程实测。所有失败和Attempt须保留，不能重复运行只选择绿色。

## 保护与保留限制

[historical-integrity.json](historical-integrity.json)核对Private2074、Public297、P0321、P1346个跟踪文件，合计3038；另核对R5审核297文件树仍为`8da9a5c18674520dab92195c279a5faf86c7f710fafe7575697ee0309e687508`，203/1479/1595保护集合不变。原目录HEAD、配置、工作区及Private可达对象集合和索引匹配；本轮没有启动数据库、容器或测试服务。

不能声称整个Private `.git`逐字节不变：与更早P1开工基线相比，完整raw refs摘要不同。当前有两个mtime晚于P1开工、早于本轮基线的Codex内部ref文件；普通loose/packed ref文件mtime均早于P1基线，当前普通refs在本轮观察期间保持稳定。旧基线仅留摘要，无法重建完整文本差异或独立确认写入者（UNKNOWN）。没有删除/重写这些ref来让核验通过。该限制与当前源码、HEAD、可达对象集合和发布候选线性祖先的核对分开记录，不是对原工程历史重写的豁免。

旧P0 demo runner缺失原因继续**UNKNOWN**，用户已确认未手动关闭；没有向其发送停止/重启命令，也不推断共享引擎完全无影响。四个原PG容器ID、启动时间、挂载和端口仍匹配P1保护记录；本轮不重启或清理它们。P1早期21样本资源文件被helper覆盖的事实保留，不声称找回全部原始样本。

两轮DeepSeek使用相同开发任务集，Single1/5→5/5、Multi4/5→4/5，第二轮Multi B2仍失败/PARTIAL；中断和失败保留，平台真实账单UNKNOWN，原40题不是独立Holdout。没有第三次修复复测或新的Live授权。任意SIGKILL下外部模型调用exactly-once、生产负载/安全/SLA、真实资金、云部署均未验收，VIDEO_NOT_RECORDED。

## 文件清单与后续授权

[payload-inventory.json](payload-inventory.json)逐项标识除本轮审核目录外的全部候选公共文件及内容树SHA。全树（包含本轮审核材料）的文件数、字节数、内容树SHA与Git SHA，保存在候选本地忽略目录的提交后回执；文件选择严格基于Git提交树，不包含`.git`、忽略文件或整个开发目录。该做法避免在被哈希文件中写自己的哈希。

[publication-plan.md](publication-plan.md)列出R1-B所需的准确Owner/Repo、最终SHA、main目标、普通fast-forward Push及自动Actions授权。**当前没有任何上传授权。** 权利人明确批准最终SHA后，仍需重新只读核验远程main、干净工作区和文件哈希；变化则停止，不Force Push、不自动换SHA。完成本地交付后停止。
