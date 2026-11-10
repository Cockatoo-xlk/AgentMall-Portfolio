export type ProviderMode =
  | "LIVE_DEEPSEEK"
  | "MOCK_TRANSPORT"
  | "FIXTURE"
  | "MODEL_DISABLED"
  | "MODEL_ENABLED_UNVERIFIED";
export interface ProviderRuntime {
  mode: ProviderMode;
  model_id?: string | null;
  requests_reserved: number | null;
  valid_responses: number | null;
  responses_observed?: number;
  budget_model_attempts?: number | null;
  unknown_usage_calls?: number;
  usage_state?: string;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | null;
  estimated_upper_cost_cny: string;
  actual_bill_cny: "UNKNOWN" | "NOT_APPLICABLE";
  halted?: string | null;
  limits?: {
    max_model_calls?: number;
    max_cost_cny?: string;
    max_wall_seconds?: number;
    max_input_tokens?: number;
    max_output_tokens?: number;
  };
}
export function parseRuntime(value: unknown): ProviderRuntime {
  const s = value as ProviderRuntime;
  if (
    !s ||
    ![
      "LIVE_DEEPSEEK",
      "MOCK_TRANSPORT",
      "FIXTURE",
      "MODEL_DISABLED",
      "MODEL_ENABLED_UNVERIFIED",
    ].includes(s.mode)
  )
    throw new Error("服务端模型身份无法核验");
  if (
    ["LIVE_DEEPSEEK", "MOCK_TRANSPORT"].includes(s.mode) &&
    s.model_id !== "deepseek-flash"
  )
    throw new Error("服务端模型身份无法核验");
  for (const count of [s.requests_reserved, s.valid_responses])
    if (count !== null && (!Number.isSafeInteger(count) || count < 0))
      throw new Error("服务端用量无法核验");
  if (!["UNKNOWN", "NOT_APPLICABLE"].includes(s.actual_bill_cny))
    throw new Error("费用来源无法核验");
  if (
    s.valid_responses !== null &&
    s.requests_reserved !== null &&
    s.valid_responses > s.requests_reserved
  )
    throw new Error("服务端用量无法核验");
  return s;
}
export function modeLabel(
  status: Pick<ProviderRuntime, "mode" | "valid_responses"> | null,
) {
  if (!status) return "服务端模型身份待核对";
  if (status.mode === "LIVE_DEEPSEEK")
    return status.valid_responses
      ? "Live DeepSeek · 已观察到 Provider 回执"
      : "Live DeepSeek · 已启用，尚无有效 Provider 回执";
  return {
    MOCK_TRANSPORT: "DeepSeek SDK · MockTransport（离线，未调用真实模型）",
    FIXTURE: "Fixture · Fake Model（未调用付费模型）",
    MODEL_DISABLED: "MODEL_DISABLED · 服务端未启用模型",
    MODEL_ENABLED_UNVERIFIED: "模型已注入，Provider 身份未核验",
  }[status.mode];
}
