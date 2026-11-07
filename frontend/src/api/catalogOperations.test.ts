import { describe, it, expect } from "vitest";
import {
  validateImportFile,
  draftActions,
  emptyProduct,
} from "./catalogOperations";
describe("merchant catalog command boundaries", () => {
  it("accepts bounded CSV and JSON only", () => {
    expect(validateImportFile({ name: "demo.CSV", size: 100 })).toBe("csv");
    expect(validateImportFile({ name: "demo.json", size: 131072 })).toBe(
      "json",
    );
    for (const f of [
      { name: "a.json", size: 131073 },
      { name: "a.json", size: 0 },
      { name: "a.exe", size: 1 },
    ])
      expect(() => validateImportFile(f)).toThrow();
  });
  it("review and publication remain distinct explicit actions", () => {
    expect(draftActions("DRAFT")).toEqual({
      edit: true,
      submit: true,
      review: false,
      publish: false,
    });
    expect(draftActions("READY_FOR_REVIEW")).toEqual({
      edit: false,
      submit: false,
      review: true,
      publish: false,
    });
    expect(draftActions("APPROVED")).toEqual({
      edit: false,
      submit: false,
      review: false,
      publish: true,
    });
    expect(draftActions("PUBLISHED")).toEqual({
      edit: false,
      submit: false,
      review: false,
      publish: false,
    });
    expect(draftActions("REJECTED").submit).toBe(true);
  });
  it("manual creation starts with unknown category and no invented specs", () => {
    expect(emptyProduct.category).toBeNull();
    expect(emptyProduct.attributes).toEqual({});
  });
});
