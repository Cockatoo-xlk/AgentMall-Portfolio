# V2.15 RC1 本地工程审核与远程交接

此文件只记录RC1本地验收快照；GitHub Push、PR和自动CI必须分别取得Owner授权并核对准确SHA及Run。本地成功不是发布、合并或真实Provider授权。正式main基线71970c88d8827d22cd5626de20317a89d389bafc，初始候选f017880dec3b644b133a6adbae114c63ea0cf589。V2.14 Release仍ON_HOLD，RELEASE_COMMIT=UNBOUND。

## 审查发现与最小修复

| 问题 | 修复与回归 |
|---|---|
| 历史商品描述遮住当前退货/人工服务撤销 | 保留转述、第三方与历史动作排除，同时允许指向过去业务对象的当前否定撤销权限；不按Task ID或商品名列举答案 |
| 小数、符号、分数、指数被截成合法数量后缀 | 整体识别不支持的数值表达，要求澄清，不擅自换成整数；有效整数量词保持 |
| 取消比较但继续推荐时旧比较条件残留 | Thread与legacy同Run共用comparison_revoked，只撤销比较，保留推荐数量及当前连接要求 |
| Supervisor解析失败后同一Resume再次消耗模型预算 | 仅MODEL_RESPONSE_INVALID沿原节点Journal/Fence/Checkpoint正常终结为PARTIAL；重放只读返回，原Case与Confirmation消费不丢失 |
| SDK在_create_chat_result之前解码非法HTTP JSON | 只识别SDK附带成功HTTP响应的JSONDecodeError；保留UNKNOWN哈希/用量与预算预留，不误分类HTTP503或传输错误 |

以上均有失败复现和修复后回归。没有扩大角色权限、改变工具Schema、业务状态机、预算、独立HITL、交易、原Oracle、任务输入或Prompt。

## 真实BGE与测试适配器

固定BAAI/bge-small-zh-v1.5，Revision7999e1d3359715c523056ef9478215996d62a620。现有六文件SHA及大小逐一匹配，权重只读挂载，CPU512维L2归一化通过，未下载权重或替代模型。真实BGE不等于真实LLM：所有Provider响应仍为MockTransport/Fixture。

原13项BGE测试首次定向执行9通过4失败。3项因旧测试wire误要求完整角色工具集合，拒绝了当前合法的按goal收窄工具；1项在原Oracle已通过后错误要求冗余模型HTTP回合。仅修测试适配器：严格逐goal工具集合与18项允许/拒绝合同；逐工具调用ID核验持久化成功事件，无额外HTTP时还要求唯一read_goal_completed回执。没有降低原Oracle、SQL、不变量、真实BGE或Checkpoint断言。最终13项全部通过，0跳过。

完整测试结果、实际命令/退出码/耗时/日志SHA及源文件绑定见[verification.json](evidence/v215-rc1/verification.json)。

| 本地检查 | 实际结果 |
|---|---|
| 独立CI_OFFLINE_CORE完整后端 | **1591 passed / 14 skipped / 0 failed / 0 errors / 3 warnings**；pytest668.11秒，命令673.09秒 |
| 真实BGE专项 | **13 passed / 0 skipped / 0 failed / 3 warnings**；15.22秒 |
| Vitest / TypeScript / ESLint / build | **132 passed**；其余全部通过 |
| 完整Playwright | **119 passed / 0 failed / 0 skipped / 0 retries**；230.16秒 |
| Ruff / format | 全部通过 |
| 真实Provider / 真实Key / 本轮费用 | **0 / 0 / CNY0** |

3条warnings来自既有jieba依赖的转义写法，未抑制。核心配置的13个BGE skip与专项13个实际通过分别记录，不能把两种环境合并为一次未执行的LOCAL_FULL结果；另1项私有原件测试保持skip。

## 运行环境与中间结果

Linux aarch64/Python3.12.10，PG17.11/pgvector0.8.7，独占新资源。真实BGE环境Torch2.9.1/Transformers4.57.6；核心环境另建，不安装Torch/Transformers，不能用前者替代轻量CI兼容证据。无外部网络路由、无Docker Socket、非root501:20、rootfs只读。依赖仅从现有镜像离线复制；公共依赖版本一致，模型下载0。

中间失败全部保留：BGE全目录收集因旧镜像缺mcp而中断；已在本轮专属Volume从现有核心镜像补齐缺包，未改锁文件。环境引导发现旧的本地测试.env.rag时安全拒绝覆盖，保留原件后为新PG单独初始化；专属Volume初始化的权限错误使用实际Owner UID解决，没有放宽Guest权限。格式检查发现2文件后按既有格式修正。所有这些日志不作为最终成功结果。

## L8历史与发布边界

原L8保持PASS1、FAIL4、NOT_SCORED3、NOT_RUN7；只有5题原Oracle评分，1/5=20%，Wilson95%为3.62%–62.45%。08仍INSUFFICIENT_EVIDENCE，Ledger与实际费用UNKNOWN；新诊断不补写历史用量、不释放旧预留。本轮没有重跑历史01—08或使用未运行09—15调试。

E1 ORACLE_CONTRACT_MISMATCH、独立Holdout=0、L7 B2 PARTIAL/CONTEXT_SCOPE_VIOLATION继续保留。当前没有真实DeepSeek复测，不代表生产可靠性或真实模型验收；没有真实付款、退款、部署或SLA认证。REMOTE_AUTH_NOT_IMPLEMENTED、VIDEO_NOT_RECORDED、Release ON_HOLD保持。

## GitHub阶段准入

Owner须针对最终候选SHA单独授权一次普通非强制Push；只读观察该Push自动CI。失败/UNKNOWN不自动追加Push，不Dispatch/Rerun。仅当准确SHA的Backend、Frontend及Release Gate全部成功且无意外跳过时，才在明确授权范围内创建一个PR；PR触发的CI与Push CI分别核验。预期T16 Admission skipped不算失败。禁止自动Merge、Tag、Release或部署。

本轮证据封存校验后，仅清理明确Owner的3个新测试容器和5个Volume，并核验不存在；旧L8资源、模型及依赖镜像未操作。原本地测试配置逐字节恢复，见[资源处理回执](evidence/v215-rc1/resource-handling.json)。
