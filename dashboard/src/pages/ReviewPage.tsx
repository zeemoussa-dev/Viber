import { useState } from 'react';
import { projectPath, useProject } from '../project';
import { post, timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';
import { RuleReach } from './RuleReach';

interface ReviewData {
  counts: { rules: number; decisions: number; items: number };
  rules: { id: string; category: string; scope: string; components: string[]; text: string; proposed_by: string | null; created_at: string }[];
  decisions: { key: string; title: string; context: string; decision: string; alternatives: string; consequences: string }[];
  items: { key: string; kind: string; title: string; gate_reason: string | null; status: string }[];
}

export function ReviewPage() {
  const { project } = useProject();
  const { data, error, loading, reload } = useApi<ReviewData>(projectPath(project, '/review'), 15000);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function act(path: string, message: string) {
    setProblem(null);
    try {
      await post(`/v1/projects/${project}${path}`);
      setDone(message);
      reload();
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  }

  if (loading && !data) return <><PageHeader title="Review queue" /><LoadingState shape="rows" rows={4} /></>;
  const total = data ? data.counts.rules + data.counts.decisions + data.counts.items : 0;

  return (
    <>
      <PageHeader title="Review queue" description="Agents propose; you decide. Nothing here changes behaviour until you accept it." />
      {error && <Notice tone="error">{error}</Notice>}
      {problem && <Notice tone="error" onDismiss={() => setProblem(null)}>{problem}</Notice>}
      {done && <Notice tone="success" onDismiss={() => setDone(null)}>{done}</Notice>}
      {data && total === 0 && <EmptyState icon="task_alt" title="Nothing is waiting for you">Proposed rules, decisions and flagged items land here.</EmptyState>}
      {data && data.rules.length > 0 && (
        <Card title={`Proposed rules (${data.rules.length})`} description="An accepted rule is injected into every session's context.">
          {data.rules.map((rule) => (
            <div key={rule.id} className="viber-review-item">
              <StatusBadge tone="accent">{rule.category}</StatusBadge>{' '}
              <span className="text-muted">{rule.proposed_by ?? 'agent'} · {timeAgo(rule.created_at)} · applies to </span>
              <RuleReach ruleId={rule.id} components={rule.components} onSaved={() => { setDone('Saved what the rule covers.'); reload(); }} />
              <p>{rule.text}</p>
              <div className="viber-actions">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => act(`/memory/rules/${rule.id}/accept`, 'Rule accepted.')}>Accept</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(`/memory/rules/${rule.id}/retire`, 'Rule dismissed.')}>Dismiss</button>
              </div>
            </div>
          ))}
        </Card>
      )}
      {data && data.decisions.length > 0 && (
        <Card title={`Proposed decisions (${data.decisions.length})`} description="Architecture decisions an agent recorded as Proposed." className="viber-section-gap">
          {data.decisions.map((decision) => (
            <div key={decision.key} className="viber-review-item">
              <strong>{decision.key}</strong> · {decision.title}
              {decision.context && <p className="text-muted">{decision.context}</p>}
              <p><strong>Decision:</strong> {decision.decision}</p>
              {decision.alternatives && <p className="text-muted"><strong>Alternatives:</strong> {decision.alternatives}</p>}
              <div className="viber-actions">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => act(`/decisions/${decision.key}/accept`, `${decision.key} accepted.`)}>Accept</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(`/decisions/${decision.key}/reject`, `${decision.key} rejected.`)}>Reject</button>
              </div>
            </div>
          ))}
        </Card>
      )}
      {data && data.items.length > 0 && (
        <Card title={`Flagged items (${data.items.length})`} description="Work an agent stopped on and needs a human to look at." className="viber-section-gap">
          {data.items.map((item) => (
            <div key={item.key} className="viber-review-item">
              <strong>{item.key}</strong> · {item.title} <StatusBadge tone="warning">{item.status}</StatusBadge>
              <p className="text-muted">{item.gate_reason ?? 'No reason given.'}</p>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
