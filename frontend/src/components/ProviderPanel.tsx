import { useEffect, useState } from "react";
import { useAuth } from "../state/Auth";
import { errorMessage } from "../api/client";
import { modeLabel, parseRuntime } from "../api/providerRuntime";
import type { ProviderRuntime } from "../api/providerRuntime";

export default function ProviderPanel({
  runId,
  revision,
  busy,
}: {
  runId?: string;
  revision: number;
  busy: boolean;
}) {
  const { client } = useAuth();
  const [status, setStatus] = useState<ProviderRuntime | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let reads = 0;
    async function read() {
      try {
        const value = await client.get<unknown>(
          "/agent/runtime" +
            (runId ? `?run_id=${encodeURIComponent(runId)}` : ""),
          controller.signal,
        );
        const checked = parseRuntime(value);
        if (!controller.signal.aborted) {
          setStatus(checked);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setStatus(null);
          setError(errorMessage(e));
        }
      }
      if (!controller.signal.aborted && busy && ++reads < 24)
        timer = setTimeout(() => void read(), 5000);
    }
    void read();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [client, runId, revision, busy]);
  return (
    <section
      className="panel stack"
      aria-label="服务端模型与预算"
      data-testid="provider-panel"
    >
      <strong data-testid="provider-mode">{modeLabel(status)}</strong>
      {error && (
        <p className="notice warning">
          模式或用量未核验：{error}；不据此宣告成功或重新发送请求。
        </p>
      )}
      {status && (
        <>
          <p>
            模型：{status.model_id ?? "未启用"} · SDK预留尝试{" "}
            {status.requests_reserved ?? "UNKNOWN"} 次 · 有效Provider回执{" "}
            {status.valid_responses ?? "UNKNOWN"} 次
          </p>
          {status.budget_model_attempts != null && (
            <p>
              工作流模型预算计次 {status.budget_model_attempts}（Fixture
              计次不代表真实付费调用）
            </p>
          )}
          <p>
            Token Usage：{status.usage_state ?? "UNKNOWN"} · 已核验输入{" "}
            {status.usage?.input_tokens ?? "UNKNOWN"} / 输出{" "}
            {status.usage?.output_tokens ?? "UNKNOWN"} / 合计{" "}
            {status.usage?.total_tokens ?? "UNKNOWN"}；未知用量{" "}
            {status.unknown_usage_calls ?? "UNKNOWN"} 次
          </p>
          <p>
            费用预留/估算上界：{status.estimated_upper_cost_cny} CNY ·
            实际平台账单：{status.actual_bill_cny}
          </p>
          {status.limits && (
            <p>
              本地会话上限：{status.limits.max_model_calls} 次请求 /{" "}
              {status.limits.max_cost_cny} CNY /{" "}
              {status.limits.max_wall_seconds} 秒。恢复和重启不会重置账本。
            </p>
          )}
          {status.halted && (
            <p className="notice error" role="alert">
              已安全停止：{status.halted}
              。不自动补发或追加预算；请核对已持久化结果。
            </p>
          )}
          <small>
            身份和计数来自认证后的服务端状态。预留尝试可能尚未到达Provider，估算不等于实际账单；页面不展示密钥、原始对话或内部推理。
          </small>
        </>
      )}
    </section>
  );
}
