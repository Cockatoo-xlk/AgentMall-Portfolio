# T14-P1 一次独立审查及修复

审查者gpt-6-astra / xhigh，仅只读源码、计划、账本和已有日志；未运行数据库、浏览器或容器，未修改文件，未派发其他审查。初始REQUEST_CHANGES：Critical0、Important3、Minor1。没有第二轮审查。

1. **Important：购物车新增行的外键锁**。原修复先锁Product FOR UPDATE，再锁Cart；CartItem INSERT在Cart锁内还会申请Product外键KEY SHARE。真实PG复现旧A删除后重新加入与下单的环路，响应201/503。修复为仅对带来源的购买使用Cart前置锁，保留原key → proposal → confirmation → UUID排序product的相对顺序，之后消费已锁Cart。
2. **Important：相同来源、不同Key的prepare与execute**。两个prepare都未见提案，后一个持有Cart后进入ON CONFLICT回查提案FOR UPDATE，与execute的反向锁相遇。真实PG复现503。统一Cart前置锁消除该环路，没有删除确认、重放或旧快照契约。
3. **Important：查询失败后的旧GET**。购物车未知时清掉current会丢失版本防线，早先空车v2可覆盖已经观察的B/v3。增加独立版本水位及读取序号，失败保留水位且使旧响应失效；身份切换重置；成功写入使先前读失效。4个Vitest排序/失败测试，以及真实UI“v3已读→新GET失败→旧v2回包”的场景覆盖此路径。
4. **Minor → 执行者升级Important：错误的全CartDTO不变断言**。available是on_hand-reserved，订单预留会合法改变它。原断言会阻断正确验收、甚至诱导错误库存行为，因此按证据正确性修复：分别断言Cart身份、version、SKU数量；可用量用独立SQL库存事实核对。没有把实际业务失败改写为成功。

锁问题专项RED2（503及真实pg_blocking_pids关系）→ 包含修复的购物车专项25 passed；前端65 passed、typecheck/lint/build通过。14项新增浏览器场景通过；最终全量结果以[verification.json](verification.json)为准。没有延期Minor，也没有让审查者重新批准修复。

锁依据除实际复现外，符合[PostgreSQL17锁冲突规则](https://www.postgresql.org/docs/17/explicit-locking.html)及[外键实现](https://raw.githubusercontent.com/postgres/postgres/REL_17_STABLE/src/backend/utils/adt/ri_triggers.c)。

审查者未独立判断或验证的部分全部保留：未亲自运行复现；当时浏览器未通过；原21个资源样本只剩明确标注的末2条摘录；旧P0 runner结束原因UNKNOWN；最终全部历史保护和清理需由执行者核验。未将这些限制写成独立审查通过。
