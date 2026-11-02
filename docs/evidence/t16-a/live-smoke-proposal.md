# T16真实多轮Smoke：仅方案，未授权、未执行

状态：OFFLINE_VERIFIED / NEW_LIVE_PREFLIGHT_AND_OWNER_APPROVAL_REQUIRED。不得由本方案产生授权回执或读取Key。

1. 本轮已完成受控离线时钟准入；实际Live环境仍须重新准入。Mac宿主需保持开盖并使用有时限的进程级保醒，保留前后时钟诊断；休眠或时钟异常时停止，不修改系统时间或全局电源配置。
2. 使用最终本地提交及 `verification.json` 的准确源码指纹；任何修改都重新绑定。创建全新的环境UUID、Session、Policy和持久费用账本，隔离业务/Checkpoint schema，不复用B1/T12授权、Run或账本。
3. 准入时重新只读核验官方模型可用性、非思考Tool Calling与最新高峰价格；当前代码声明deepseek-flash，不把历史价格当现行报价。如果不兼容，先另行离线修复和审查，再申请绑定新指纹的授权。
4. 建议仅一个合成买家的Multi三轮：推荐300元静音键盘 → 改400元无线 → 当前名单第二款、一件、演示宿舍。预先明确独占目录中至少有三款合成无线商品；不得修改旧演示库。购买必须由用户亲自独立确认。只核验唯一PENDING_PAYMENT订单，付款0。
5. 建议待批准上限：人民币5元、18次模型请求、900秒、累计输入1048576 tokens、输出18432 tokens。只是建议，用户确认准确Policy SHA和全部边界后才能生效；预留无法满足、Usage UNKNOWN、Provider错误/超时/格式异常立即安全停止，不自动补费或重跑。
6. Key只通过现有服务器安全加载入口，权限0600，服务只绑定localhost。使用现有 `--describe` 核对最终镜像指纹；不得把Key写入网页、Git、Trace或报告。
7. 保存脱敏Provider元数据、真实工具路径、独立确认、RunEvent、Checkpoint、数据库回执、账本和UNKNOWN状态。三轮用于工程Smoke，不构成模型质量或泛化实验。

本轮真实付费请求0；不得自动执行本方案，不Push、不触发远程Actions。
