# T14-P1 购物车结算与订单生命周期修复

本轮在独立`codex/t14-p1-cart-lifecycle` worktree实施，父提交`d8a18b0b56b0bdebe9a1ea1400849f82cecdbbef`。代码已写且真实PostgreSQL、Checkpoint及浏览器断言已验证。仅本地提交，没有Push、远程Actions、部署、真实支付或付费模型请求。最终提交SHA由包含本报告的本地Git提交及交付回复给出，避免自引用哈希。

## 行为与实现

购物车生成购买提案时，服务端在已验证归属和版本的Cart锁内，把`cart_source={cart_id,user_id,store_id,version}`加入不可变、参与payload_hash的canonical_payload。前端不能自行授予来源；不根据proposal_slot、相同SKU或Agent身份猜测来源。历史没有来源的提案仍可下单，回执为NOT_APPLICABLE。

带来源的执行先锁该用户/店铺Cart，再保留原有key→proposal→confirmation→UUID排序Product的相对锁顺序。订单创建、预留库存、精确SKU/数量核验、CartItem删除、Cart版本加一、Confirmation消费、幂等回执和BusinessEvent一同提交或回滚。任一版本或商品集合不匹配保留整个变化后的购物车，回执SKIPPED_CART_CHANGED；原合法购买快照仍可创建订单。成功消费回执CONSUMED。后置数据库时钟检查保留，锁等待不扩大提案有效期。

重复Key/不同Key重放读取已提交回执，不再次消费；即使后来重新加入同一SKU也保留。付款、拒付、取消和到期逻辑未改动，不再次消费或恢复购物车。没有增加表、迁移或依赖，没有修改Payment、Agent或Checkpoint内核。

前端在订单页以及提案页恢复出已完成CHECKOUT回执后，经认证GET原提案和GET /cart更新真实CartProvider及徽标。服务端查询失败显示数量“—”及待核对提示，订单仍按已读取的真实状态展示。独立CartReadTracker保留版本水位和读序号，阻止旧空车响应覆盖已读的新商品，身份切换清除水位。

## 实际验收

| 检查 | 实际结果 | 退出 |
|---|---|---:|
| 全量CI_OFFLINE_CORE后端，Linux ARM64容器/真实PG | 670 passed / 14 skipped / 3既有Jieba warnings | 0 |
| 新购物车PG专项（含2个审查锁交错） | 25 passed | 0 |
| 新测试控制入口事务回滚用例 | 全量中通过，新增1项 | 0 |
| 最终Ruff check / format --check | 通过，189 Python文件格式合规 | 0 |
| 最终前端typecheck / lint / build | 通过 | 0 |
| 最终Vitest | 65 passed（基线55，新增10） | 0 |
| 最终Playwright全量 | 74 passed（基线60，新增14），0 skip/flaky，1 worker/0 retries | 0 |
| Compose config / git diff --check | 通过 | 0 |

14个后端skip没有扩大：13个缺少真实BGE权重的既有规则，1个未公开私有Live原件比较；不是核心事务/恢复/权限跳过。T09恢复/SIGKILL/Thread、T10 Trace、T11并发/Oracle、T12预算/授权/协议在670项全量中执行。没有重新运行封存真实Live任务或模型质量实验。

本轮空库探针实测PostgreSQL17.11、pgvector0.8.7、Alembic0006；重复seed前后均3用户/12商品，官方Checkpoint探针schema清理完成。

后端新增25项与测试控制入口新增1项，共比644基线增加26项。覆盖来源/哈希、变化保护、历史兼容、拒绝/过期/库存与目录错误、删除后的真实事务回滚、不同Key竞争、跨用户/店铺、伪造来源、锁等待跨有效期、提交后真实子进程SIGKILL及重放、支付/拒付/取消/过期不重复消费。独立连接核对终态，不只依赖同Session。

