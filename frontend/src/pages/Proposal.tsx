import { useParams } from 'react-router'
import ConfirmationCard from '../components/ConfirmationCard'
export default function ProposalPage() {
  const { id } = useParams()
  return (
    <main className="page narrow-page">
      <div className="page-header">
        <div>
          <span className="eyebrow">CHECK BEFORE YOU COMMIT</span>
          <h1>确认你的选择</h1>
          <p className="muted">核对商品、数量和金额，再决定是否继续。</p>
        </div>
      </div>
      {id && <ConfirmationCard key={id} proposalId={id} />}
    </main>
  )
}
