# T15-C1 — Clock Diagnosis & E2E Release Unblock

**T15_C_LOCAL_RELEASE_GATE_PASSED**，范围是**未变更的生产源码在新建独立、通过时钟准入的Linux环境中的本地验收**。不是修复或重新认证原共享VM，也不是GitHub CI、新Live或生产验证。

## 基线与改动

开始核验HEAD `1fb92b5bb0ecf23bfac71ecfb124eb8cab0a2a5f`、工作区干净；分支 `codex/t15-c1-clock-diagnosis`，工作目录仍为指定的T15-C独立工作树。

本轮生产代码、既有测试、断言、skip、retry、安全验证均修改0。生产源码指纹仍为 `7049db6ae8e334f82dc0b8de3083255e1c84a10ab4f3ec5e99b315fdf519a71a`，宿主describe与实际独立后端镜像/挂载源一致。修改限于忽略新私有诊断目录、结果/发布说明及本轮脱敏证据；完整诊断代码和原日志留在Git/Docker构建忽略的`.t15-c1`。

## 六项历史失败，分别归因

[逐项原始字段/数据库状态/时钟关联及复测结果](six-case-attribution.json)明确区分原T15-C记录、C1复现和新环境完整复测。原日志未保存JWT iat/nbf/exp及精确验证时间，**这些旧字段全部保留NOT_RECORDED，绝不追补**。

| 原用例 | 原HTTP/错误证据 | 原业务终态 | 归因与本轮证据 |
|---|---|---|---|
| cart checkout: failed cart refresh keeps order success and unknown quantity until GET recovery | 原响应未录，页面认证失效；C1同用例实测GET cart=401、ImmatureSignatureError | orders/proposals/confirmations均0；购物车仍有1件 | **JWT时钟异常，同用例自然复现确认**；不是原失败逐请求时间已补齐 |
| playground: mobile SDK return and replacement keep two independent confirmations | 原select超时，页面认证失效；没有原JWT异常类型 | 合法准备订单1、支付1、Case0、Thread/Checkpoint0 | **原因未确定**；认证路径有线索，无浏览器驱动或业务回归的确定证据 |
| playground: model cannot invent missing user quantity to create checkout | **500 INTERNAL_ERROR**响应及服务端**PRICE_EXPIRED**堆栈 | orders/proposals/confirmations均0 | **原因未确定**；是价格门禁初始化错误，不能称JWT错误；原价格年龄未记录 |
| return_replace: refresh requires login and rebuilds known Thread from seq zero | 订单组件不可见，页面认证失效，原响应未录 | **订单1、Confirmation1、Run COMPLETED**、reserved1 | **原因未确定**；业务实际完成，不能把展示失败写成业务失败 |
| return_replace: unsubmitted Resume retry retains request ID after reads | select超时/DOM detached，页面认证失效 | orders/proposals/confirmations/Checkpoint均0 | **原因未确定**；尚未进入被测Resume路径，不能据此判定恢复内核缺陷 |
| return_replace: two clarification interrupts use distinct requests and new input | 第二输入未出现，页面认证失效，原响应未录 | orders/proposals/confirmations均0；Run WAITING_INPUT、Checkpoint5 | **原因未确定**；原单请求验证证据不足 |

原6个失败区间分别可对应1/3/1/1/3/1条既有Colima host-agent时间回拨消息，但时间区间相关性不是逐请求因果证明。

原环境初次定向诊断6项恰好通过，且观察器只装在桥接父进程、未进入API子进程，属于观测工具准备失败，**没有据此准入旧环境**。修正仅在独立测试进程中的观测器后，定向诊断5通过/1失败：第一项JWT在iat校验被拒绝。原方法始终执行、返回或抛出不变，leeway=0，没有放宽验证。

该次实测签发iat `1793539662.037904`，编码后iat `1793539662`，验证器实际now `1793539660.596954`，相差约1.403秒；单调时钟正常前进，墙钟后退。对应HTTP401被记录。其余5项该次未复现，保持未知；**没有把全部失败统一归到环境**。

## 同步墙钟/单调时钟诊断

[诊断摘要及原数据SHA](clock-diagnosis.json)保存每个进程的Python/OS/kernel/架构/CPU affinity、time/monotonic时钟信息、初末wall-minus-mono、逐样本增量、偏移PING区间和异常事件。原始JSONL按原样保留，仅数值/进程环境，不含JWT、Key、Cookie、用户身份或原始对话。

准入阈值在观测前冻结：单次墙钟后退超过1ms、单调时钟倒退、wall/mono残差超过100ms或可用PING偏移中值变化超过100ms均不准入；不根据结果修改阈值。

| 环境/窗口 | 容器样本 | 墙钟最小增量 | 重大异常 | 宿主-容器偏移变化 |
|---|---:|---:|---:|---:|
| 原共享VM，60.75秒 | 5155 | **-2.130516138秒** | **12** | **2141.90ms** |
| 新独立VM准入，60.65秒 | 5075 | +10.148ms | 0 | 1.224ms |
| 新独立VM持续监测，600.59秒 | 52830 | +10.047ms | 0 | 11.815ms |
| 覆盖完整E2E及结束后的486.45秒窗口 | 42490 | +10.050ms | 0 | 8.638ms |

各窗口同步Mac宿主记录均无重大异常。旧VM的wall-minus-mono发生阶跃，monotonic仍前进，既有host-agent日志记录周期性约2.1秒guest时钟校正。**旧VM为何持续漂移未被修复**，它仍排除于可信验收环境之外；没有改其时间同步设置或重启共享引擎。