**验证方式限制：完整命令集合分阶段通过，不声称单容器一体化命令退出0。** 只有约1.91GiB、无swap的本机Docker引擎在容器内同时跑浏览器时发生OOM；两个当前镜像全量容器尝试均退出143，完整失败记录保留。最终把浏览器/驱动移至本机Mac，真实FastAPI、Vite、PG和Checkpoint仍在本轮独占容器。Checkpoint严格内部127.0.0.1:55433；宿主55439被原保护拒绝，未修改保护条件。本机headless shell最小探针0帧/点击超时；同版本完整Chromium headless70帧/点击成功，最终74项由后者执行。没有force点击、关闭交互检查、提高重试或新增skip。

最终运行的服务镜像`439ef687302ce2124cbed07a658df89645b9a49e55148c8c37c18de2ef5c7dff`；231个运行源码/后端测试/依赖锁文件与当前worktree哈希匹配，无源码挂载。后端字节与670项执行时一致。四个原E2E脚本仅替换可配置loopback origin，逆变换字节一致，断言数不变。新managed模式固定本轮项目、容器名和端口，默认8001/5174模式保留。180次容器资源采样无OOM停止触发；这不是生产压力测试或保证峰值的采样。

## 数据库证据

[database-evidence.json](database-evidence.json)从真实浏览器操作后的独立psycopg读取投影生成，保留原始事实哈希及14项最终通过状态。合成商品原库存20：

| 场景 | 独立数据库终态 |
|---|---|
| 正常Cart A结算，付款前 | 1订单PENDING_PAYMENT；reserved=1；Cart v2、0行；CONSUMED |
| 随后付款、刷新、重新登录 | 同1订单PAID、1 Payment；reserved=0；Cart仍v2空 |
| 提案后加入B / 修改A / 删除重加A | 订单保留原数量1快照；Cart分别v2数量1+2 / v2数量2 / v3数量2；SKIPPED_CART_CHANGED |
| 提交成功后、响应前再加入商品 | 1订单；Cart v3新增行保留；双击及回执恢复没有再次消费 |
| Multi-Agent独立同SKU下单 | 1订单、27条Checkpoint；原Cart v1数量1完整保留；NOT_APPLICABLE |
| 注入事件写入前失败 | 0订单、0预留、0回执/事件；Cart v1数量1；显式重试才成功 |
| 提交后回包丢失 | GET恢复同一订单/回执；1订单、1预留；Cart v2空；跨用户不能读取/执行 |
| Cart GET失败 | 真实订单已创建；UI数量未知，不把未知当0；后续GET恢复 |

真实PG锁日志保留pid和pg_blocking_pids关系。审查前两种受控交错均复现503，修复后25项通过；真实子进程记录`SIGKILL=-9`后重启200、orders=1、cart_version=3、后来重新加入quantity=2保留。[review.md](review.md)说明一次独立审查的3项Important、1项Minor（执行者升级证据正确性问题）及修复；没有第二次审查或假称审查者重新验收。

## 页面与截图

路径：登录 → 商品加入购物车 → /cart生成提案 → /proposals/{id}独立确认 → /orders/{id}待支付（此时Cart已消费）→ 独立批准模拟付款 → PAID → 刷新重新登录 → /cart仍空。

提案后购物车变化会显示“已保留新增或修改的商品，请核对当前购物车”。Agent独立提案保持购物车。提案页读取旧成功回执也刷新徽标，点击订单链接之前即可核对。只使用合成数据，不发生真实扣款。

- [付款前Cart已消费，待支付订单](screenshots/cart-consumed-before-payment.png)
- [移动端变化后购物车保留](screenshots/cart-preserved-add_b.png)
- [订单已创建但Cart查询未知](screenshots/cart-read-unknown.png)

三张PNG均来自最终74项全量，逐张视觉审查，没有文本/EXIF元数据；原图哈希、尺寸见[screenshots.json](screenshots.json)。VIDEO_NOT_RECORDED。模拟购物闭环具备录制条件；不包括真实模型、真实资金或生产部署验收。

