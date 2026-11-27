import { useMemo, useState } from 'react';
import { projectPath, useProject } from '../project';
import { post, timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { DecisionBody } from './DecisionBody';
import { GroupedList, sourceName, type Facet } from './GroupedList';
import { RuleReach } from './RuleReach';

interface Rule { id: string; category: string; scope: string; components: string[]; text: string; source: string | null; proposed_by: string | null; created_at: string }
interface ReviewData {
  counts: { rules: number; decisions: number; items: number };
  rules: Rule[];
  decisions: { key: string; title: string }[];
  items: { key: string; kind: string; title: string; gate_reason: string | null; status: string }[];
}

const RULE_FACETS: Facet<Rule>[] = [
  { id: 'component', label: 'Component', of: (r) => (r.components.length ? r.components : ['Whole project']) },
  { id: 'source', label: 'Came from', of: (r) => [sourceName(r.source)] },
  { id: 'kind', label: 'Kind', of: (r) => [r.category] },
  // Rules cut off when they were imported end mid-sentence: easy to find and leave alone.
  { id: 'wording', label: 'Wording', of: (r) => [/[:;,]\s*$/.test(r.text) ? 'Cut off' : 'Complete'] },
];

function BulkRules({ selected, onDone, onProblem, clear }: { selected: Rule[]; onDone: (m: string) => void; onProblem: (m: string) => void; clear: () => void }) {
  const { project } = useProject();
  const [asking, setAsking] = useState<'accept' | 'retire' | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(verb: 'accept' | 'retire') {
    setBusy(true);
    try {
      const result = await post<{ done: number }>(`/v1/projects/${project}/memory/rules/bulk/${verb}`, { ids: selected.map((r) => r.id) });
      onDone(`${result.done} rule${result.done === 1 ? '' : 's'} ${verb === 'accept' ? 'accepted' : 'dismissed'}.`);
      clear();
    } catch (failure) { onProblem((failure as Error).message); } finally { setBusy(false); setAsking(null); }
  }

  if (asking) {
    const everywhere = selected.filter((r) => r.components.length === 0).length;
    return (
      <>
        <span>{asking === 'accept'
          ? `Accept ${selected.length}? Sessions must obey them${everywhere ? `; ${everywhere} reach every session` : ''}.`
          : `Dismiss ${selected.length}? They stay in the history.`}</span>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(asking)}>{busy ? 'Working…' : `Yes, ${asking === 'accept' ? 'accept' : 'dismiss'} ${selected.length}`}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(null)}>No</button>
      </>
    );
  }
  return (
    <>
      <button type="button" className="btn btn-primary btn-sm" onClick={() => setAsking('accept')}>Accept selected</button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking('retire')}>Dismiss selected</button>
    </>
  );
}

export function ReviewPage() {
  const { project } = useProject();
  const { data, error, loading, reload } = useApi<ReviewData>(projectPath(project, '/review'), 15000);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const rules = useMemo(() => data?.rules ?? [], [data]);

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
  // Open on what matters most: a few decisions are never buried under hundreds of rules.
  const current = tab ?? (data?.decisions.length ? 'decisions' : data?.items.length ? 'items' : 'rules');

  return (
    <>
      <PageHeader title="Review queue" description="Agents propose; you decide. Nothing here changes behaviour until you accept it." />
      {error && <Notice tone="error">{error}</Notice>}
      {problem && <Notice tone="error" onDismiss={() => setProblem(null)}>{problem}</Notice>}
      {done && <Notice tone="success" onDismiss={() => setDone(null)}>{done}</Notice>}
      {data && total === 0 && <EmptyState icon="task_alt" title="Nothing is waiting for you">Proposed rules, decisions and flagged items land here.</EmptyState>}
      {data && total > 0 && (
        <Tabs label="Waiting for you" value={current} onChange={setTab} tabs={[
          { value: 'decisions', label: 'Decisions', count: data.decisions.length },
          { value: 'items', label: 'Flagged', count: data.items.length },
          { value: 'rules', label: 'Rules', count: data.rules.length },
        ]} />
      )}
      {data && total > 0 && current === 'decisions' && (
        <Card description="Architecture decisions a session recorded as Proposed.">
          {data.decisions.length === 0 && <EmptyState icon="gavel" title="No decisions waiting">All decisions are on the Decisions page.</EmptyState>}
          {data.decisions.map((decision) => (
            <div key={decision.key} className="viber-review-item">
              <p><strong>{decision.key}</strong> · {decision.title}</p>
              <DecisionBody adrKey={decision.key} />
              <div className="viber-actions">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => act(`/decisions/${decision.key}/accept`, `${decision.key} accepted.`)}>Accept</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(`/decisions/${decision.key}/reject`, `${decision.key} rejected.`)}>Reject</button>
              </div>
            </div>
          ))}
        </Card>
      )}
      {data && total > 0 && current === 'items' && (
        <Card description="Work a session stopped on and needs a human to look at.">
          {data.items.length === 0 && <EmptyState icon="flag" title="Nothing is flagged" />}
          {data.items.map((item) => (
            <div key={item.key} className="viber-review-item">
              <strong>{item.key}</strong> · {item.title} <StatusBadge tone="warning">{item.status}</StatusBadge>
              <p className="text-muted">{item.gate_reason ?? 'No reason given.'}</p>
            </div>
          ))}
        </Card>
      )}
      {data && total > 0 && current === 'rules' && (
        <Card description="An accepted rule is given to every session it applies to. Group them, filter them, then decide many at once.">
          <GroupedList<Rule> id={`${project}.review-rules`} rows={rules} rowKey={(r) => r.id} text={(r) => `${r.text} ${r.components.join(' ')}`}
            facets={RULE_FACETS} defaultGroup="component" empty="No rules are waiting"
            actions={(selected, clear) => <BulkRules selected={selected} clear={clear} onProblem={setProblem} onDone={(m) => { setDone(m); reload(); }} />}
            render={(rule) => (
              <>
                <StatusBadge tone="accent">{rule.category}</StatusBadge>{' '}
                <span className="text-muted">{sourceName(rule.source)} · {timeAgo(rule.created_at)} · applies to </span>
                <RuleReach ruleId={rule.id} components={rule.components} onSaved={() => { setDone('Saved what the rule covers.'); reload(); }} />
                <p>{rule.text}</p>
                <div className="viber-actions">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => act(`/memory/rules/${rule.id}/accept`, 'Rule accepted.')}>Accept</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(`/memory/rules/${rule.id}/retire`, 'Rule dismissed.')}>Dismiss</button>
                </div>
              </>
            )} />
        </Card>
      )}
    </>
  );
}
