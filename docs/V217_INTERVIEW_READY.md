# V2.17 最终本地候选 · 工程与作品集交付

本页将当前产品代码、历史真实模型案例、离线演示与原评测结果分开记录。当前分支为 `codex/v217-post-live-hardening`，产品代码验收提交为 `759391cd6c33a1bbc906df34e6de87126cb53dac`，Tree `339d618bd92d092467e62e0511649c77b3a701d8`，Parent `2df4e594e2c2687173e9360ee351fb6f83d12fc7`。文档提交不改变这些产品/测试文件，也不声称在新的文档Tree上重跑了全部测试。

2026-11-18只读核对远程main为 `550853eeffe113f840dbe17de57fc71e3d68434b`。上述修复仍是本地交付，未完成该候选的Push/PR与远程CI；不能用早期V2.16/V2.17 CI冒充最新修复的CI。Release **ON_HOLD**，没有生产部署。

## 最终源码验收

| 检查 | 已核验结果 | 归属 |
|---|---|---|
| 完整Backend CI Offline Core | **1824 PASS / 0 FAIL / 16 SKIP**，退出码0，pytest831.85秒 | 最终产品提交759391cd；真实隔离PG、SDK MockTransport/Fixture |
| 最终定向回归 | 153 PASS / 0 FAIL / 10 SKIP，退出码0 | 同一最终产品实现；与全套有重叠，不累加 |
| Ruff | PASS，退出码0 | backend/evals/scripts |
| Format | PASS，退出码0，351文件 | backend/evals/scripts |
| Diff检查 | staged与committed diff --check均通过 | 唯一P2修复提交，9个文件 |
| 当前文档收尾 | 不重跑Backend/BGE/前端，只做文档核对 | 只改Markdown，不修改产品或测试 |

完整Backend仅在最终产品源码上执行一次，受控Linux测试命令为：

```text
python -m pytest --ci-offline-core --strict-markers \
  -o cache_dir=/tmp/pytest-cache -o junit_family=legacy \
  --junitxml=<owned-output>/backend-final.xml -ra -q backend/tests
```

该命令运行于专属真实PostgreSQL网络命名空间，最终831个受控文件与工作树逐字节相符；测试容器无外网、无Docker Socket或额外组0、非privileged、只读RootFS。它不是可不经授权启动Live的命令。初始RED（10失败）与审核补充RED（6失败）、7项开发脚本兼容失败均留证；后续用既有terminal finish协议修正Fixture，SQL、独立确认、重复调用和失败断言未放宽，不把中间结果相加充当最终成绩。

16项Skip准确分解如下：

| 文件 | 数量 | 原因 |
|---|---:|---|
| [test_live_preflight.py](../backend/tests/test_live_preflight.py) | 10 | CI_OFFLINE_CORE未安装真实BGE权重，real_bge策略跳过 |
| [test_multiagent_integration.py](../backend/tests/test_multiagent_integration.py) | 2 | 同上 |
| [test_postfix_smoke_selection.py](../backend/tests/test_postfix_smoke_selection.py) | 1 | 同上 |
| [test_retrieval_ingest.py](../backend/tests/test_retrieval_ingest.py) | 1 | 同上 |
| [test_v217_live1_bge.py](../backend/tests/test_v217_live1_bge.py) | 1 | 同上 |
| [test_eval_monitor_policy.py](../backend/tests/test_eval_monitor_policy.py) | 1 | 缺少原始私有历史Live证据，仍跳过；不伪造原件或通过结果 |

以上15项BGE跳过不代表BGE测试通过；此前另行执行的真实BGE13项、Vitest146项、Playwright129项/0重试属于[早期V2.17回执](evidence/v217/verification.json)，本次没有重跑。3条warnings来自既有jieba正则转义。

| 私有验证记录的公开哈希锚点 | SHA256 |
|---|---|
| 最终完整Backend日志 | `9e1c650840160e2a9a1f2e1ef108d2b770ec8e7eac87e5cbff4c7587f754afc0` |
| 最终Backend JUnit | `97623d36657d4186468913d165c1b6d5888a7cfe27f660b28206ee2b7c7d66c7` |
| 最终P2机器回执 | `127efdbfca57020953f785ce6d32619d7d3e93b01245d5db8f466bda532f2feb` |
| P2修复Diff | `283d22abc62c91f1de14e0c6f3057453234cddf00f241a0bf1bb3f6ab78d7099` |

哈希用于绑定记录，不公开原始调试包、数据库或私有路径，不代替第三方对原件的审计。

## 产品改进与源码入口

