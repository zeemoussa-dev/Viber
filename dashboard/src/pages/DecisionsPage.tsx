import { useState } from 'react';
import { post, useApi } from '../api';
import { projectPath, useProject } from '../project';
import { Card } from '../ui/Card';
import { LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge, type StatusTone } from '../ui/StatusBadge';
import { DecisionBody } from './DecisionBody';
import { GroupedList, type Facet } from './GroupedList';

interface Decision { key: string; title: string; status: string; decided_on: string | null; source: string | null }

const TONE: Record<string, StatusTone> = { Accepted: 'success', Proposed: 'warning', Reserved: 'info', Rejected: 'danger', Superseded: 'neutral', Obsolete: 'neutral', Deprecated: 'neutral' };
const family = (key: string) => key.replace(/[0-9]+[a-z]?$/, '') || key;
const number = (key: string) => Number(key.match(/([0-9]+)[a-z]?$/)?.[1] ?? 0);

const FACETS: Facet<Decision>[] = [
  { id: 'status', label: 'Status', of: (d) => [d.status] },
  { id: 'family', label: 'Series', of: (d) => [`${family(d.key)}…`] },
  { id: 'month', label: 'Month', of: (d) => [d.decided_on?.slice(0, 7) ?? 'no date'] },
];

export function DecisionsPage() {
  const { project } = useProject();
  const { data, error, loading, reload } = useApi<Decision[]>(projectPath(project, '/decisions'), 15000);
  const [opened, setOpened] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function act(key: string, verb: 'accept' | 'reject') {
    setProblem(null);
    try { await post(`/v1/projects/${project}/decisions/${key}/${verb}`); setDone(`${key} ${verb === 'accept' ? 'accepted' : 'rejected'}.`); reload(); }
    catch (failure) { setProblem((failure as Error).message); }
  }

  const card = (decision: Decision) => (
    <div>
      <button type="button" className="btn btn-ghost" aria-expanded={opened === decision.key} style={{ textAlign: 'left', whiteSpace: 'normal', height: 'auto' }}
        onClick={() => setOpened(opened === decision.key ? null : decision.key)}>
        {opened === decision.key ? '▾' : '▸'} <strong>{decision.key}</strong> · {decision.title}
      </button>{' '}
      <StatusBadge tone={TONE[decision.status] ?? 'neutral'}>{decision.status}</StatusBadge>{' '}
      <span className="text-muted">{decision.decided_on ?? ''}</span>
      {opened === decision.key && <DecisionBody adrKey={decision.key} />}
      {decision.status === 'Proposed' && (
        <div className="viber-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={() => act(decision.key, 'accept')}>Accept</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(decision.key, 'reject')}>Reject</button>
        </div>
      )}
    </div>
  );

  // Newest number first inside each series.
  const rows = [...(data ?? [])].sort((a, b) => family(b.key).localeCompare(family(a.key)) || number(b.key) - number(a.key));
  const waiting = rows.filter((d) => d.status === 'Proposed');

  return (
    <>
      <PageHeader title="Decisions" description="Every architecture decision. Press one to read it." />
      {error && <Notice tone="error">{error}</Notice>}
      {problem && <Notice tone="error" onDismiss={() => setProblem(null)}>{problem}</Notice>}
      {done && <Notice tone="success" onDismiss={() => setDone(null)}>{done}</Notice>}
      {loading && !data ? <LoadingState shape="rows" rows={5} /> : (
        <>
          {waiting.length > 0 && (
            <Card title={`Waiting for you (${waiting.length})`} description="Recorded by a session as Proposed. Nothing treats them as decided until you accept.">
              {waiting.map((d) => <div key={d.key} className="viber-review-item">{card(d)}</div>)}
            </Card>
          )}
          <Card title="All decisions" className="viber-section-gap">
            <GroupedList<Decision> id={`${project}.decisions`} rows={rows.filter((d) => d.status !== 'Proposed')} rowKey={(d) => d.key}
              text={(d) => `${d.key} ${d.title}`} facets={FACETS} defaultGroup="family" render={card} empty="No decisions yet" />
          </Card>
        </>
      )}
    </>
  );
}
