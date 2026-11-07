import type { Category } from "./types";
export const catalogBase = "/merchant/catalog";
export interface ProductData {
  name: string;
  category: Category | null;
  description: string;
  attributes: Record<string, string | string[]>;
  price_cents: number;
  on_hand: number;
}
export interface MerchantProduct extends ProductData {
  id: string;
  catalog_version: number;
  reserved: number;
  available: number;
  active: boolean;
  index_status: string;
}
export type DraftStatus =
  "DRAFT" | "READY_FOR_REVIEW" | "APPROVED" | "REJECTED" | "PUBLISHED";
export interface CatalogDraft {
  id: string;
  version: number;
  status: DraftStatus;
  data: ProductData;
  source: {
    kind: string;
    original?: unknown;
    row?: number;
    catalog_version?: number;
  };
  extraction: {
    mode?: string;
    status?: string;
    error_code?: string;
    uncertain?: string[];
    evidence?: {
      field: string;
      value: string;
      quote: string;
      start: number;
      end: number;
    }[];
    category_quote?: string;
  };
  extraction_attempts: number;
  target_product_id: string | null;
  target_version: number | null;
  approved_by: string | null;
  approved_at: string | null;
  published_product_id: string | null;
  index_job_id: string | null;
  history: { state?: string; version?: number; reason?: string }[];
}
export interface CatalogImport {
  id: string;
  status: string;
  format: string;
  source_hash: string;
  parser_mode: string;
  draft_ids: string[];
  errors: { row: number; code: string }[];
}
export interface IndexJob {
  id: string;
  product_id: string;
  status: string;
  effective_status: string;
  requested_version: number;
  current_version: number;
  attempts: number;
  error_code: string | null;
}
export const emptyProduct: ProductData = {
  name: "",
  category: null,
  description: "",
  attributes: {},
  price_cents: 0,
  on_hand: 0,
};
export function validateImportFile(file: Pick<File, "name" | "size">) {
  if (file.size > 131072 || file.size === 0)
    throw new Error("文件需为1–128 KiB的CSV或JSON文本。");
  if (!/\.(csv|json)$/i.test(file.name))
    throw new Error("仅支持CSV或JSON文件。");
  return file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
}
export function draftActions(status: DraftStatus) {
  return {
    edit: status === "DRAFT" || status === "REJECTED",
    submit: status === "DRAFT" || status === "REJECTED",
    review: status === "READY_FOR_REVIEW",
    publish: status === "APPROVED",
  };
}
