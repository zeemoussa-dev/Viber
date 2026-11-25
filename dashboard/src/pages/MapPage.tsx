import { useState } from 'react';
import { projectPath, useProject } from '../project';
import { timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { DataTable, NameCell } from '../ui/DataTable';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge, type StatusTone } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';

interface ComponentRow {
  key: string; kind: string; repo: string | null; lifecycle: string; head_version: string | null; latest_release: string | null;
  scanned_at: string | null; releases: number; depends_on: number; dependents: number;
}
interface LinkRow { from_component: string; to_component: string | null; to_contract: string | null; type: string; scope: string; constraint: string; declared_by: string; state: string }
interface Problem { issue: string; from: string; to: string; constraint: string; detail?: string; target_version?: string }
interface Check { problems: Problem[]; link_states: Record<string, number> }

const LINK_TONE: Record<string, StatusTone> = { verified: 'success', drifted: 'warning', unverified: 'neutral' };

export function MapPage() {
  const { project } = useProject();
  const components = useApi<ComponentRow[]>(projectPath(project, '/components/summary'));
  const links = useApi<LinkRow[]>(projectPath(project, '/links'));
  const check = useApi<Check>(projectPath(project, '/links/check'));
  const [tab, setTab] = useState('components');

  const problems = check.data?.problems ?? [];
  const error = components.error ?? links.error ?? check.error;
  const loading = (components.loading && !components.data) || (links.loading && !links.data);

  return (
    <>
      <PageHeader title="Map" description="Components, their versions, and the links between them, read from the manifests." />
      {error && <Notice tone="error">{error}</Notice>}
      <Tabs label="Map sections" value={tab} onChange={setTab} tabs={[
        { value: 'components', label: 'Components', count: components.data?.length },
        { value: 'links', label: 'Links', count: links.data?.length },
        { value: 'problems', label: 'Problems', count: problems.length },
      ]} />
      {loading ? <LoadingState shape="rows" rows={6} /> : (
        <Card padded={false}>
          {tab === 'components' && (
            <DataTable<ComponentRow>
              label="Components" rows={components.data ?? []} rowKey={(row) => row.key}
              empty={<EmptyState icon="hub" title="No components yet">Run tools/scan-github.ps1 to read them from GitHub.</EmptyState>}
              columns={[
                { key: 'key', header: 'Component', render: (row) => <NameCell name={row.key} sub={row.repo ?? undefined} /> },
                { key: 'kind', header: 'Kind', hideBelow: 'sm', render: (row) => <StatusBadge tone="neutral">{row.kind}</StatusBadge> },
                { key: 'head', header: 'Head', render: (row) => <span className="viber-mono">{row.head_version ?? '-'}</span> },
                { key: 'release', header: 'Latest tag', hideBelow: 'sm', render: (row) => <span className="viber-mono">{row.latest_release ?? '-'}</span> },
                { key: 'deps', header: 'Depends on', align: 'end', hideBelow: 'md', render: (row) => row.depends_on },
                { key: 'dependents', header: 'Used by', align: 'end', hideBelow: 'md', render: (row) => row.dependents },
                { key: 'scanned', header: 'Scanned', align: 'end', hideBelow: 'md', render: (row) => timeAgo(row.scanned_at) },
              ]}
            />
          )}
          {tab === 'links' && (
            <DataTable<LinkRow>
              label="Links" rows={links.data ?? []} rowKey={(row) => `${row.from_component}>${row.to_component ?? row.to_contract}:${row.type}:${row.scope}`}
              empty={<EmptyState icon="link" title="No links yet">Links are derived from each component's manifest when it is scanned.</EmptyState>}
              columns={[
                { key: 'from', header: 'From', render: (row) => row.from_component },
                { key: 'type', header: 'Type', hideBelow: 'sm', render: (row) => `${row.type}${row.scope !== 'runtime' ? ` (${row.scope})` : ''}` },
                { key: 'to', header: 'To', render: (row) => row.to_component ?? `${row.to_contract} (contract)` },
                { key: 'constraint', header: 'Constraint', render: (row) => <span className="viber-mono">{row.constraint || 'any'}</span> },
                { key: 'state', header: 'State', align: 'end', render: (row) => <StatusBadge tone={LINK_TONE[row.state] ?? 'neutral'} title={`declared by ${row.declared_by}`}>{row.state}</StatusBadge> },
              ]}
            />
          )}
          {tab === 'problems' && (
            <DataTable<Problem>
              label="Link problems" rows={problems} rowKey={(row) => `${row.issue}:${row.from}:${row.to}`}
              empty={<EmptyState icon="verified" title="No link problems">Every constraint is satisfied and every provider is known.</EmptyState>}
              columns={[
                { key: 'issue', header: 'Issue', render: (row) => <StatusBadge tone={row.issue === 'unsatisfied' ? 'danger' : 'warning'}>{row.issue.replace('_', ' ')}</StatusBadge> },
                { key: 'from', header: 'From', render: (row) => row.from },
                { key: 'to', header: 'To', render: (row) => row.to },
                { key: 'constraint', header: 'Constraint', render: (row) => <span className="viber-mono">{row.constraint}</span> },
                { key: 'detail', header: 'Detail', hideBelow: 'md', render: (row) => row.detail ?? (row.target_version ? `target is ${row.target_version}` : '') },
              ]}
            />
          )}
        </Card>
      )}
    </>
  );
}
