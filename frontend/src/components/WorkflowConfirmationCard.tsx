import { useRef, useState } from 'react'
import { useAuth } from '../state/Auth'
import { useResource } from '../state/useResource'
import { errorMessage } from '../api/client'
import { decide, operationKey, readOperation, saveOperation } from '../api/agentWorkflow'
import type { Operation, Run, Thread } from '../api/agentWorkflow'
import type { Proposal } from '../api/types'
import WorkflowResources from './WorkflowResources'
import WorkflowProposalDetails from './WorkflowProposalDetails'
import { expiryLabel } from '../api/proposalExpiry'
import { useProposalExpiry } from '../state/useProposalExpiry'
export default function WorkflowConfirmationCard({
  run,
  onThread,
  onRequote,
}: {
  run: Run
  onThread: (thread: Thread) => void
  onRequote: () => void
}) {
  const { client: api, user } = useAuth()
  const pending = run.pending_confirmation!
  const {
    data: proposal,
    error,
    reload,
  } = useResource<Proposal>(`/proposals/${pending.proposal_id}`)
  const expiry = useProposalExpiry(proposal, reload)
  const key = operationKey(`${user!.store_id}:${user!.user_id}`, run.thread_id, pending)
  const operation = useRef<Operation | null>(readOperation(key, run))
  const guard = useRef(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [retry, setRetry] = useState(Boolean(operation.current))
  async function submit(decision: 'approve' | 'reject') {
    if (guard.current || !proposal || (expiry.elapsed && !retry && !proposal.confirmation))
      return
    guard.current = true
    setBusy(true)
    setNotice('')
    const op = operation.current ?? {
      request_id: crypto.randomUUID(),
      run_id: run.id,
      interrupt_id: pending.interrupt_id,
      proposal_id: pending.proposal_id!,
      decision,
    }
    function save(value: Operation) {
      operation.current = value
      saveOperation(key, value)
    }
    save(op)
    try {
      const result = await decide(api, run.thread_id, op, save)
      onThread(result.thread)
      reload()
      setRetry(result.uncertain)
      setNotice(
        result.uncertain
          ? '结果尚未确定。已核对服务器；可使用原 request_id 继续恢复。'
          : '已核对持久化结果。',
      )
    } catch (e) {
      setNotice(errorMessage(e))
      setRetry(true)
      reload()
    } finally {
      guard.current = false
      setBusy(false)
    }
  }
  return (
    <section className="panel workflow-confirmation" data-testid="workflow-confirmation">
      <span className="eyebrow">YOUR DECISION</span>
      <h2>{pending.action_type === 'RETURN_REQUEST' ? '确认退货申请' : '确认购买快照'}</h2>
      <p className="muted">每份提案单独确认。批准后由工作流提交，前端不重复执行交易。</p>
      <small>当前授权节点 {pending.interrupt_id} · Run {run.id}</small>
      {error && <p role="alert">{error}</p>}
      {!proposal && !error && <p>读取服务端快照…</p>}
      {proposal && (
        <>
          <WorkflowProposalDetails proposal={proposal} />
          {operation.current && <small data-testid="resume-request-id">原恢复 request_id {operation.current.request_id} · {retry ? '仅在点击核对后重试原请求' : '已保留请求身份'}</small>}
          {proposal.result && (
            <p className="notice">
              业务已执行，工作流回答尚待核实。请以下方真实资源状态为准，恢复不会重新提交该业务。
            </p>
          )}
          {proposal.result && (
            <WorkflowResources
              refs={[
                {
                  kind: proposal.action_type === 'RETURN_REQUEST' ? 'case' : 'order',
                  id: proposal.result.resource_id,
                },
              ]}
            />
          )}
          <p className="muted">
            服务端有效期：{new Date(proposal.expires_at).toLocaleString()}
          </p>
          {proposal.status === 'PENDING' && !proposal.confirmation && !proposal.result && (
            <div
              className={`notice ${expiry.elapsed ? 'warning' : ''}`}
              data-testid="proposal-countdown"
            >
              <p>
                服务端有效期倒计时（估计）：<strong>{expiryLabel(expiry.remaining)}</strong>
              </p>
              <p>
                {expiry.elapsed
                  ? '倒计时结束，已暂停新确认并查询服务端状态。请核对，未自动重新报价。'
                  : expiry.remaining === null
                    ? '服务端时间待核对，请刷新提案状态；不会使用本机时钟决定授权。'
                    : '以服务端核验为准；倒计时不会延长提案或自动批准。'}
              </p>
            </div>
          )}
          {proposal.status === 'EXPIRED' ? (
            <div className="notice warning">
              <p>提案已过期，需要新提案和重新确认。</p>
              <button className="button primary" onClick={onRequote}>
                重新请求报价
              </button>
            </div>
          ) : (
            <div className="inline-actions">
              {retry || proposal.confirmation ? (
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() =>
                    void submit(operation.current?.decision ?? proposal.confirmation!.decision)
                  }
                >
                  核对并重试原恢复
                </button>
              ) : (
                <>
                  <button
                    className="button primary"
                    disabled={busy || expiry.elapsed}
                    onClick={() => void submit('approve')}
                  >
                    批准并继续工作流
                  </button>
                  <button
                    className="button secondary"
                    disabled={busy || expiry.elapsed}
                    onClick={() => void submit('reject')}
                  >
                    拒绝并继续工作流
                  </button>
                </>
              )}
            </div>
          )}
        </>
      )}
      <button className="text-button" disabled={busy} onClick={reload}>
        刷新提案状态
      </button>
      {notice && <p role="status">{notice}</p>}
    </section>
  )
}
