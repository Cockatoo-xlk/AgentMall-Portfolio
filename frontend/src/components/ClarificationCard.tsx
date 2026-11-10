import { useRef, useState } from 'react'
import { useAuth } from '../state/Auth'
import type { Run, Thread } from '../api/agentWorkflow'
import { errorMessage } from '../api/client'
// Parent keys this component by run AND interrupt. Retries never change the accepted input.
export default function ClarificationCard({
  run,
  onThread,
}: {
  run: Run
  onThread: (thread: Thread) => void
}) {
  const { client } = useAuth()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [locked, setLocked] = useState(false)
  const [error, setError] = useState('')
  const gate = useRef(false)
  const operation = useRef<{
    request_id: string
    run_id: string
    interrupt_id: string
    clarification: string
  } | null>(null)
  async function submit() {
    if (gate.current) return
    gate.current = true
    setBusy(true)
    setLocked(true)
    const op = operation.current ?? {
      request_id: crypto.randomUUID(),
      run_id: run.id,
      interrupt_id: run.pending_confirmation!.interrupt_id,
      clarification: text,
    }
    operation.current = op
    try {
      const before = await client.get<Thread>(`/agent/threads/${run.thread_id}`)
      if (
        before.runs[0]?.id !== run.id ||
        before.runs[0]?.pending_confirmation?.interrupt_id !== op.interrupt_id
      ) {
        onThread(before)
        return
      }
      try {
        await client.post(`/agent/threads/${run.thread_id}/resume${before.runs[0]?.job ? "/async" : ""}`, op)
      } finally {
        onThread(await client.get<Thread>(`/agent/threads/${run.thread_id}`))
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      gate.current = false
      setBusy(false)
    }
  }
  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <label>
        补充信息
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={1500}
          disabled={locked}
        />
      </label>
      <button className="button primary" disabled={busy || !text.trim()}>
        {locked ? '核对并重试原补充' : '提交补充并 Resume'}
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  )
}
