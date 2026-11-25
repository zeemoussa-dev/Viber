import { useMemo, useState } from 'react';
import { projectPath, useProject } from '../project';
import { useApi } from '../api';
import { Card } from '../ui/Card';
import { DataTable, NameCell } from '../ui/DataTable';
import { DetailPanel } from '../ui/DetailPanel';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge, type StatusTone } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { SearchField, Toolbar } from '../ui/Toolbar';

interface ItemRow { key: string; kind: string; lane: string; status: string; severity: string | null; area: string | null; title: string; found_on: string | null; gate: string }
interface ItemDetail extends ItemRow { body: string; gate_reason: string | null; data: Record<string, unknown> }

const CLOSED = new Set(['Closed', 'Done', "Won't Fix"]);

function statusTone(status: string): StatusTone {
  if (CLOSED.has(status)) return 'neutral';
  if (status === 'Blocked') return 'danger';
  if (status === 'In Progress' || status === 'In Sprint') return 'info';
  return 'warning';
}

function severityTone(severity: string | null): StatusTone {
  if (severity === 'Blocker') return 'danger';
  if (severity === 'Major') return 'warning';
  return 'neutral';
}

function Detail({ itemKey, onClose }: { itemKey: string; onClose: () => void }) {
  const { project } = useProject();
  const { data, error } = useApi<ItemDetail>(projectPath(project, `/items/${itemKey}`));
  return (
    <DetailPanel title={itemKey} subtitle={data?.title} onClose={onClose}
      badges={data && <><StatusBadge tone={statusTone(data.status)}>{data.status}</StatusBadge><StatusBadge tone="neutral">{data.kind}</StatusBadge>{data.severity && <StatusBadge tone={severityTone(data.severity)}>{data.severity}</StatusBadge>}</>}>
      {error && <Notice tone="error">{error}</Notice>}
      {!data ? <LoadingState rows={3} /> : (
        <>
          <dl className="viber-kv">
            <dt>Lane</dt><dd>{data.lane}</dd>
            <dt>Area</dt><dd>{data.area ?? '-'}</dd>
            <dt>Found</dt><dd>{data.found_on ?? '-'}</dd>
            <dt>Gate</dt><dd>{data.gate}{data.gate_reason ? `: ${data.gate_reason}` : ''}</dd>
          </dl>
          {data.body ? <p className="viber-handoff">{data.body}</p> : <p className="text-muted">No description.</p>}
        </>
      )}
    </DetailPanel>
  );
}

export function WorkPage() {
  const { project } = useProject();
  const { data, error, loading } = useApi<ItemRow[]>(projectPath(project, '/items?limit=1000'), 15000);
  const [kind, setKind] = useState('all');
  const [view, setView] = useState('open');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  const items = data ?? [];
  const kinds = useMemo(() => ['all', ...Array.from(new Set(items.map((item) => item.kind))).sort()], [items]);
  const shown = items.filter((item) =>
    (kind === 'all' || item.kind === kind)
    && (view === 'all' || (view === 'open') === !CLOSED.has(item.status))
    && (!search || `${item.key} ${item.title}`.toLowerCase().includes(search.toLowerCase())));

  return (
    <>
      <PageHeader title="Work" description="Bugs, tasks and stories, from the quick lane to the full pipeline." />
      {error && <Notice tone="error">{error}</Notice>}
      <Tabs label="Kind" value={kind} onChange={setKind}
        tabs={kinds.map((value) => ({ value, label: value === 'all' ? 'All' : value, count: value === 'all' ? items.length : items.filter((i) => i.kind === value).length }))} />
      <Toolbar end={<Tabs label="Status" value={view} onChange={setView} tabs={[{ value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'all', label: 'All' }]} />}>
        <SearchField value={search} onChange={setSearch} placeholder="Search work" />
      </Toolbar>
      {loading && !data ? <LoadingState shape="rows" rows={6} /> : (
        <Card padded={false}>
          <DataTable<ItemRow>
            label="Work items" rows={shown} rowKey={(row) => row.key} selectedKey={open} onRowClick={(row) => setOpen(row.key)}
            empty={<EmptyState icon="task_alt" title="Nothing matches">Bugs from viber_bug and work from viber_quick appear here.</EmptyState>}
            columns={[
              { key: 'key', header: 'Item', width: '9rem', render: (row) => <NameCell name={row.key} sub={row.kind} /> },
              { key: 'title', header: 'Title', render: (row) => row.title },
              { key: 'severity', header: 'Severity', hideBelow: 'sm', render: (row) => row.severity ? <StatusBadge tone={severityTone(row.severity)}>{row.severity}</StatusBadge> : '-' },
              { key: 'found', header: 'Found', hideBelow: 'md', render: (row) => row.found_on ?? '-' },
              { key: 'status', header: 'Status', align: 'end', render: (row) => <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge> },
            ]}
          />
        </Card>
      )}
      {open && <Detail itemKey={open} onClose={() => setOpen(null)} />}
    </>
  );
}
