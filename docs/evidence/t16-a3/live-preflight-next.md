# 下一次 Live 预检：未授权、未注册

当前BLOCKED_ENVIRONMENT_CLOCK。真实多轮Live为NOT_RUN。

1. 解释/解决LinuxKit在长期负载下的墙钟回退，保持原1ms回退、100ms残差与单调时钟门槛；如需改全局Docker/系统时钟或另建基础设施，先取得相应授权。不能在同一不稳定环境挑选绿色结果。
2. 在独占稳定Linux环境验证最终提交：完整核心pytest、原14项skip、Vitest、Playwright零重试，以及`verify_t16_a3.py`强制真实BGE14项与三轮Mock。当前后审查版导出清理链需要真实运行，旧快照严格复核不能替代。
3. 冻结新的Git SHA和源码指纹，创建新的Environment UUID、Session和独立持久全局账本策略；不得复用R2 Policy、Session、旧Live许可或保留的失败Mock state。
4. 无Key核对固定BGE六文件、pgvector、Checkpoint归属、至少两个合法无线静音候选和localhost边界。复核DeepSeek官方模型/协议和24小时有效价格，再计算调用/输入输出token/人民币/时限预留上限。原¥5/24次/900秒只能作研究起点，不能当授权。
5. 仅提出一次同buyer1、同Thread三Run的明确场景，第三轮需用户独立确认，订单最多1笔PENDING_PAYMENT，付款0。任何额外场景、重跑、预算扩大均需另行授权。
6. 新准入通过且用户明确批准准确绑定之后才允许安全加载真实Key；当前不读取Key、不生成approved=true、不发送请求。

本轮当前生产指纹：`1e54c1f0d0b76ff0a975fbcc9938008336febbf1a1c8c5564253a23f4a901e27`。最终Git SHA由本地交付回执给出。
