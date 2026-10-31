# 3–5分钟合成业务演示

按[首页](../README.md)启动隔离Compose及 `scripts/demo.py --prepare-return --seconds 900`。这是Fixture Model + 真实FastAPI/PostgreSQL/Checkpoint，准备订单由脚本独立确认并模拟付款，不是模型自主支付。

| 时间 | 操作 | 核对事实 |
|---|---|---|
| 0:00–0:30 | buyer1登录，打开“工作流”，指出Fixture标识；创建multi Thread | 当前服务使用Fake Model，JWT只存内存 |
| 0:30–1:15 | 输入“找一款300元以内静音键盘准备购买，送演示宿舍” | Supervisor/Handoff时间线；WAITING_INPUT只生成提案，没有新增订单 |
| 1:15–1:50 | 阅读快照，点击“批准并继续工作流”，查看订单 | 原Run Resume；新增PENDING_PAYMENT订单，不等于已付款 |
| 1:50–3:30 | 复制启动输出的delivered_order_id；新Run输入“订单<该UUID>质量问题想退掉，再帮我推荐一款500元以内静音键盘，准备购买，送演示宿舍。” | 第一次批准创建REQUESTED Case；第二张购买提案用新的confirmation再次批准；退款数仍0 |
| 3:30–4:15 | 刷新，重新登录同一买家，恢复原Thread | 数据库重建事件与真实资源，不新建原业务动作 |
| 4:15–4:45 | 说明失败、费用和许可边界 | UNKNOWN Usage、PARTIAL保留；无真实资金，也无生产负载或SLA验证 |

返回/重复确认/回包丢失的真实浏览器与SQL断言见[return_replace.spec.ts](../frontend/tests/return_replace.spec.ts)。网络不确定先GET核对原Thread/Proposal/Order/Case，保持原request_id，不自动重做业务。

以下是原T13合成Fixture演示截图，R2已审阅像素、R4核对SHA及PNG元数据，非本轮新Live或录屏：

- [购物完成](screenshots/shopping-completed.png)：PENDING_PAYMENT。
- [退货及替代购买](screenshots/return-replacement-completed.png)：两份确认，Case仍REQUESTED。
- [移动端恢复](screenshots/recovered-mobile.png)：刷新后登录恢复。

录屏状态VIDEO_NOT_RECORDED。端口占用或运行失败时保留错误，不能把历史截图称为现场成功。不要对公网开放测试控制接口。退出后等待本次进程/schema清理，按首页只停止本项目容器。
