# T14-P0：订单页模拟付款闭环

基线17f72b8ccd6a86e083fd3206ea839dd28dc22bcf；范围以当前用户T14-P0十项实施要求为准。本地worktree，禁止Push/远程Actions/部署/付费模型；原Private、public main、R5审核目录及现有演示资源保持。

## 局部设计

复用既有订单页、类型和五个API。采用订单页内独立支付确认卡，和购买确认明确分开；不重写支付领域服务，不增加支付Provider或支付路由。订单视图接受完整的服务端GET订单DTO更新，所有状态以GET为准。

用户点击“模拟付款”生成一次稳定操作：request_id、提案Key、执行Key、expected_version。POST payment-proposals后GET proposal确认不可变快照，展示订单/金额/币种/有效期/服务端提案状态。第二个独立批准按钮创建该支付提案自己的Confirmation，再POST mock-payments，最后GET proposal及订单核对回执。拒绝只记录reject，不执行支付。

非秘密导航/幂等引用按user+store+order存sessionStorage；不保存JWT、密码、地址或模型对话。刷新/重登后只GET恢复，不能自动执行持久approve。所有未知写入先GET；若创建提案响应丢失且未知proposal_id，则先GET订单，只有用户再次点击才用原request_id及原Key重放原创建请求以找回提案。未取得真实回执不宣告成功。后续显式新报价仅在原操作已明确终结或服务端版本失效后允许，不自动更换标识。

SUCCEEDED/DECLINED/EXPIRED回执与当前GET订单分开展示；STALE_VERSION提醒核对及重新生成快照；401/403/404停止付款；本机时钟不决定有效性。操作锁防双击，结果未知时仅开放查询/原操作继续；其他订单状态没有可执行付款入口。页面清楚说明合成数据/模拟资金。

## 实施计划（当前会话直接执行）

1. **契约与RED**：读取真实API/adapter/DTO；跑既有Vitest基线，先补按钮/非待付不可付、幂等/丢回包/拒绝/过期/版本与权限Vitest，再运行观察RED。新增真实React+API+PG支付成功E2E，先验证原UI缺入口的RED。
2. **最小前端**：新增api/payment.ts及MockPaymentPanel；Orders仅接入同一订单详情；稳定操作引用与读取恢复，展示不可变快照、独立批准/拒绝和真实回执。覆盖计划1的行为，运行Vitest/typecheck/lint。
3. **PG E2E证据**：扩展既有受控web_e2e_server，仅增加测试adapter选择、订单时钟/版本控制与payment rows只读事实；成功/拒付/过期/重复点击/拒绝/未知响应/刷新恢复/非待付不可付/他人拒绝/Agent订单同路径，截图桌面及移动端，断言独立数据库终态与库存、确认、回执/事件唯一性。
4. **回归与交付**：独占Compose项目和新PGDATA完成CI_OFFLINE_CORE、前端全项与全量Playwright；保存实际数量/退出码/截图/SQL；一次针对性独立审查，必要修复后回归；核对原资产、清理本轮资源；本地提交并停止，保留worktree供后续发布审核。

## Review Focus

- 首次提案响应丢失没有proposal_id时必须保存原请求；确认响应丢失不能自动批准新提案。
- 已提交支付但GET失败或订单状态推进时不能误显示失败，也不能重复扣减库存。
- 支付Confirmation与购买Confirmation隔离；拒绝后绝不POST支付。
- 页面刷新/切账号/换订单不复用错误的操作引用或JWT。
- 过期/拒付/陈旧版本不会自动重报价或自动批准；测试最终结论来自独立PG连接。
