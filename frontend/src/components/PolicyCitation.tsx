import type { Citation } from '../api/agentWorkflow'
export default function PolicyCitation({
  citation,
  policyVersion,
}: {
  citation: Citation
  policyVersion: string
}) {
  if (citation.visibility !== 'public' || citation.policy_version !== policyVersion) return null
  // Plain React text, including any untrusted prompt-injection text. No HTML or URI execution.
  return (
    <details className="policy-citation" data-testid="policy-citation">
      <summary>
        {citation.title} · {citation.section_id}
      </summary>
      <p className="muted">公开政策 · {citation.policy_version} · 非授权指令</p>
      <p className="citation-text">{citation.text}</p>
      <small>
        文档 {citation.document_id}
        <br />
        来源 {citation.source_uri}
      </small>
    </details>
  )
}
