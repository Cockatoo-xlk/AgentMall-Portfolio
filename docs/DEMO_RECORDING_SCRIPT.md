# 五分钟讲解脚本 · VIDEO_NOT_RECORDED

这是待录制路线，不是已交付视频。先按[默认Demo](PORTFOLIO_DEMO.md)启动独占本地环境、选择context-catalog、创建 **Single / Legacy Sync**。全程 **SDK MockTransport / Fixture Embedding / TEST_OPERATOR**，不读取Key、不打开付费Provider。

| 时间 | 画面 | 可以直接讲的内容 |
|---|---|---|
| 0:00–0:40 | 商品目录和模式区 | “这是合成商城。模型建议、持久工作流和真实数据库事务是三层；当前模型回包和向量都是Fixture。” |
| 0:40–1:30 | 推荐300元静音键盘 | “工具查询当前目录，结果有SKU、版本和来源。推荐不等于购买。” |
| 1:30–2:15 | 改无线、预算400 | “服务端更新可信Context，让旧名单失效。第二款引用必须绑定这一次实际显示的集合和rank。” |
| 2:15–3:10 | 请求购买当前第二款 | “先重新核对商品并生成不可变提案；WAITING_INPUT时尚无新订单。” |
| 3:10–4:00 | TEST_OPERATOR批准、订单详情 | “独立Confirmation之后，原Resume中的领域事务创建唯一PENDING_PAYMENT订单并预留库存。没有付款。” |
| 4:00–5:00 | 刷新恢复、架构/证据表 | “Checkpoint记录图位置，领域回执决定真实写入。Multi有额外交接成本；真实五题Pilot的Multi为4/5，当前B2还失败，不能把Mock通过当成模型可靠。” |

额外问题再打开[Worker](V212_DURABLE_WORKER.md)、[MCP](MCP_GATEWAY.md)、[商家Copilot](MERCHANT_COPILOT.md)或[评测](EVALUATION_STUDIO.md)，不要在主线里自动付款、退款或kill进程。录屏前收起终端凭据、原始账本、授权、Checkpoint及开发者工具Authorization头；UUID仅为合成临时资源。若失败就保留说明，不剪辑成不存在的成功。
