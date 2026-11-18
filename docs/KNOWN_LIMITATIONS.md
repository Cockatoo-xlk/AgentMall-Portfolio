# 已知限制与证据边界

本页对应产品代码验收提交 `759391cd6c33a1bbc906df34e6de87126cb53dac`（Tree `339d618bd92d092467e62e0511649c77b3a701d8`）。当前为本地候选，Release **ON_HOLD**，没有生产部署。文档收尾没有新的模型调用、Key读取、付费评测或资源清理。

## 真实模型与统计边界

| 范围 | 可以确认 | 不能据此声称 |
|---|---|---|
| 三个成功案例 | A推荐、B购买、C双HITL分别有真实DeepSeek与SQL回执；A/C Source为`8171e5576180e8827b78fff3d6c9f58051729f08`，B为`115905a3cb45bfd2b70384fec7375be9243a6f92` | 同一版本3/3、未见输入独立盲测、模型总体成功率或生产可靠性认证 |
| 首次Smoke | A FAIL / B PASS / C NOT_SCORED；后续A/C会话的C也仍NOT_SCORED | 以后C成功可以覆盖此前的超时、操作交付问题或原评分 |
| 原Owner四题 | H01 FAIL、H02 NOT_SCORED、H03 NOT_RUN、H04 STATIC_ADMISSION_REJECTED / Oracle NOT_RUN；原计划4，实际启动2、评分1 | 四题全跑完、未运行等于失败、后续开发回归算作原题PASS |
| L8原15题 | PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7，只有5题评分 | 完整15题实测通过率、统计显著Single/Multi优势 |
| 独立性 | 四题为PROSPECTIVE_OWNER_SUPPLIED，L8为PROSPECTIVE_SELF_AUTHORED；独立盲测数量0 | 开发者自填来源即可获得第三方评测或独立盲封身份 |
| 用量与账单 | 成功案例Usage已SETTLED；C当次保守上界CNY0.098820 | Host用量回执、峰值估算或预留就是供应商实际账单；实际账单仍UNKNOWN |

[完整结果与各Source](EVALUATION_RESULTS.md)保留失败、未评分和未运行项。三个成功执行是在开发与操作流程改进后获得的功能证据，没有合并通过率。最新产品修复提交只完成离线工程回归，没有新的Live评分。

## 产品与工程边界

