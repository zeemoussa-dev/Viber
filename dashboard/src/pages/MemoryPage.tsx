import { useEffect, useState } from 'react';
import { projectPath, useProject } from '../project';
import { apiFetch, useApi } from '../api';
import { Card } from '../ui/Card';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge, type StatusTone } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { SearchField, Toolbar } from '../ui/Toolbar';
import { GroupedList, sourceName, type Facet } from './GroupedList';
import { RuleReach } from './RuleReach';

interface Rule { id: string; category: string; scope: string; components: string[]; text: string; status: string; source: string | null }
interface Fact { id: string; scope: string; subject: string | null; text: string; trust: string; source: string | null }
interface Recalled { items: { kind: string; id: string; content: string; rank: number }[]; context: string }

const RULE_TONE: Record<string, StatusTone> = { accepted: 'success', proposed: 'warning', retired: 'neutral' };

const RULE_FACETS: Facet<Rule>[] = [
  { id: 'status', label: 'Status', of: (r) => [r.status] },
  { id: 'component', label: 'Component', of: (r) => (r.components.length ? r.components : ['Whole project']) },
  { id: 'source', label: 'Came from', of: (r) => [sourceName(r.source)] },
  { id: 'kind', label: 'Kind', of: (r) => [r.category] },
];
const FACT_FACETS: Facet<Fact>[] = [
  { id: 'source', label: 'Came from', of: (f) => [sourceName(f.source)] },
  { id: 'component', label: 'Component', of: (f) => [f.scope === 'project' ? 'Whole project' : f.scope.replace('component:', '')] },
  { id: 'trust', label: 'Trust', of: (f) => [f.trust] },
];

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
  const facts = useApi<Fact[]>(projectPath(project, '/memory/facts?limit=5000'));
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
        <Card>
          {tab === 'rules' && (
            <GroupedList<Rule> id={`${project}.memory-rules`} rows={rules.data ?? []} rowKey={(row) => row.id} text={(row) => `${row.text} ${row.components.join(' ')}`}
              facets={RULE_FACETS} defaultGroup="status" empty="No rules yet"
              render={(row) => (
                <>
                  <StatusBadge tone={RULE_TONE[row.status] ?? 'neutral'}>{row.status}</StatusBadge>{' '}
                  <span className="text-muted">{row.category} · {sourceName(row.source)} · applies to </span>
                  <RuleReach ruleId={row.id} components={row.components} locked={row.status === 'retired'} onSaved={rules.reload} />
                  <p>{row.text}</p>
                </>
              )} />
          )}
          {tab === 'facts' && (
            <GroupedList<Fact> id={`${project}.memory-facts`} rows={facts.data ?? []} rowKey={(row) => row.id} text={(row) => `${row.text} ${row.subject ?? ''}`}
              facets={FACT_FACETS} defaultGroup="source" empty="No facts yet"
              render={(row) => (
                <>
                  <span className="text-muted">{row.scope === 'project' ? 'Whole project' : row.scope.replace('component:', '')} · {sourceName(row.source)}{row.subject ? ` · ${row.subject}` : ''}</span>
                  <p>{row.text}</p>
                </>
              )} />
          )}
        </Card>
      )}
    </>
  );
}
