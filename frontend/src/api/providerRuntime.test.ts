import { describe, expect, it } from "vitest";
import { modeLabel, parseRuntime } from "./providerRuntime";

describe("server provider identity and safe usage", () => {
  it("does not invent Live or Fixture identity without a server response", () => {
    expect(modeLabel(null)).toContain("待核对");
  });
  it("labels the actual SDK mock explicitly without claiming paid inference", () => {
    expect(modeLabel({ mode: "MOCK_TRANSPORT", valid_responses: 2 })).toContain(
      "MockTransport",
    );
    expect(
      modeLabel({ mode: "MOCK_TRANSPORT", valid_responses: 2 }),
    ).not.toContain("Live DeepSeek");
  });
  it("distinguishes configured Live from observed provider responses", () => {
    expect(modeLabel({ mode: "LIVE_DEEPSEEK", valid_responses: 0 })).toContain(
      "尚无",
    );
    expect(modeLabel({ mode: "LIVE_DEEPSEEK", valid_responses: 1 })).toContain(
      "Provider 回执",
    );
  });
  it("shows Fixture and MODEL_DISABLED from server enums", () => {
    expect(modeLabel({ mode: "FIXTURE", valid_responses: 0 })).toContain(
      "Fixture",
    );
    expect(modeLabel({ mode: "MODEL_DISABLED", valid_responses: 0 })).toContain(
      "MODEL_DISABLED",
    );
  });
  it("rejects unrecognized or inconsistent identity instead of trusting a frontend flag", () => {
    expect(() => parseRuntime({ mode: "LIVE", model_id: "fake" })).toThrow();
    expect(() =>
      parseRuntime({
        mode: "LIVE_DEEPSEEK",
        model_id: "fake",
        requests_reserved: 1,
        valid_responses: 1,
        actual_bill_cny: "UNKNOWN",
      }),
    ).toThrow();
  });
  it("keeps unknown usage and actual billing separate from upper cost estimates", () => {
    const status = parseRuntime({
      mode: "MOCK_TRANSPORT",
      model_id: "deepseek-flash",
      requests_reserved: 2,
      valid_responses: 1,
      unknown_usage_calls: 1,
      usage_state: "UNKNOWN",
      usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
      estimated_upper_cost_cny: "2.12",
      actual_bill_cny: "UNKNOWN",
      halted: "PROVIDER_USAGE_UNKNOWN",
    });
    expect(status.actual_bill_cny).toBe("UNKNOWN");
    expect(status.unknown_usage_calls).toBe(1);
    expect(status.estimated_upper_cost_cny).toBe("2.12");
  });
});
