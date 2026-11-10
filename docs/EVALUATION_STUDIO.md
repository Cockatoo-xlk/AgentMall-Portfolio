# Agent Evaluation Studio

打开前端的 `/engineering/evals`，可查看配对比较、失败详情及数据来源。页面读取静态 JSON，面向本地工程展示。

## 导出已有评测

从仓库根目录执行。输入目录需要现有评测器写出的 `schedule.json` 和逐 Episode 文件。输出位置应在原始证据目录之外。

```sh
eval_dir=evals/results/YOUR_RUN_ID
PYTHONPATH=. backend/.venv/bin/python -m evals.studio "$eval_dir" \
  > /tmp/agentmall-studio-v1.json
```

可加 `--reviewed-live docs/evidence/live-pilots.json` 单独附上已经审查的历史汇总。导出器使用 `scheduled_rows()` 处理缺失的计划项，用 `paired_report()` 计算配对指标。缺失文件保留为失败的 `NOT_RUN` 行，计划分母维持原值。重复或不完整的配对计划会被拒绝。

如有原始执行回执，可在输入目录提供独立的 `studio-provenance.json`，字段为 `git_commit`、`started_at`、`completed_at` 及 `environment` 中的 `os`、`architecture`、`python`、`postgresql`。Git SHA 和时间来自执行回执。旧产物缺少这些字段时显示 `UNKNOWN`。审核脱敏结果后，再把 JSON 放到 `frontend/public/evals/studio-v1.json`。

## 当前样本

静态样本 `v24-dev-fixture` 使用 Git 提交 `8cb788dea4e02d763faeafbfad0fc7f639d91868` 的归档源码，通过原 `run_episode()` 和 `schedule_pairs()` 在独立 PostgreSQL 17 环境运行开发集子集。每任务每架构一次，共 18 个 Episode。样本包含推荐、购买、订单查询、售后、组合任务、安全、恢复及异常路径。具体 Task ID 和数据集 SHA-256 见导出 JSON。模型和向量均使用 Fixture，样本未封存。

P50/P95 取已有 `machine_seconds`，调用数来自已有运行计数。业务副作用只比较 Oracle 快照中的新增记录，不包含实体 ID。通过率与终态分开显示，符合预期的 `PARTIAL` 可以通过 Oracle。Bootstrap 保留同任务的重复运行，区间只描述此批样本。两次历史 Live 只展示已审查汇总和已公开失败，当前 V2 的真实模型评测为 `NOT_RUN`。