新VM启动时一次-113ms初始化校正在准入之前；所有准入和持续测试窗口均无重大异常。最终完整87项测试位于连续监测窗口内，前后均有数据覆盖，不仅测一个短暂“好时刻”。

## 独立环境与实际回归

通过现有Colima0.10.3新建专属`agentmall-t15-c1` VZ Linux aarch64实例，2vCPU/4GiB/12GiB磁盘。`--activate=false --template=false --ssh-config=false --ssh-agent=false`，只挂载本项目；原`colima` Docker context保持当前值，原17容器未停或改动。没有安装系统服务、修改主机时钟或全局同步配置。

原已锁定Backend镜像与PG镜像通过本机Docker save/load复制到新engine，无镜像上传。新Compose项目`agentmall-t15-c1-independent`：PG17.11/pgvector0.8.7、受保护内部127.0.0.1:55433、真实test_/cp_及官方Checkpointer；runner1536MiB、PG384MiB。Mac宿主运行锁定Node24.21.0/npm11.19.0及完整Chromium headless。

首次浏览器准备在用例执行前因宿主8021被占用而失败。socket.bind实际返回EADDRINUSE；未停止未知监听者，改用本轮专属127.0.0.1:8022→新VM8021的本地SSH转发，前端5191。另一次独立协议准备脚本缺失Settings必填字段，仍在全局准备阶段中止；修正工具后才首次真正执行87项。

| 项目 | 实测 | 退出码 |
|---|---|---:|
| 新独立环境完整Backend CI_OFFLINE_CORE | **713 passed / 14 skipped**，727 collected | 0 |
| Ruff check / format | 通过 | 0 |
| Vitest | **80 passed** | 0 |
| typecheck / lint / build | 通过 | 0 |
| 新独立环境完整Playwright | **87 passed / 0 failed / 0 skipped / 0 flaky**，1worker，retries0 | **0** |
| 原六个失败用例 | 全部包含在该次完整运行且各执行1次通过 | 0 |
| 新倒计时用例 | 3/3，包含于87项 | 0 |

[命令、耗时、退出及日志SHA](command-receipts.json)保留全部准备失败、旧环境诊断和新环境结果。旧环境6项“恰好绿色”及5/1诊断均不是发布成绩；新稳定环境只有一次完整用例执行，没有使用`--last-failed`或新增retry/skip/force click，也没有修改原断言。原14项skip仍只对应13项BGE权重依赖和1项私有Live原件比较。

## Date、倒计时与JWT契约

[单独协议检查](security-and-time-contract.json)在完整套件前于该专属测试API执行，数量不计入87。有效JWT访问本人信息=200；正确签名但未来iat、未来nbf、过期exp均=401 UNAUTHORIZED，原验证未改。只保存数字声明和客户端前后时间界限，不保存Token/签名/密钥。

正常提案Date为 `Sun, 01 Nov 2026 13:40:41 GMT`，高精度X-Server-Time为 `2026-11-01T13:40:42.843390+00:00`，剩余299.990977秒；Date存在秒粒度和服务端缓存，差1.84339秒，处于预设2秒范围，不用它授权。倒计时使用精确数据库X-Server-Time及单调增量。提案JSON/哈希不变；独立的过期合成快照GET=EXPIRED、X-Server-Time晚于期限，批准=409，订单/确认/付款均0。

Fixture身份来自认证runtime，模型真实请求0；完整测试保留MockTransport明确标记、人工确认、支付/购物车/恢复/Checkpoint及数据库Oracle。没有为处理时钟异常删除iat/nbf/exp校验或放宽价格有效期。

## 证据保护、隐私与清理

原T15-C的1578个私有证据文件逐一哈希保持不变，原报告和81/6失败不覆盖。更早B1/预算/授权/Manifest及原工作区保护集合继续核对；本轮不读取真实Provider Key或执行真实LLM。B1只能描述旧617cdf29的历史单场景，当前源Live=NOT_RUN。远程CI=NOT_RUN，不Push、不部署、不触发Actions。

诊断工具的一次准备错误使Pydantic在私有失败日志中显示了**本轮新生成的临时合成JWT签名串的截断片段**，不是任何真实Key或JWT。该容器已销毁且不复用该串；原失败日志0600、Git/Docker上下文忽略，未复制到公开摘要。工具改为只读取非秘密issuer/audience默认字段后，不再序列化含签名参数的配置异常。此准备问题与全部失败均未隐瞒。

两套本轮数据库结束时test_/cp_ schema、应用会话、Advisory Lock均0。仅关闭本轮Compose项目、取消自己添加的8022转发、停止自己创建的VM，保留磁盘和日志，不删除Volume。原共享引擎与17个旧容器保持运行/原状态，原context不变。

原始JSONL、原HTTP观测、原Playwright JSON/JUnit/失败截图及日志留在`.t15-c1`；本地原件哈希清单以最终交付的私有raw-inventory.json为准，其中路径相对于`.t15-c1`，不将这些原件加入Git。公开摘要省略个人路径/完整Checkpoint/账本/密钥。精确本地Commit由交付消息和本分支Git记录提供。

## 后续边界

本地发布阻塞已通过**切换到真实验证过的隔离环境**解除；旧共享VM仍不可信，不能直接在那里重启新Live或据一次绿色诊断宣布已修复。新运行应重新做时钟准入。GitHub上传及Actions仍需用户对准确新SHA单独授权；本轮不进入发布或真实模型实验。
