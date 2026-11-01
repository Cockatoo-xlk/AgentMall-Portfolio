# T15-C — Real Agent Demo & Release Readiness

**IMPLEMENTED，发布准入 BLOCKED_ENVIRONMENT_CLOCK。** 本地源码、脱敏B1摘要、手册和审核材料已完成；完整浏览器回归81通过/6失败，不能标记整套回归通过或发布候选已验收。真实Key读取0、新付费请求0、Push/部署/远程Actions0。

## 版本及边界

基线 `617cdf29a4353673bbfe141d5c87eec1ce665ec3`，独立分支 `codex/t15-c-demo-release`，独立工作区名 `AgentMall-T15-C-Demo-Release`。内置worktree工具不接受当前聊天挂载以外的sourceRoot，故按用户授权使用本地Git worktree；没有在原T15-A、T14、Public main或Private源码上实施。

本轮源码指纹 `7049db6ae8e334f82dc0b8de3083255e1c84a10ab4f3ec5e99b315fdf519a71a`，宿主describe与实际后端测试容器一致。历史B1指纹为 `ee0f6927f30687892159b39272148e8859fe61f406a0e5aa7c48cb5766766687`。**当前源码LIVE_VERIFIED=NOT_RUN**，不能将旧B1结果转移到新指纹。没有改写Manifest/历史授权或清空账本。准确本地提交见交付消息和本分支Git记录；本报告不自引用自身提交SHA。

## 实现

- 认证 `GET /api/v1/proposals/{id}` 添加 `X-Server-Time` 响应头，来自PostgreSQL `clock_timestamp()`。ApiClient只将该GET头投影成前端展示字段server_time；后端ProposalDTO、不可变快照/哈希、领域服务及POST/重放响应JSON均保持原样。
- 购买/退货确认卡以服务端时间与浏览器单调时间显示估计倒计时；浏览器日历时钟偏移不授权。到零暂停新确认，最多自动GET一次；缺失/错误时间UNKNOWN，网络错误待核对，只有服务端EXPIRED提示新提案。新报价、Confirmation和Resume仍由用户显式操作，已有操作恢复保留原ID。
- RunTimeline沿用持久RunEvent，增加易读Supervisor路由、Handoff、工具成功/失败/耗时及输入输出Usage，结构化投影可展开。身份/调用/Token/费用/UNKNOWN仍来自现有认证runtime，不增加第二套Trace或模型输出。
- [Real Agent手册](../../REAL_AGENT_DEMO.md)、[3–5分钟脚本](../../DEMO_RECORDING_SCRIPT.md)、[发布清单](../../RELEASE_CHECKLIST.md)覆盖默认Fixture、新Live准入/预算/安全Key、本人确认、停止、刷新/登录/Thread恢复、结果未知核对和独立发布授权。README/COPYRIGHT/SNAPSHOT不再以长期有效文案断言某候选尚未上传，具体版本状态由实际回执确认。

## 历史B1只读核验

[公开汇总](b1-public-summary.json)仅含允许字段：历史617cdf29单次静音键盘任务，7次真实deepseek-flash回执（Supervisor3/Shopping2/Order2），输入12048/输出1109，费用估算上界¥0.032968，实际平台账单与Provider头请求IDUNKNOWN。

原私有证据清单54项哈希验证；逐项对齐API/DB事件seq1..50及ID，核验官方Saver安全摘要next=done/pending_writes=[]。人工确认前订单与Confirmation为0；用户独立批准后唯一19900分PENDING_PAYMENT订单、一个已消费Confirmation、一个BusinessEvent，payments0。另对原独立数据库执行明确READ ONLY事务，复核orders1/confirmations1/payments0/events50/checkpoints30。

未将原账本、授权、完整Checkpoint、JWT、真实Key、对话或原始截图复制进Git。公开仅7份回执的角色/Usage/状态及response_id哈希、汇总计数。旧B1授权已结束，不是当前版本的新Live许可，也不是独立泛化评测。

## 回归实测

| 检查 | 实测 | 退出码 |
|---|---|---:|
| 后端完整CI_OFFLINE_CORE | **713 passed / 14 skipped**，727 collected；新增2 | 0 |
| Ruff check / format --check | 全部通过 | 0 |
| Vitest全量 | **80 passed**；新增9（倒计时4、事件摘要3、响应头协议2） | 0 |
| typecheck / lint / build | 全部通过 | 0 |
| Playwright全量 | **81 passed / 6 failed / 0 skipped / 0 flaky**，87项、1worker、0retries | **1** |
| 新增倒计时专项 | 3/3通过，包含在上述87项内 | 0 |
| Compose config / 本地链接 / diff check | 通过 | 0 |
| 当前源码真实Live / GitHub CI / 录屏 | NOT_RUN / NOT_RUN / VIDEO_NOT_RECORDED | 不适用 |

14项skip未扩大：13项本地真实BGE权重依赖、1项未分发的私有Live原件比较；完整后端仍包含T09恢复/SIGKILL、T10 Trace、T11真实并发、T12协议/预算/权限/Oracle。没有重跑封存40题或历史Live。

后端为本地Linux ARM64/Python3.12.10、PG17.11/pgvector0.8.7/官方Checkpoint；前端和完整Chromium headless在Mac ARM64，Node24.21.0/npm11.19.0。专属项目agentmall-t15-c-tests，宿主55442/8018/5188，内部55433。runner1152MiB、PG256MiB；分阶段执行，**不声称单容器整体CI或Ubuntu amd64远程CI通过**。