| 范围 | 限制 | 核查入口 |
|---|---|---|
| 自然语言 | 中文解析有明确支持范围；原商品/新商品属性与单价/总预算分开，无法确定时仍需澄清，不能保证理解任意表达 | [偏好投影](../backend/src/agentmall/agents/product_preferences.py)、[价格与上下文](../backend/src/agentmall/agents/context.py)、[P2回归](../backend/tests/test_final_p2_contract.py) |
| 独立目标完成 | 交易回执只证明对应交易，不能替代订单查询、比较或售后目标；Single继续携原始目标、回执和prior results。纯购买显式结束通常增加一次受原预算约束的模型调用 | [持久图](../backend/src/agentmall/agents/durable_graph.py)、[Single控制](../backend/src/agentmall/agents/specialists/runner.py) |
| 模型错误 | 即使已有订单，模型重复写或非法参数仍应失败；既有结束信号也不构成任意自然语言目标都被满足的确定性证明 | [工具校验](../backend/src/agentmall/agents/model_control.py)、[重复写回归](../backend/tests/test_agent_write_sequencing.py) |
| HITL与资金 | 独立Confirmation只授权被审阅的具体Proposal；购买批准不授权付款或退款。REQUESTED Case不是已退款，PENDING_PAYMENT不是已支付 | [动作服务](../backend/src/agentmall/actions/service.py)、[订单事务](../backend/src/agentmall/orders/service.py) |
| 恢复与外部副作用 | Checkpoint、Journal、Thread锁、epoch fence与持久回执有受控故障测试；不保证任意外部Provider请求exactly-once、生产灾备或SLA | [恢复测试](../backend/tests/test_recovery_interleavings.py)、[Worker](../backend/src/agentmall/agents/worker.py) |
| 诊断与隐私 | model_request_id是本地关联UUID；Schema/响应哈希是规范JSON哈希，不是原HTTP字节；body.id不是HTTP request-id。OBSERVED_VALID仅表示用量数字自洽，不是账单 | [诊断边界](ARCHITECTURE.md#正式run模型诊断的证据边界) |
| RAG | Jieba + PostgreSQL全文ts_rank_cd、本地BGE/pgvector、RRF；默认不启用Reranker。历史40条合成检索查询与单标注者结果不等于Agent业务可靠性 | [检索验证](REAL_RETRIEVAL.md) |
| 工程测试 | 最终Backend为1824 PASS / 0 FAIL / 16 SKIP；15项真实BGE按CI Offline Core跳过，1项缺少私有历史原件。早期真实BGE/前端结果不能冒充此Source的新验证 | [精确归属](V217_INTERVIEW_READY.md#最终源码验收) |
| 旧E1契约 | E1_ORACLE_CONTRACT_MISMATCH保留：Native与正式SDK校验阶段不同；没有放行未声明工具或更改原Oracle | [原Oracle回归](../backend/tests/test_l8_r4_original_oracle.py)、[批次校验](../backend/src/agentmall/agents/model_control.py) |
| MCP与规模 | 仅stdio/localhost，REMOTE_AUTH_NOT_IMPLEMENTED；没有生产用户数、QPS、高并发压测、SLA或生产部署证据 | [MCP指南](MCP_GATEWAY.md)、[架构](ARCHITECTURE.md) |

L8第08题仍为INSUFFICIENT_EVIDENCE，原Ledger、实际费用UNKNOWN与CNY2.113536预留保留；新诊断不能补造历史响应或释放原预留。未继续原09—15题，不恢复停止的历史Run，不修改Gold、Oracle或旧评分。

## 演示与历史验证

[3分30秒MP4](media/v217/agentmall-v217-demo.mp4)来自V2.16 RC1的真实业务API/PG与SDK Mock素材，标注OFFLINE MOCK DEMO。原静音WebM及录制器收尾exit1保留；字幕和SQL卡不是新Live录屏。历史VIDEO_NOT_RECORDED只描述当时阶段，不能当作当前视频状态。可复现[Demo](DEMO_GUIDE.md)使用MockTransport/Fixture，真实后端不等于真实模型；首次构建仍可能下载依赖。

历史V2.17 BGE13、Vitest146、Playwright129属于[原回执](evidence/v217/verification.json)对应阶段。本次只核对既有日志，不重跑完整Backend、前端或BGE，不把这些数字累加成最新Source的验证数量。

## 容器隔离与保留资源

历史Docker Socket整改按精确Owner授权删除8个Exited风险容器，删除退出码0、未使用force或volume删除；原Volume和镜像保留。收尾回执SHA256为 `70e9ce13b522b642904830bc185062674ce7e03afd215f709c5cbf0dfe7f582a`。本次只读核验这8个完整ID仍不存在。历史Docker API审计并不完整，是否发生过越权操作仍UNKNOWN；没有证据就不推定入侵。**本地历史整改不是生产环境安全认证**。

普通Agent Worker只使用Owner批准的安全Native隔离入口：不挂载Docker Socket或其父目录、不加入额外组0、不privileged，保持只读RootFS、no-new-privileges、最小Capabilities；Docker管理留在可信Host。旧B2B2配置只读保留，通用CI Compose不作为Agent Worker入口；不能声称所有历史/通用配置都已自动加固。每次新运行仍需核验实际资源权限。

Final P2在本轮独占测试PG中发现12个临时业务/Checkpoint Schema，已通过私有数据库快照保全后停止该PG。快照SHA256为 `af3ccfb0b617b5021abbdac039a279f8a97914b2eb9fec28162a4aa514ed59fb`。本次只核对Owner、Exited状态和快照哈希；不重启、不连接数据库、不清理Schema或Volume，也不声称停止的临时文件系统仍在线保有这些Schema。以后处置须另获精确授权；历史C/L8资源不在范围内。

## 贡献与公开边界

项目使用AI辅助开发。个人贡献只陈述自己实际设计、修改、复现、走读和能够解释的部分；测试数量不等于独立个人贡献。公开文档只给核验过的统计、业务增量与哈希，不上传Key、凭据日志、数据库密码、真实用户身份、私有运行目录、Gold或完整调试日志。Release ON_HOLD，文档、离线回归或远程CI均不构成新的模型费用、发布或部署授权。
