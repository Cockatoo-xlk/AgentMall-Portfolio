import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, errorMessage } from "../api/client";
import { money } from "../api/format";
import { categoryLabels as CATEGORY_LABELS } from "../api/catalog";
import type { Category, Page } from "../api/types";
import {
  catalogBase as base,
  emptyProduct,
  validateImportFile,
  draftActions,
} from "../api/catalogOperations";
import type {
  CatalogDraft,
  CatalogImport,
  MerchantProduct,
  IndexJob,
  ProductData,
} from "../api/catalogOperations";
import { useAuth } from "../state/Auth";
import { useMounted, useResource } from "../state/useResource";

function useCatalogCommand(refresh: () => void) {
  const { client } = useAuth();
  const alive = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const pending = useRef<{
    path: string;
    method: string;
    body: object & { request_id: string };
    done?: (result: unknown) => void;
  } | null>(null);
  const locked = useRef(false);
  async function execute() {
    if (locked.current || !pending.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const request = pending.current;
    try {
      const value = await client.request<unknown>(
        base + request.path,
        request.method,
        request.body,
      );
      if (!alive.current) return;
      request.done?.(value);
      pending.current = null;
      setUnknown(false);
      refresh();
    } catch (error) {
      if (!alive.current) return;
      setError(errorMessage(error));
      if (error instanceof ApiError && error.ambiguous) setUnknown(true);
      else {
        pending.current = null;
        setUnknown(false);
        refresh();
      }
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function recover() {
    if (locked.current || !pending.current) return;
    locked.current = true;
    setBusy(true);
    try {
      const value = await client.get<{ result: unknown }>(
        base + "/commands/" + pending.current.body.request_id,
      );
      if (!alive.current) return;
      pending.current.done?.(value.result);
      pending.current = null;
      setUnknown(false);
      setError("");
      refresh();
    } catch (error) {
      if (alive.current) setError(errorMessage(error));
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return {
    busy: busy || unknown,
    error,
    unknown,
    recover,
    retry: execute,
    run(
      path: string,
      body: object,
      done?: (result: unknown) => void,
      method = "POST",
    ) {
      if (locked.current || pending.current) return;
      pending.current = {
        path,
        method,
        body: { ...body, request_id: crypto.randomUUID() },
        done,
      };
      void execute();
    },
  };
}

export default function MerchantCatalog() {
  const [tab, setTab] = useState<
    "products" | "drafts" | "imports" | "index-jobs"
  >("products");
  const [cursor, setCursor] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [format, setFormat] = useState<"csv" | "json">("json");
  const [content, setContent] = useState("");
  const [assist, setAssist] = useState(true);
  const [inputError, setInputError] = useState("");
  const query = new URLSearchParams({ limit: "12" });
  if (cursor.at(-1)) query.set("cursor", cursor.at(-1)!);
  if (status) query.set("status", status);
  if (category && tab === "products") query.set("category", category);
  const list = useResource<
    Page<MerchantProduct | CatalogDraft | CatalogImport | IndexJob>
  >(`${base}/${tab}?${query}`);
  const meta = useResource<{
    parser_mode: string;
    embedding_model: string | null;
  }>(base + "/meta");
  const draft = useResource<CatalogDraft>(
    selected ? `${base}/drafts/${selected}` : null,
  );
  const command = useCatalogCommand(() => {
    list.reload();
    draft.reload();
  });
  function changeTab(value: typeof tab) {
    setTab(value);
    setCursor([]);
    setStatus("");
  }
  function open(value: unknown) {
    setSelected((value as CatalogDraft).id);
    setManual(false);
    changeTab("drafts");
  }
  async function fileChanged(file: File | undefined) {
    if (!file) return;
    try {
      const type = validateImportFile(file);
      setContent(await file.text());
      setFormat(type);
      setInputError("");
    } catch (error) {
      setInputError(errorMessage(error));
    }
  }
  return (
    <section className="catalog-operations">
      <div className="notice">
        结构化辅助：<strong>{meta.data?.parser_mode ?? "加载中"}</strong> ·
        Embedding：{meta.data?.embedding_model ?? "未配置"}
        。模型仅建议草稿；商家审核与正式发布为独立操作。Mock不代表真实LLM准确率。
      </div>
      {command.error && (
        <p role="alert" className="error-text">
          {command.error}
        </p>
      )}
      {command.unknown && (
        <div className="notice">
          请求结果未知，请先核对回执。刷新只读取记录，不会自动提交。
          <button
            className="button secondary"
            disabled={command.busy && !command.unknown}
            onClick={() => void command.recover()}
          >
            只读核对回执
          </button>
          <button
            className="button secondary"
            onClick={() => void command.retry()}
          >
            以原request_id重试
          </button>
        </div>
      )}
      <div className="inline-actions">
        {(["products", "drafts", "imports", "index-jobs"] as const).map(
          (t, i) => (
            <button
              key={t}
              className={`button ${tab === t ? "primary" : "secondary"}`}
              onClick={() => changeTab(t)}
            >
              {["本店商品", "商品草稿", "导入任务", "索引任务"][i]}
            </button>
          ),
        )}
        <button
          className="button secondary"
          disabled={command.busy}
          onClick={() => {
            setManual(true);
            setSelected(null);
          }}
        >
          创建商品草稿
        </button>
      </div>
      <details>
        <summary>批量导入CSV / JSON（最多50行、128 KiB）</summary>
        <p className="muted">
          字段：name、category、description、price_cents（整数分）、on_hand、attributes（JSON对象）。资料只作为数据，不执行内容指令。导入不会直接上架。
        </p>
        <div className="field">
          <label htmlFor="catalog-file">商品资料文件</label>
          <input
            id="catalog-file"
            type="file"
            accept=".csv,.json"
            onChange={(e) => void fileChanged(e.target.files?.[0])}
          />
        </div>
        <div className="field">
          <label htmlFor="import-format">导入格式</label>
          <select
            id="import-format"
            value={format}
            onChange={(e) => setFormat(e.target.value as "csv" | "json")}
          >
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="import-content">商品资料文本</label>
          <textarea
            id="import-content"
            rows={5}
            maxLength={131072}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </div>
        <label>
          <input
            type="checkbox"
            checked={assist}
            onChange={(e) => setAssist(e.target.checked)}
          />
          使用当前模式辅助提取（结果仍需商家确认）
        </label>
        {inputError && <p role="alert">{inputError}</p>}
        <button
          className="button primary"
          disabled={command.busy || !content}
          onClick={() => {
            if (new TextEncoder().encode(content).length > 131072) {
              setInputError("UTF-8内容超过128 KiB");
              return;
            }
            command.run("/imports", { format, content, assist }, () =>
              changeTab("imports"),
            );
          }}
        >
          导入为草稿
        </button>
      </details>
      {manual && (
        <ProductEditor
          initial={emptyProduct}
          busy={command.busy}
          save={(data) => command.run("/drafts", { data }, open)}
        />
      )}
      {draft.data && (
        <section className="panel" aria-label="商品草稿详情">
          <h2>
            {draft.data.data.name} · {draft.data.status} · v{draft.data.version}
          </h2>
          <p>
            草稿ID：{draft.data.id} · 来源：{draft.data.source.kind} ·
            原商品版本：{draft.data.target_version ?? "新商品"}
          </p>
          <p>
            辅助模式：{draft.data.extraction.mode ?? "未提取"} /{" "}
            {draft.data.extraction.status ?? "未提取"} · 待确认：
            {draft.data.extraction.uncertain?.join("、") ||
              "请人工核对全部字段"}
          </p>
          {draft.data.extraction.error_code && (
            <p role="alert">{draft.data.extraction.error_code}</p>
          )}
          <details>
            <summary>原始输入与规格依据</summary>
            <pre>
              {JSON.stringify(
                draft.data.source.original ?? draft.data.source,
                null,
                2,
              )}
            </pre>
            <p>
              品类依据：
              {draft.data.extraction.category_quote ?? "商家填写 / 未知"}
            </p>
            {draft.data.extraction.evidence?.map((e) => (
              <p key={e.field}>
                {e.field} = {e.value}；原文「{e.quote}」[{e.start}, {e.end})
              </p>
            ))}
          </details>
          <ProductEditor
            key={`${draft.data.id}:${draft.data.version}`}
            initial={draft.data.data}
            busy={command.busy || !draftActions(draft.data.status).edit}
            save={(data) =>
              command.run(
                `/drafts/${selected}`,
                { expected_version: draft.data!.version, data },
                undefined,
                "PATCH",
              )
            }
          />
          <div className="inline-actions">
            {["READY_FOR_REVIEW", "APPROVED"].includes(draft.data.status) && (
              <button
                className="button secondary"
                disabled={command.busy}
                onClick={() =>
                  command.run(
                    `/drafts/${selected}`,
                    {
                      expected_version: draft.data!.version,
                      data: draft.data!.data,
                    },
                    undefined,
                    "PATCH",
                  )
                }
              >
                返回编辑（撤销审核）
              </button>
            )}
            {draftActions(draft.data.status).edit && (
              <button
                className="button secondary"
                disabled={command.busy || draft.data.extraction_attempts >= 3}
                onClick={() =>
                  command.run(`/drafts/${selected}/extract`, {
                    expected_version: draft.data!.version,
                  })
                }
              >
                辅助整理为草稿
              </button>
            )}
            {draftActions(draft.data.status).submit && (
              <button
                className="button primary"
                disabled={command.busy}
                onClick={() =>
                  command.run(`/drafts/${selected}/submit`, {
                    expected_version: draft.data!.version,
                  })
                }
              >
                提交审核
              </button>
            )}
            {draftActions(draft.data.status).review && (
              <Review
                key={draft.data.id + ":" + draft.data.version}
                busy={command.busy}
                approve={() =>
                  command.run(`/drafts/${selected}/approve`, {
                    expected_version: draft.data!.version,
                    reviewed: true,
                  })
                }
                reject={(reason) =>
                  command.run(`/drafts/${selected}/reject`, {
                    expected_version: draft.data!.version,
                    reason,
                  })
                }
              />
            )}
            {draftActions(draft.data.status).publish && (
              <button
                className="button primary"
                disabled={command.busy}
                onClick={() =>
                  command.run(`/drafts/${selected}/publish`, {
                    expected_version: draft.data!.version,
                  })
                }
              >
                正式发布商品
              </button>
            )}
          </div>
          {draft.data.status === "PUBLISHED" && (
            <div className="notice">
              已发布商品 {draft.data.published_product_id}
              。索引需单独执行；请在「索引任务」检查当前检索状态。草稿已冻结，修改需从商品创建新修订。
            </div>
          )}
          <p>
            {draft.data.history
              .map((h) =>
                h.state ? `${h.state} v${h.version}` : `拒绝原因：${h.reason}`,
              )
              .join(" → ")}
          </p>
        </section>
      )}
      <div className="inline-actions">
        <div className="field">
          <label htmlFor="catalog-status">列表状态筛选</label>
          <input
            id="catalog-status"
            value={status}
            placeholder={
              tab === "products" ? "ACTIVE / INACTIVE" : "DRAFT / PUBLISHED 等"
            }
            onChange={(e) => {
              setStatus(e.target.value);
              setCursor([]);
            }}
          />
        </div>
        {tab === "products" && (
          <div className="field">
            <label htmlFor="catalog-category">品类筛选</label>
            <select
              id="catalog-category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setCursor([]);
              }}
            >
              <option value="">全部</option>
              {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        )}
        <button
          className="button secondary"
          onClick={() => {
            list.reload();
            draft.reload();
          }}
        >
          刷新服务端记录
        </button>
      </div>
      {(list.error || draft.error) && (
        <p role="alert">{list.error || draft.error}</p>
      )}
      {list.loading && <p role="status">读取中…</p>}
      <div className="catalog-operation-grid">
        {list.data?.items.map((item) => (
          <article className="panel" key={item.id}>
            {tab === "products" &&
              (() => {
                const p = item as MerchantProduct;
                return (
                  <>
                    <h3>{p.name}</h3>
                    <p>
                      {money(p.price_cents)} ·{" "}
                      {p.category ? CATEGORY_LABELS[p.category] : "未知"} · v
                      {p.catalog_version}
                    </p>
                    <p>
                      库存{p.on_hand} · 已预留{p.reserved} · 可用{p.available} ·{" "}
                      {p.active ? "上架" : "下架"}
                    </p>
                    <p>索引：{p.index_status}</p>
                    <button
                      className="button secondary"
                      disabled={command.busy}
                      onClick={() =>
                        command.run(
                          `/products/${p.id}/draft`,
                          { expected_version: p.catalog_version },
                          open,
                        )
                      }
                    >
                      创建修订草稿
                    </button>
                    {p.active && (
                      <button
                        className="button secondary"
                        disabled={command.busy}
                        onClick={() =>
                          command.run(`/products/${p.id}/deactivate`, {
                            expected_version: p.catalog_version,
                          })
                        }
                      >
                        下架商品
                      </button>
                    )}
                  </>
                );
              })()}
            {tab === "drafts" &&
              (() => {
                const d = item as CatalogDraft;
                return (
                  <>
                    <h3>{d.data.name}</h3>
                    <p>
                      {d.status} · v{d.version} · {money(d.data.price_cents)}
                    </p>
                    <button
                      className="button secondary"
                      onClick={() => {
                        setSelected(d.id);
                        setManual(false);
                      }}
                    >
                      查看 / 审核草稿
                    </button>
                  </>
                );
              })()}
            {tab === "imports" &&
              (() => {
                const j = item as CatalogImport;
                return (
                  <>
                    <h3>导入 {j.status}</h3>
                    <p>
                      {j.parser_mode} · {j.format} · {j.id}
                    </p>
                    {j.errors.map((e, i) => (
                      <p role="status" key={i}>
                        第{e.row}行：{e.code}
                      </p>
                    ))}
                    {j.draft_ids.map((id, i) => (
                      <button
                        className="button secondary"
                        key={id}
                        onClick={() => {
                          setSelected(id);
                          changeTab("drafts");
                        }}
                      >
                        打开第{i + 1}个草稿
                      </button>
                    ))}
                  </>
                );
              })()}
            {tab === "index-jobs" &&
              (() => {
                const j = item as IndexJob;
                return (
                  <>
                    <h3>索引 {j.effective_status}</h3>
                    <p>
                      商品：{j.product_id} · 目标v{j.requested_version} / 当前v
                      {j.current_version} · 尝试{j.attempts}/3
                    </p>
                    {j.error_code && <p>{j.error_code}</p>}
                    <button
                      className="button secondary"
                      disabled={
                        command.busy ||
                        j.attempts >= 3 ||
                        ["SUCCEEDED", "STALE"].includes(j.effective_status)
                      }
                      onClick={() => command.run(`/index-jobs/${j.id}/run`, {})}
                    >
                      执行 / 重试索引
                    </button>
                  </>
                );
              })()}
          </article>
        ))}
      </div>
      {!list.loading && list.data?.items.length === 0 && <p>当前没有记录。</p>}
      <div className="inline-actions">
        <button
          className="button secondary"
          disabled={!cursor.length}
          onClick={() => setCursor((c) => c.slice(0, -1))}
        >
          上一页
        </button>
        <span>第{cursor.length + 1}页</span>
        <button
          className="button secondary"
          disabled={!list.data?.next_cursor}
          onClick={() => setCursor((c) => [...c, list.data!.next_cursor!])}
        >
          下一页
        </button>
      </div>
    </section>
  );
}

function ProductEditor({
  initial,
  busy,
  save,
}: {
  initial: ProductData;
  busy: boolean;
  save: (value: ProductData) => void;
}) {
  const [value, setValue] = useState(initial);
  const [attributes, setAttributes] = useState(
    JSON.stringify(initial.attributes, null, 2),
  );
  const [error, setError] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const attrs: unknown = JSON.parse(attributes);
      if (
        !attrs ||
        typeof attrs !== "object" ||
        Array.isArray(attrs) ||
        Object.entries(attrs).some(
          ([k, v]) =>
            typeof v !== "string" &&
            !(
              k === "connection_capabilities" &&
              Array.isArray(v) &&
              v.length > 0 &&
              v.length <= 2 &&
              new Set(v).size === v.length &&
              v.every((c) => c === "wired" || c === "wireless")
            ),
        )
      )
        throw new Error(
          "规格必须为规格JSON对象（connection_capabilities可为wired/wireless数组）",
        );
      save({
        ...value,
        attributes: attrs as Record<string, string | string[]>,
      });
      setError("");
    } catch (error) {
      setError(errorMessage(error));
    }
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <legend>商品信息（价格单位：分）</legend>
        <p className="muted">
          编辑后请先保存草稿；审核和发布以服务端已保存快照为准。
        </p>
        <div className="catalog-operation-grid">
          <div className="field">
            <label>
              商品名称
              <input
                required
                maxLength={200}
                value={value.name}
                onChange={(e) => setValue({ ...value, name: e.target.value })}
              />
            </label>
          </div>
          <div className="field">
            <label>
              商品品类
              <select
                value={value.category ?? ""}
                onChange={(e) =>
                  setValue({
                    ...value,
                    category: (e.target.value || null) as Category | null,
                  })
                }
              >
                <option value="">待确认</option>
                {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field">
            <label>
              单价（分）
              <input
                type="number"
                min={0}
                max={100000000}
                required
                value={value.price_cents}
                onChange={(e) =>
                  setValue({ ...value, price_cents: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <div className="field">
            <label>
              总库存
              <input
                type="number"
                min={0}
                max={1000000}
                required
                value={value.on_hand}
                onChange={(e) =>
                  setValue({ ...value, on_hand: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <div className="field">
            <label>
              商品描述
              <textarea
                maxLength={4000}
                value={value.description}
                onChange={(e) =>
                  setValue({ ...value, description: e.target.value })
                }
              />
            </label>
          </div>
          <div className="field">
            <label>
              规格JSON
              <textarea
                rows={5}
                value={attributes}
                onChange={(e) => setAttributes(e.target.value)}
              />
            </label>
          </div>
        </div>
        {error && <p role="alert">{error}</p>}
        <button className="button secondary" type="submit">
          保存草稿
        </button>
      </fieldset>
    </form>
  );
}
function Review({
  busy,
  approve,
  reject,
}: {
  busy: boolean;
  approve: () => void;
  reject: (reason: string) => void;
}) {
  const [checked, setChecked] = useState(false);
  const [reason, setReason] = useState("");
  return (
    <div>
      <label>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
        />
        我已核对原始资料、所有规格、价格和库存，包括待确认字段
      </label>
      <button
        className="button primary"
        disabled={busy || !checked}
        onClick={approve}
      >
        审核通过（不自动上架）
      </button>
      <div className="field">
        <label>
          拒绝原因
          <input
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      </div>
      <button
        className="button secondary"
        disabled={busy || !reason.trim()}
        onClick={() => reject(reason)}
      >
        拒绝草稿
      </button>
    </div>
  );
}