新增浏览器测试验证：本机日历设2099年不错误判过期；到期只GET、不产生新Run/订单/确认；缺失时间UNKNOWN；到期GET失败没有自动重试循环或伪造EXPIRED。真实Provider调用始终为0。Fixture与MockTransport不冒充Live。

## 阻塞：Docker时钟回退

完整浏览器失败详见[browser-failures.json](browser-failures.json)。5项最终页面出现刚登录后失效，另1项SDK测试初始化抛出PRICE_EXPIRED。原始错误、截图、数据库事实、Playwright JSON及日志均留在忽略目录，未挑绿色结果或增加retry。

随后进行有界、纯合成诊断：

| 8秒窗口 | 循环数 | 实测回退 | 刚签发合成JWT失败 |
|---|---:|---:|---:|
| Docker默认双核 | 335391 | -2.091132025秒 | 1次ImmatureSignatureError |
| Docker进程单核CPU0 | 329861 | -2.090692078秒 | 1次ImmatureSignatureError |
| Mac宿主 | 337779 | 未观察到 | 0 |

因此已证明Docker中存在会触发认证失败的实际时间异常，单核诊断没有解决它。但**未逐请求记录全部6个浏览器失败的JWT异常类型/价格年龄，不能声称所有失败根因均已逐项闭环**。修复或更换时钟稳定的独立环境后，必须再做完整浏览器回归；若仍失败应继续定位源码问题。当前发布准入保持BLOCKED。

未调整全局Docker/系统时钟、未重启旧容器、未改JWT校验/leeway/价格Guard，也没有为绿色结果跳过或自动重复全量。诊断只生成不输出内容的合成JWT，未读取真实Key/Token或执行模型请求。新Live在此环境下也不应准入。

## 保留的RED/GREEN和历史失败

1. 新PostgreSQL测试先因缺少时间字段失败；首版到期fixture触发不可变约束，改用原timed_proposal辅助构造独立合成快照，未修改触发器。
2. 时间放进所有DTO时，全量5失败/708通过/14skip，原因是重放JSON不再相等；只放GET JSON时仍有1项Cart一致性断言失败。最终改为响应头，原领域服务/DTO恢复，7项受影响与新增测试通过，随后完整713/14通过；没有降低旧断言。
3. 私有Playwright配置准备曾遇到工作目录/模块解析错误，且wrapper使首个测试服务子进程未随之退出，下一次fresh bootstrap安全拒绝。只停止本轮拥有API子进程，改为原生直接Compose生命周期；无未知schema/volume清理。
4. 本轮浏览器6失败和时钟诊断原样保留。历史T14约1.91GiB Docker单容器OOM/143、T15-A预算子进程OOM/137、P0旧演示结束原因UNKNOWN、两轮Pilot同开发集及账单UNKNOWN均保留在原报告，不覆盖或改称通过。

## 公开内容与一次独立审查

[审计](publication-audit.json)检查公开独立父链中的P0/P1/R1-A/T15-A全部可达blob（453个旧blob），含已被后续版本替换的文件；新候选源文件和本地索引另外扫描。发现0项未解决秘密/个人路径/私有原件。公共作者仅已确认noreply身份；合成口令标为SYNTHETIC_TEST_DATA。原15张PNG来源为合成Fixture/Mock演示，哈希保留，无EXIF/text元数据；无新增公开媒体或第三方依赖，MIT及NOTICE不变，不分发镜像/权重/二进制。扫描不能证明不存在任意未知秘密，仍须权利人审核最终SHA。

一次只读独立审查未发现Critical/Important；[review.json](review.json)记录一项Minor：某些系统休眠会暂停performance.now，唤醒后估计可能滞后。已明确手动刷新提示；服务端确认检查仍防过期授权，暂不扩展自动焦点校准。独立审查未替主执行者核验私有原件或执行全量测试，不夸大其证据范围。

CI workflow未修改：目标Ubuntu24.04 amd64、锁定Python/Node/PG/pgvector/Action SHA、contents:read、无DeepSeek Key、仅有界脱敏状态Artifact。新的3项浏览器测试会由原默认配置收集。**远程从未触发，兼容性仍需真实远程验收**。

## 清理、复现和后续准入

所有本轮test_/cp_ schema已回收，独立PG最终应用会话0、Advisory Lock0；API和前端测试进程结束。仅对agentmall-t15-c-tests执行无-v的down，保留忽略目录PGDATA和证据，不重置历史Volume。原17容器、旧工作区/历史材料的最终保护核对见historical-integrity.json；原Private/Public/T14/T15-A未被修改。

[命令及退出/日志SHA](command-receipts.json)保留成功与失败，绝对工作站路径已替换为占位符。原始日志及实际完整命令保留在本地`.t15-c`，不是公开Artifact。后端核心命令为原bootstrap后`pytest --ci-offline-core --strict-markers -ra`；前端为typecheck/lint/test/build；完整浏览器使用现有Playwright测试集，只在私有配置中改独占端口/Compose生命周期/宿主完整Chromium，未改测试断言、skip或retry。

后续须先解决独立环境时间问题并完整回归，才能重新评定发布准入。其后仍需权利人对准确SHA、仓库/分支、Push和Actions作单独授权。当前不Push、不部署、不触发远程CI、不进行新付费Live。完成本地阻塞交付后停止。
