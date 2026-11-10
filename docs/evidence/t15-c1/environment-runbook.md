# 隔离时钟环境的本地复现边界

本轮使用已有Colima，不安装系统服务、不重启default、不更改global时钟同步。以下是工程复现方法，不是GitHub/真实模型授权。

1. 先核对当前context和既有实例。名称已存在时检查归属，不能覆盖或重置旧实例。确认独立端口实际可bind；仅靠lsof空列表不足（本轮8021实际EADDRINUSE但lsof无结果）。
2. 已有CLI创建新的VZ实例，明确不切换当前context、不读模板、不注入SSH agent、不改用户SSH配置，只挂载本工作区：

```sh
colima start agentmall-t15-c1 --activate=false --template=false --ssh-config=false --ssh-agent=false --vm-type vz --arch aarch64 --cpus 2 --memory 4 --disk 12 --runtime docker --network-address=false --mount '<WORKTREE>:w'
```

真实执行记录以[command-receipts.json](command-receipts.json)为准，`<WORKTREE>`是脱敏占位符。所有Docker调用都显式`--context colima-agentmall-t15-c1`，不执行context use。锁定PG/Backend镜像可本地save/load转移；若没有原缓存，应在该context从锁文件按现有Dockerfile构建，不借用其他项目。

3. 新独占Compose项目使用本目录自己的PGDATA、宿主PG55444、VM内API8021、内部PG55433；runner1536MiB、PG384MiB。宿主8021冲突后仅为自己的VM添加127.0.0.1:8022→VM127.0.0.1:8021转发，不停止未知监听者。Vite5191的API target与Playwright API_ORIGIN统一8022。
4. 预先冻结时钟准入阈值。60秒同时记录host/guest wall_ns、monotonic_ns及增量，PING给出偏移区间；不准入任何超过1ms后退、单调倒退、超过100ms残差或偏移中值变化。旧VM失败则排除，不重复全量碰绿色。
5. 通过后仍持续观测完整测试窗口。运行原Backend CI_OFFLINE_CORE、前端typecheck/lint/Vitest/build，再完整87项Playwright。私有配置只改启动器/端口/生命周期和单独协议前置检查，workers1/retries0，测试文件/断言/skip不改。不用last-failed代替完整验收。
6. 单独协议前置只使用本轮合成账号/专属测试签名串，内存中构造未来iat/nbf及过期exp，原API必须拒绝；不记录JWT/签名/Key/Cookie。核对Date（秒粒度缓存）与数据库X-Server-Time、正常期限和过期拒绝。全局准备失败不是执行过87个用例，必须单列。
7. 按每个阶段保存真实退出码、单调耗时和原始日志SHA。异常处理也不能把带秘密的配置对象直接交给验证器错误回显。原件只在忽略私有目录，不上传原日志或测试签名材料。
8. 全部参与者结束后独立连接检查test_/cp_ schema、会话、Advisory Lock为0，只down本轮项目（不-v），取消自己的转发、停止自己的VM。保留磁盘与证据，重新使用前再次准入。原default仍有问题，不因本轮新VM通过而宣称全机时钟已修复。

当前源码仍未重新Live；B1仅为旧617cdf29历史Smoke。正式远程CI/发布必须再获准确SHA授权。