## 命令与复现

实际命令、时间、退出码及原始日志哈希见[command-receipts.json](command-receipts.json)、[verification.json](verification.json)。所有日志留在忽略目录`.t14-p1/`，不提交原始Trace/Checkpoint、模型权重、凭据、PGDATA或浏览器缓存。

本轮后端实际执行：容器内`backend/.venv/bin/python -m pytest --ci-offline-core --strict-markers -ra`（通过），位于受保护的本轮PG55433网络内。静态及前端实际命令：

```sh
backend/.venv/bin/ruff check backend evals scripts
backend/.venv/bin/ruff format --check backend evals scripts
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
docker compose -p agentmall-t14-p1 -f compose.ci.yaml -f compose.cart-local.yaml config --quiet
git diff --check
AGENTMALL_E2E_MANAGED_DEMO=1 NO_PROXY=127.0.0.1,localhost npm --prefix frontend run test:e2e
```

E2E前需独立构建runner并启动本轮PostgreSQL，完整步骤见[DEMO](../../DEMO.md)。最终E2E命令额外指定独立忽略证据目录和输出目录，未注入Key/模型地址；命令回执保留准确参数。重新验证需新建日志目录，不能覆盖本轮证据或重置已有演示数据。

## 保护、清理及限制

[historical-integrity.json](historical-integrity.json)：Private2074跟踪文件、refs/objects/config/index、published297文件/main17f72b8、P0321文件/HEADd8a18b0均与开工前一致；203/1479/1595保护集合不变；R5审核297文件树仍为`8da9a5c18674520dab92195c279a5faf86c7f710fafe7575697ee0309e687508`。另核对P0原42条命令日志、9条CI步骤、12份付款事实及独立demo事实的原有绑定哈希；没有把未绑定的全部旧原始文件追认成逐字节验证。

**运行时限制必须保留：** 开始时存在的P0 demo runner后来消失。用户确认没有手动关闭；本轮没有向它发出停止或重启命令，Docker保留事件查询也无记录，原因UNKNOWN。不能据此断言旧演示运行时完全未受影响，也不能排除共享引擎资源影响。没有擅自重启它。四个原PostgreSQL容器ID、StartedAt、挂载、端口及运行状态核对一致；没有对其写入、迁移、清理或重启。

[resource-cleanup.json](resource-cleanup.json)：本轮临时业务/Checkpoint schemas=0、其他会话=0、Advisory Lock=0后，专属Compose down退出0，专属容器0，仅移除本worktree新建PGDATA；保留所有日志、缓存及本地源码。不删除历史Volume。早期一个21样本资源文件因helper重用文件名被覆盖，只保留已观察末2条摘录；命令/日志仍完整，明确披露，不声称所有原始样本保留。所有失败、错误镜像中止、低堆内存、宿主端口保护和本机shell探针见[failed-attempts.json](failed-attempts.json)。

历史Frozen Manifest/哈希/Live评测没有修改。源码变化使历史Manifest不能描述当前P1版本；[manifest-boundary.json](manifest-boundary.json)逐份列出基线已经存在的不匹配与本轮新增不匹配，状态HISTORICAL_ONLY_NOT_REBOUND；没有重新封存、重授权或声称旧Live成绩验证当前Cart行为。

状态：IMPLEMENTED / REAL_PG_CART_VERIFIED / CHECKPOINT_BROWSER_VERIFIED / OFFLINE_CHECK_SET_VERIFIED。SINGLE_CONTAINER_CI_RESOURCE_BLOCKED；P0_DEMO_EXIT_CAUSE_UNKNOWN；REMOTE_CI_NOT_RUN；LIVE_MODEL_NOT_RUN；PAID_REQUESTS_ZERO。完成T14-P1后停止，发布需单独授权。
