import { useEffect, useState } from 'react';
import { projectPath, useProject } from '../project';
import { apiFetch, useApi } from '../api';
import { Card } from '../ui/Card';
import { DataTable } from '../ui/DataTable';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge, type StatusTone } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { SearchField, Toolbar } from '../ui/Toolbar';
import { RuleReach } from './RuleReach';

interface Rule { id: string; category: string; scope: string; components: string[]; text: string; status: string; source: string | null }
interface Fact { id: string; scope: string; subject: string | null; text: string; trust: string }
interface Recalled { items: { kind: string; id: string; content: string; rank: number }[]; context: string }

const RULE_TONE: Record<string, StatusTone> = { accepted: 'success', proposed: 'warning', retired: 'neutral' };

function Recall({ project }: { project: string }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<Recalled | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.trim().length < 2) { setResult(null); return undefined; }
    const timer = window.setTimeout(() => {
      apiFetch<Recalled>(`/v1/projects/${project}/recall?q=${encodeURIComponent(query.trim())}&limit=20`)
        .then((found) => { setResult(found); setError(null); })
        .catch((failure: Error) => setError(failure.message));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, project]);

  return (
    <Card title="Recall" description="What a session would get from viber_recall: facts, accepted rules, decisions, open work, episodes.">
      <Toolbar><SearchField value={query} onChange={setQuery} placeholder="Search project memory" autoFocus /></Toolbar>
      {error && <Notice tone="error">{error}</Notice>}
      {result && result.items.length === 0 && <EmptyState icon="search_off" title="Nothing remembered about that" />}
      {result?.items.map((item) => (
        <div key={`${item.kind}:${item.id}`} className="viber-review-item">
          <StatusBadge tone="accent">{item.kind}</StatusBadge> <span className="text-muted viber-mono">{item.kind === 'decision' || item.kind === 'item' ? item.id : ''}</span>
          <p>{item.content}</p>
        </div>
      ))}
    </Card>
  );
}

export function MemoryPage() {
  const { project } = useProject();
  const rules = useApi<Rule[]>(projectPath(project, '/memory/rules'));
  const facts = useApi<Fact[]>(projectPath(project, '/memory/facts'));
  const [tab, setTab] = useState('rules');
  const loading = (rules.loading && !rules.data) || (facts.loading && !facts.data);

  return (
    <>
      <PageHeader title="Memory" description="What every session on this project can recall." />
      {project && <Recall project={project} />}
      <div className="viber-section-gap" />
      {(rules.error ?? facts.error) && <Notice tone="error">{rules.error ?? facts.error}</Notice>}
      <Tabs label="Memory sections" value={tab} onChange={setTab} tabs={[
        { value: 'rules', label: 'Rules', count: rules.data?.length },
        { value: 'facts', label: 'Facts', count: facts.data?.length },
      ]} />
      {loading ? <LoadingState shape="rows" rows={5} /> : (
        <Card padded={false}>
          {tab === 'rules' && (
            <DataTable<Rule> label="Rules" rows={rules.data ?? []} rowKey={(row) => row.id}
              empty={<EmptyState icon="gavel" title="No rules yet">Agents propose them with viber_remember; you accept them in the review queue.</EmptyState>}
              columns={[
                { key: 'text', header: 'Rule', render: (row) => row.text },
                { key: 'category', header: 'Kind', hideBelow: 'sm', render: (row) => row.category },
                { key: 'scope', header: 'Applies to', hideBelow: 'md', render: (row) => <RuleReach ruleId={row.id} components={row.components} locked={row.status === 'retired'} onSaved={rules.reload} /> },
                { key: 'status', header: 'Status', align: 'end', render: (row) => <StatusBadge tone={RULE_TONE[row.status] ?? 'neutral'}>{row.status}</StatusBadge> },
              ]} />
          )}
          {tab === 'facts' && (
            <DataTable<Fact> label="Facts" rows={facts.data ?? []} rowKey={(row) => row.id}
              empty={<EmptyState icon="psychology" title="No facts yet">Sessions store durable facts with viber_remember.</EmptyState>}
              columns={[
                { key: 'text', header: 'Fact', render: (row) => row.text },
                { key: 'scope', header: 'Scope', hideBelow: 'md', render: (row) => row.scope },
                { key: 'trust', header: 'Trust', align: 'end', render: (row) => <StatusBadge tone="neutral">{row.trust}</StatusBadge> },
              ]} />
          )}
        </Card>
      )}
    </>
  );
}
