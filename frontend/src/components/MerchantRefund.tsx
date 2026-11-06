import { formatDate, money } from '../api/format'
import type {
  AfterSalesCase,
  Confirmation,
  MockRefundProposal,
  Proposal,
  RefundReceipt,
} from '../api/types'
import { useAuth } from '../state/Auth'
import { useMerchantAction } from '../state/useMerchantAction'
import { useMounted } from '../state/useResource'

export interface RefundDraft {
  proposal?: MockRefundProposal
  preparation?: { version: number; replaces: string | null; key: string }
  execution?: { id: string; key: string }
  pending?: boolean
}

export default function MerchantRefund({
  record,
  reload,
  draft,
  save,
}: {
  record: AfterSalesCase | null
  reload: () => void
  draft: RefundDraft
  save: (update: Partial<RefundDraft>) => void
}) {
  const { client } = useAuth()
  const alive = useMounted()
  const { busy: localBusy, error, run } = useMerchantAction(reload)
  const busy = localBusy || draft.pending === true
  const { proposal } = draft

  function perform(operation: () => Promise<void>, refresh = false) {
    if (busy) return
    // The case may be unmounted while its request is still in flight.
    void run(async () => {
      save({ pending: true })
      try {
        await operation()
      } finally {
        save({ pending: false })
      }
    }, refresh)
  }

  function checked(value: Proposal, caseId: string, orderId: string): MockRefundProposal {
    if (
      value.action_type !== 'MOCK_REFUND' ||
      value.canonical_payload.case_id !== caseId ||
      value.canonical_payload.order_id !== orderId
    )
      throw new Error('退款提案与当前售后单不匹配，请核对后重试。')
    return value
  }

  async function read(current: MockRefundProposal) {
    const value = checked(
      await client.get<Proposal>(`/proposals/${current.proposal_id}`),
      current.canonical_payload.case_id,
      current.canonical_payload.order_id,
    )
    if (value.proposal_id !== current.proposal_id || value.payload_hash !== current.payload_hash)
      throw new Error('退款快照已变化，请重新核对。')
    save({ proposal: value })
    return value
  }

  function generate() {
    if (!record || record.status !== 'RECEIVED') return
    perform(async () => {
      const replaces = proposal?.proposal_id ?? null
      const preparation =
        draft.preparation?.version === record.version && draft.preparation.replaces === replaces
          ? draft.preparation
          : { version: record.version, replaces, key: crypto.randomUUID() }
      save({ preparation })
      const { key } = preparation
      const value = await client.post<Proposal>(
        `/merchant/after-sales/${record.id}/refund-proposals`,
        { request_id: key, expected_version: record.version },
        key,
      )
      save({ proposal: checked(value, record.id, record.order_id) })
    })
  }

  function approve(current: MockRefundProposal) {
    perform(async () => {
      const latest = await read(current)
      if (!alive.current || latest.status !== 'PENDING' || latest.confirmation || latest.result)
        return
      const confirmation = await client.post<Confirmation>(
        `/proposals/${latest.proposal_id}/confirmations`,
        { decision: 'approve' },
      )
      save({ proposal: { ...latest, status: 'APPROVED', confirmation } })
    })
  }

  function execute(current: MockRefundProposal) {
    perform(async () => {
      const latest = await read(current)
      const confirmation = latest.confirmation
      if (
        !alive.current ||
        latest.result ||
        latest.status !== 'APPROVED' ||
        confirmation?.decision !== 'approve' ||
        confirmation.consumed_at
      )
        return
      const execution =
        draft.execution?.id === latest.proposal_id
          ? draft.execution
          : { id: latest.proposal_id, key: crypto.randomUUID() }
      save({ execution })
      const receipt = await client.post<RefundReceipt>(
        `/merchant/after-sales/${latest.canonical_payload.case_id}/refund`,
        {
          proposal_id: latest.proposal_id,
          confirmation_id: confirmation.confirmation_id,
        },
        execution.key,
      )
      save({ proposal: { ...latest, status: 'EXECUTED', result: receipt } })
    }, true)
  }

  if (record?.status !== 'RECEIVED' && !proposal && !error && !busy) return null
  const snapshot = proposal?.canonical_payload
  const receipt = proposal?.result
  const expired = proposal?.status === 'EXPIRED'
  const rejected = proposal?.status === 'REJECTED'
  const stale = !!snapshot && !!record && record.version !== snapshot.expected_version
  const mayAct = record?.status === 'RECEIVED' && !stale && !receipt && !busy

  return (
    <section className="panel stack" aria-label="模拟退款">
      <h3>模拟退款</h3>
      <p className="muted">核对退款快照后，分别批准提案并执行。退款不会发生真实资金转移。</p>
      {busy && (
        <p className="muted" role="status">
          正在核对退款操作…
        </p>
      )}
      {record?.status === 'RECEIVED' && (!proposal || expired || rejected || stale) && !receipt && (
        <button className="button secondary" disabled={busy} onClick={generate}>
          {proposal ? '重新生成模拟退款提案' : '生成模拟退款提案'}
        </button>
      )}
      {proposal && snapshot && (
        <>
          <h4>退款快照</h4>
          <dl className="details-list">
            <div>
              <dt>订单编号</dt>
              <dd className="id-text">{snapshot.order_id}</dd>
            </div>
            <div>
              <dt>退款金额</dt>
              <dd>
                {money(snapshot.amount_cents)} {snapshot.currency}
              </dd>
            </div>
            <div>
              <dt>有效期至</dt>
              <dd>{formatDate(proposal.expires_at)}</dd>
            </div>
            <div>
              <dt>提案编号</dt>
              <dd className="id-text">{proposal.proposal_id}</dd>
            </div>
          </dl>
          {expired && <p role="status">提案已过期，请重新生成。</p>}
          {rejected && <p role="status">提案已拒绝，请重新生成。</p>}
          {stale && !receipt && <p role="status">售后版本已变化，请核对状态。</p>}
          {proposal.status === 'PENDING' && !proposal.confirmation && (
            <button
              className="button secondary"
              disabled={!mayAct}
              onClick={() => approve(proposal)}
            >
              批准退款提案
            </button>
          )}
          {proposal.status === 'APPROVED' && proposal.confirmation?.decision === 'approve' && (
            <>
              <p role="status">提案已批准。退款结果以服务端回执为准。</p>
              <button
                className="button primary"
                disabled={!mayAct}
                onClick={() => execute(proposal)}
              >
                执行模拟退款
              </button>
            </>
          )}
          {receipt ? (
            <div className="notice" role="status">
              <strong>退款回执</strong>
              <p>{money(receipt.amount_cents)} · 模拟退款成功</p>
              <p className="id-text">{receipt.refund_id}</p>
            </div>
          ) : (
            <button
              className="button secondary small"
              disabled={busy}
              onClick={() =>
                perform(async () => {
                  await read(proposal)
                }, true)
              }
            >
              核对退款提案状态
            </button>
          )}
        </>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
