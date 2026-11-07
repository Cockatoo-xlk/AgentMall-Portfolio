# V2.5 多品类合成目录

V2.5 提供 13 个品类、120 个 SKU。所有名称、规格、价格、库存和插画都是合成演示材料，无品牌授权或真实销售含义；器材描述也不是安全认证或医疗建议。

| category | 类别 | SKU |
|---|---|---:|
| keyboard | 键盘 | 8 |
| mouse | 鼠标 | 6 |
| headphones | 耳机 | 6 |
| smartphone | 手机 | 10 |
| laptop | 笔记本电脑 | 10 |
| tablet | 平板电脑 | 10 |
| monitor | 显示器 | 10 |
| camera | 摄影器材 | 10 |
| smartwatch | 智能手表 | 10 |
| speaker | 音箱 | 10 |
| cycling | 骑行装备 | 10 |
| fitness | 健身器材 | 10 |
| home_appliance | 生活家电 | 10 |

## 数据版本与迁移

- `legacy-12-v1`：`seed(session, settings)` 的默认数据，原 `PRODUCTS`、UUID5命名、12件商品和初始库存保持不变。后端测试、Playground及历史评测继续显式或默认使用这一基线。
- `expanded-120-v1`：`seed(session, settings, profile="expanded")` 先补齐缺失Legacy记录，再从[独立资源](../backend/src/agentmall/catalog/data/expanded-v1.json)插入108个SKU。SKU键经严格Schema校验，ID为`uuid5(storefront_id, "expanded-120-v1:" + sku)`；按ID冲突不更新。重复导入不重置库存、价格、下架状态、版本或已有订单引用，也不删除其他商品。
- 新增[迁移0008](../backend/migrations/versions/0008_expanded_catalog.py)只扩大类别CHECK，旧迁移未修改。在有新类别商品时回退会拒绝，不自动删除数据。请先备份并独立设计数据迁移，不能用降级清空目录。

在**自己的新数据库**完成配置后，可运行：

```sh
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend python -m agentmall.seed --profile expanded
```

普通API不会自行迁移、Seed或启用模型。不要把命令指向历史Demo数据库。

## 无Key浏览器演示

沿用[作品集本地启动](PORTFOLIO_DEMO.md#启动)的独占Compose方式。`scripts/demo.py`默认选择Expanded，也可明确指定：

```sh
docker --context desktop-linux compose -p agentmall-v25-demo \
  -f compose.ci.yaml -f compose.portfolio-local.yaml run --rm --no-deps \
  runner python scripts/demo.py --catalog-profile expanded --seconds 900
```

先按原指南用同一个**新项目名**构建runner、启动PostgreSQL。若旧实例占用5196/8026，可在执行所有Compose命令的终端先设置`export AGENTMALL_DEMO_WEB_PORT=5198 AGENTMALL_DEMO_API_PORT=8028`，访问地址与控制API同步使用5198/8028；先检查新端口空闲，不停止旧Demo。默认端口保持不变，绑定地址始终为127.0.0.1。控制API仍仅用于本机合成环境。健康回执的`catalog_dataset`区分两种数据身份。`--catalog-profile legacy`保留旧12件演示，评测不能把Expanded数据冒充旧结果。

以合成buyer1账号登录，商城有换行分类导航。手机筛选最高3000元可看到6件；27英寸显示器有5个不同价位；公路车骑行有头盔、手套、车灯等；生活家电500元以内有8件。详情展示各类别参数，卡片只摘取真实目录的2—3项规格。可从卡片加购，再生成购买提案、独立确认，最终到`PENDING_PAYMENT`；默认不付款。

工作流可使用已有`context-catalog` SDK MockTransport场景，并依次尝试：

1. `推荐3000元以内的手机，不要购买。`
2. `改为比较27英寸显示器，不要下单。`
3. `就买第二款，一件，送演示宿舍。`

编号只能引用当前有效名单。第三轮先生成提案，TEST_OPERATOR或用户单独确认后才执行。MockTransport和Fixture Embedding只证明可复现业务链路，不能代表真实DeepSeek或真实语义向量效果。

## 检索和安全边界

类别与同义词来自[受控目录词表](../backend/src/agentmall/catalog/categories.py)。显式类别、预算、库存、店铺、目录版本、屏幕尺寸、公路车用途和咖啡机/头盔/哑铃等受控细分类型约束在召回LIMIT之前执行；结果还会重读当前商品，工具在准备购买前再次检查。跨品类商品只能按实际已读取的规格比较，未提供的属性不能作为事实。含多个明确类别的歧义Thread输入要求澄清；当前结构化偏好仍一次绑定一个类别。

产品索引版本从`catalog-zh-v2`变为`catalog-zh-v3`，旧索引不会自动当成新事实。对自己已确认归属的环境，先Seed，再通过已有`index_products(session, storefront_id, encoder)`原子重建；环境初始化和Demo会调用此入口。当前没有面向任意持久Schema的通用索引CLI，不要把独占验证入口当成旧库升级工具，详见[检索说明](RETRIEVAL_INDEXING.md)。政策索引不改变版本。BGE固定Revision、512维、RRF与0.45阈值均不变；无模型时不编造结果。

品类切换清除旧类别的连接、键盘轴体/配列、噪声、活动及屏幕偏好，保留预算，显式新条件可以覆盖；旧名单会失效。屏幕、用途及商品类型均有明确CLEAR按钮，使用原context_version与request_id校验，清除后必须重新检索。购买意图、数量、地址和Confirmation仍不跨Run继承。

## 验证与限制

本轮实际结果、源码绑定、失败保留及日志SHA见[验证摘要](evidence/v25/verification.json)。测试只使用新建PostgreSQL/pgvector、官方Checkpoint与合成Mock/Fixture资源。没有变更支付、退款或售后事务，没有重跑历史Live Pilot或900秒准入。

截图展示合成目录与TEST_OPERATOR购买，见[桌面目录](screenshots/v25/01-expanded-desktop.png)、[手机确认](screenshots/v25/02-phone-confirmation.png)、[移动端骑行](screenshots/v25/03-cycling-mobile.png)。未执行新版本真实Provider评测或远程CI。

## A—J业务检查

| 场景 | 本地离线验证方式 |
|---|---|
| A 手机≤3000元 | 可信品类/预算解析，三种召回模式仅返回真实手机；网页返回6件 |
| B 公路车头盔/配件 | `activity=road_cycling`与实际用途字段核对；细分头盔可再收紧；无虚构商品 |
| C 27英寸显示器 | `screen_inches=27`过滤、不同价格实际记录；工具再验规格 |
| D 生活家电≤500元 | 真实目录有8件符合；三种召回模式检查预算与品类 |
| E 无显式类别参数 | 手机/显示器/vlog等查询自动识别类别；咖啡机、哑铃等收紧真实细分类型 |
| F 新品独立确认 | Agent选当前名单商品后WAITING_INPUT，确认前订单0；Cart购买另有浏览器确认 |
| G 库存/并发/幂等 | 新手机最后一件，两买家真实PostgreSQL锁竞争，一成功一缺货；重复回执仍仅一单，付款0 |
| H Legacy与V2 | 原12件及UUID/属性保留；原交易、售后、商家、SSE和Studio回归分别执行 |
| I 重复Seed | 120不增加；已有商品价格/预留和已有订单不被覆盖 |
| J 分页完整性 | API每页7件遍历120个唯一ID；浏览器每页8件加载全量，无重复卡片 |

这些检查使用真实数据库事实和工具结果，非真实模型效果评测。已请求的属性不会因界面或Mock答案而变成授权；只有当前有效提案的独立Confirmation才能创建订单。
