# 商品检索文档与重建

商品文档由可信目录记录生成：名称、英文品类、确定性中文品类名、描述和原始属性。
品类词汇仅有 `keyboard → 键盘`、`mouse → 鼠标`、`headphones → 耳机`。
未知品类不猜测标签；不改商品名称、连接标签或性能事实。

这样通用查询“键盘”能命中词法召回，仍须经过当前店铺、上架、库存、预算、
静音与连接能力过滤。RRF、BGE 的 0.45 相似度门槛和工具级二次校验保持原状。
没有空结果兜底商品，也没有修改 MockTransport 的查询。

## 旧索引兼容

商品使用独立文档标识 `jieba-0.42.1-search-nfkc-v1:catalog-zh-v2`，保存在现有
`product_search.tokenizer_version` 字段中。政策 chunk 仍使用原 tokenizer 标识，
没有数据库结构迁移，也没有重新标记历史政策或修改 Frozen Manifest。

旧商品索引不会被自动视为新版。升级源码后，管理员必须对经过授权的准确数据库、
Schema 和店铺显式调用 `index_products(session, store_id, encoder)`，使用真实本地
`LocalEncoder`，并由调用者在事务中提交。该入口锁定商品行，原子更新文档哈希、
向量、词法索引和文档标识；目录未变化时保留原 Catalog Version。
重复重建覆盖同一 Product ID，不新增 SKU。

未重建的旧文档、Catalog Version 不一致的记录不会被召回。召回后还会重读当前
商品和索引身份，再重新计算当前商品文档哈希，避免过期索引冒充最新商品事实。

本地验证不会自动重建任何旧演示库。已有 `evals.rag_local` 入口面向其独占的
public Schema，不能当作任意持久 Playground Schema 的升级工具。

## 显式离线验证

在自有 Linux 测试容器中配置专属 `127.0.0.1:55433/agentmall_test` 数据库及
`AGENTMALL_TEST_DATABASE_URL`，挂载固定 Revision 的六个 BGE 文件到 `.models/`。
不传入 Provider Key，保持外部模型网络禁用。

```bash
python scripts/verify_t16_a3.py \
  --output .t13/outputs/t16-a3-check \
  --state-dir .playground/t16-a3-fresh-check
```

两个路径均应为全新路径；已有 state 将在数据库访问前被拒绝。验证器只使用
受控 MockTransport，创建新的带归属标记的业务/Checkpoint Schema 和 Mock 账本。
它必跑真实 BGE 检索及固定三轮场景，无模型缺失 skip。

独立 READ ONLY 数据库快照和官方 Checkpoint 读取结果保存为 JSON，文件、SHA
及目录项均同步、回读验证，并重新执行 Oracle 后才允许 DROP 本次拥有的 Schema。
导出或目录同步失败保留 Schema；清理中断的结果标记 UNKNOWN，不能盲目恢复。
日志、环境文件和 Mock 账本是私有本地证据，不能整体提交。

默认核心 CI 继续保留原 14 项跳过规则；该显式真实 BGE 验证单独报告，
不冒充真实 DeepSeek 或付费准入。源码变化后必须重新进行 B0 环境/价格/预算绑定，
历史 Policy 和 Session 不能沿用。