- **事实与展示一致。** 推荐最终数量、商品引用和Thread候选绑定，同时保留探索记录；价格库存来自服务端。[偏好与投影](../backend/src/agentmall/agents/product_preferences.py)、[Thread记忆](../backend/src/agentmall/agents/memory.py)。
- **自然语言作用域。** 区分单价描述和总预算；退货原商品属性不能污染新购买商品，“退货后/换用”的新商品约束不能整句丢弃，同一新商品真实冲突仍澄清。[上下文](../backend/src/agentmall/agents/context.py)、[最终P2回归](../backend/tests/test_final_p2_contract.py)。
- **回执与目标分开。** 购买成功不能证明独立查询或比较完成；原目标、持久回执和prior results继续既有Single流程。纯购买通过既有结构化结束信号收尾；重复写仍硬拒绝，确认和库存事务未放宽。[持久图](../backend/src/agentmall/agents/durable_graph.py)、[Specialist执行](../backend/src/agentmall/agents/specialists/runner.py)。
- **失败可观察。** H01补充SQL商品category投影；交易后查询、重复Resume及双HITL在正式API、PG、Checkpoint与独立SQL下回归。[开发回归](../backend/tests/test_post_holdout_product_fix.py)。最新修复没有新的真实模型成绩。

## 真实模型案例与原评分

[详细Source、用量和回执SHA](EVALUATION_RESULTS.md#三个独立执行的真实成功案例)：B真实购买PASS使用Source `115905a3cb45bfd2b70384fec7375be9243a6f92`；A真实推荐PASS、C真实双HITL PASS分别执行于Source `8171e5576180e8827b78fff3d6c9f58051729f08`。C的连续Episode为81.333秒，11次HTTP；Case+1、PENDING_PAYMENT订单+1、Confirmation创建/消费+2/+2、库存预留+1、Payments/Refunds+0、Run COMPLETED。

这些是不同会话与两种源码下的独立成功执行案例，不是同一版本3/3、独立Holdout3/3或生产可靠性认证。成功案例用量已SETTLED，实际供应商账单UNKNOWN。首次Smoke仍A FAIL/B PASS/C NOT_SCORED；后续A/C会话的C也仍NOT_SCORED，不被更后C成功覆盖。

原Owner四题仍H01 FAIL、H02 NOT_SCORED、H03 NOT_RUN、H04 STATIC_ADMISSION_REJECTED / Oracle NOT_RUN。原输入、Oracle、Gold和79份封存证据不改；H04暴露后的开发回归不算原题重评。独立盲测数量0。L8永久PASS1/FAIL4/NOT_SCORED3/NOT_RUN7，08 Ledger与实际费用UNKNOWN，E1_ORACLE_CONTRACT_MISMATCH保留；原09—15未运行。

## 可复现离线演示与作品集

[agentmall-v217-demo.mp4](media/v217/agentmall-v217-demo.mp4)：**3:30 / 1440×1080 / 25fps / H.264 / 2,728,972 bytes**，静音字幕版。[讲解稿](media/v217/agentmall-v217-demo-script.md)、[剪辑清单](media/v217/edit-list.json)、[编辑工具](../scripts/render_interview_video.py)。成片SHA256为 `143c029a324632309ded3a03d1847e0944d5718d3034bb351ebf390e25cbe24e`；本次不修改媒体。

视频来自V2.16 RC1的SDK MockTransport / Fixture素材，正式FastAPI、PostgreSQL与业务事务真实运行，明确标注OFFLINE MOCK DEMO / REAL BUSINESS API / REAL POSTGRESQL，不是真实DeepSeek在线录屏。原6:55 WebM保留，SHA256为 `c2becdda2b5b33d467d3ff789a83af79d94ca1aa32d775a0bd3c90c5c70e45e1`，录制器收尾exit1未改成成功。字幕中的SQL卡是原回执投影，不是新终端执行画面。

[连续A/B/C浏览器回归](../frontend/tests/interview-demo.spec.ts)与[早期回执](evidence/v217/verification.json)验证正式API/SQL链路：A不交易、B独立确认后唯一待付款订单、C两份独立确认产生Case及替换订单，支付/退款增量0，刷新不重放交易。它们是合成模型开发验证，不是新的真实模型通过分母；历史BGE、前端及录像成绩只绑定原阶段。

[演示指南](DEMO_GUIDE.md)用于无Key复现；[架构](ARCHITECTURE.md)、[工程案例](ENGINEERING_CASES.md)、[12问](INTERVIEW_TALKING_POINTS.md)、[简历稿](RESUME_PROJECT.md)用于源码讲解。项目为AI辅助开发，个人贡献只保留实际设计、实现、复现与能够解释的部分；没有线上用户量、QPS、SLA或独立手写整个仓库的证明。

## 安全、资源与下一交付门禁

历史8个Exited Docker Socket风险容器已按精确授权删除，Volume/镜像保留；本次只读确认这8个ID仍不存在。历史操作审计不完整，不能推定发生或未发生过越权行为；本地整改不是生产安全认证。普通Worker仅用批准的安全Native入口，Docker控制权留在可信Host，通用CI Compose不作为Agent Worker。[详细边界](KNOWN_LIMITATIONS.md#容器隔离与保留资源)。

Final P2的12个临时Schema通过私有测试库快照保全，PG仍Exited。本次只读核对归属与快照哈希，不重启、不清理、不操作历史C/L8数据库或Volume。以后处置须另行授权。

本地代码门禁已通过；本次只提交事实性Markdown修正。GitHub交付前仍须实时复核准确候选与main、取得针对准确SHA的Push/PR授权并验收各自CI；不自动Merge。新的Live必须另行绑定Source/任务/预算并获授权。Release继续ON_HOLD，不Tag、不Release、不Deploy。
