# 商家运营工作台

使用合成商家账号 `merchant`（演示密码见[本地 Demo](PORTFOLIO_DEMO.md)），登录后从顶部进入 **商家工作台**（`/merchant`）。工作台不依赖模型。退款只改变本地演示交易记录。

| 步骤 | 浏览器操作 | 核对 |
| --- | --- | --- |
| 1 | 在买家商城创建订单，打开订单详情并完成独立确认的模拟付款。退出买家登录，使用商家账号登录。 | 买家不显示工作台入口，直接访问也会被拒绝。 |
| 2 | 在「订单管理」筛选已支付，打开对应订单。点「发货」，随后点「确认送达」。 | 详情显示商品快照、金额、创建时间和版本；状态依次变为已发货、已签收。 |
| 3 | 买家使用现有工作流提交退货申请，或由下方测试创建同样的合成申请。商家切到「售后管理」筛选待审核。 | 可打开售后详情、阅读原因、跳转关联订单。 |
| 4 | 填写审核说明，点「审核通过」或「审核拒绝」。若通过，点「确认收到退货」。 | 收货只在审核通过后出现；拒绝后不能收货或退款。 |
| 5 | 点「生成模拟退款提案」，核对订单、不可编辑金额和有效期。点「批准退款提案」，再点「执行模拟退款」。 | 批准只产生 Confirmation。执行后有退款回执，售后和订单都显示已退款。 |

列表支持状态筛选和游标翻页。写入后读取服务端状态；如果另一窗口已更新版本，页面会提示核对最新状态，不会替你重试。网络结果不确定时，先点「核对退款提案状态」。在本次工作台内查看其他订单或售后后返回，仍可沿用原提案和请求标识。沿用 V1 的内存登录：整页刷新后需要重新登录，不会自动执行写操作。未完成退款提案和即时回执不会跨页面会话保留；订单和售后最终状态仍可在重新登录后查询。

## AI运营助手

新增独立[只读Copilot](MERCHANT_COPILOT.md)，可查看本店待办、库存与索引事实并草拟审核说明。只读重检后可填入原表单；批准、拒绝及退款仍使用本页原有独立业务按钮。原工作台不依赖模型，普通API的Copilot默认MODEL_DISABLED。

## API

新增商家读接口，统一前缀 `/api/v1`：

- `GET /merchant/orders` 与 `GET /merchant/orders/{order_id}`。
- `GET /merchant/after-sales` 与 `GET /merchant/after-sales/{case_id}`。

列表接受各自的 `status`、`cursor`、`limit`（默认 20，范围 1–100），按 ID 稳定分页，响应含 `items` 和 `next_cursor`。店铺取自服务端认证后的账号，不能从查询参数指定；未登录返回 401，买家返回 403，跨店详情返回 404。原买家接口仍只读本人的资源。发货、送达、审核、收货、退款及 Confirmation 继续调用已有端点，使用原有版本检查和事务规则。

## 复现浏览器冒烟

在独占的本地测试 PostgreSQL 17 / pgvector 库上安装锁定依赖和浏览器。**不要将测试 URL 指向在用的演示库。** 下方标准 Playwright 入口要求其测试库通过 `127.0.0.1:55433` 访问；如果这个端口已被旧环境占用，请在独立环境运行，或按后文用普通 FastAPI 与 Vite 手工验收。商家场景不需要 Agent 模型、Checkpoint 或 BGE 权重。

```sh
uv sync --project backend --locked --no-extra embedding
npm --prefix frontend ci
npm --prefix frontend run install:browser
# 当前 shell 设置本次专属的 AGENTMALL_TEST_DATABASE_URL、
# AGENTMALL_DATABASE_URL 与随机 AGENTMALL_JWT_SECRET，再运行：
backend/.venv/bin/python -m pytest -q backend/tests/test_merchant_workbench.py \
  backend/tests/test_checkout.py backend/tests/test_lifecycle_http.py \
  backend/tests/test_aftersales.py backend/tests/test_refund_idempotency.py
npm --prefix frontend run test:e2e -- merchant.spec.ts
```

浏览器测试先用现有买家 API 准备合成订单和售后申请，所有商家业务步骤通过 UI 执行。覆盖买家访问拒绝、真实版本冲突、查看关联订单后恢复原提案、提交成功但响应丢失后只读找回回执，以及刷新不重放。通过后，`frontend/test-results/` 内可找到合成订单、退款提案和回执截图；截图不含登录凭据或 JWT。全程无需配置 Provider Key。

### 在独立端口手工查看

为普通 API 指定**本次新建**的 PostgreSQL 连接和随机 JWT secret。确认以下两个示例端口均空闲；不同终端分别启动 API 和前端：

```sh
# 终端 1：已安装上方依赖，且 AGENTMALL_DATABASE_URL、
# AGENTMALL_JWT_SECRET 指向本次专属的演示配置。
backend/.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/python -m agentmall.seed
backend/.venv/bin/python -m uvicorn agentmall.main:create_app --factory \
  --host 127.0.0.1 --port 18082

# 终端 2
AGENTMALL_API_TARGET=http://127.0.0.1:18082 \
  npm --prefix frontend run dev -- --port 15282 --strictPort
```

打开 [本地工作台](http://127.0.0.1:15282/merchant)，登录后按上表操作。普通 API 不启动买家 Agent；如需测试预置售后数据，使用标准冒烟测试。停止时只退出本次启动的进程及新建数据库。
