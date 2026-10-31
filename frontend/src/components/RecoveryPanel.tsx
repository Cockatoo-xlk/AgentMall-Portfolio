import { useState } from 'react'
import { uuidPattern } from '../api/agentWorkflow'
export default function RecoveryPanel({
  onRestore,
  busy,
}: {
  onRestore: (id: string) => void
  busy: boolean
}) {
  const [id, setId] = useState('')
  return (
    <form
      className="panel recovery-panel"
      onSubmit={(e) => {
        e.preventDefault()
        if (uuidPattern.test(id.trim())) onRestore(id.trim())
      }}
    >
      <label htmlFor="thread-reference">恢复已有 Thread</label>
      <div className="inline-actions">
        <input
          id="thread-reference"
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="输入 Thread ID"
          autoComplete="off"
        />
        <button className="button secondary" disabled={busy || !uuidPattern.test(id.trim())}>
          恢复会话
        </button>
      </div>
      <small className="muted">
        刷新后需重新登录。链接只保存会话引用，所有查询仍由服务器验证归属。
      </small>
    </form>
  )
}
