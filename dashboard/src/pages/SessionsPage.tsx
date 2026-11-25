import { useState } from 'react';
import { projectPath, useProject } from '../project';
import { timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { DataTable, NameCell } from '../ui/DataTable';
import { DetailPanel } from '../ui/DetailPanel';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';

interface SessionRow {
  tag: string; goal: string | null; state: string; repo: string | null; branch: string | null; source: string | null;
  last_seen: string; ended_at: string | null; parent_tag: string | null; component: string | null; active: boolean;
  files_touched: number; handoffs: number; summary: string | null;
}
interface SessionDetail {
  tag: string; goal: string | null; state: string; summary: string | null; started_at: string; last_seen: string; ended_at: string | null;
  files: { path: string; touches: number; last_touched: string }[]; handoffs: { content: string; occurred_at: string }[]; forks: string[];
}

function Detail({ tag, onClose }: { tag: string; onClose: () => void }) {
  const { project } = useProject();
  const { data, error } = useApi<SessionDetail>(projectPath(project, `/sessions/${tag}/detail`));
  return (
    <DetailPanel title={`Session ${tag}`} subtitle={data?.goal ?? 'No goal set'} onClose={onClose}
      badges={data && <StatusBadge tone={data.ended_at ? 'neutral' : 'success'}>{data.ended_at ? 'ended' : data.state}</StatusBadge>}>
      {error && <Notice tone="error">{error}</Notice>}
      {!data ? <LoadingState rows={4} /> : (
        <>
          <dl className="viber-kv">
            <dt>Started</dt><dd>{timeAgo(data.started_at)}</dd>
            <dt>Last seen</dt><dd>{timeAgo(data.last_seen)}</dd>
            <dt>Forks</dt><dd>{data.forks.length ? data.forks.join(', ') : 'none'}</dd>
          </dl>
          <h3>Files edited</h3>
          {data.files.length === 0 ? <p className="text-muted">None recorded.</p> : (
            <DataTable<SessionDetail['files'][number]> label="Files edited" rows={data.files} rowKey={(row) => row.path}
              columns={[
                { key: 'path', header: 'File', render: (row) => <span className="viber-mono">{row.path}</span> },
                { key: 'n', header: 'Edits', align: 'end', width: '5rem', render: (row) => row.touches },
              ]} />
          )}
          <h3 className="viber-section-gap">Handoffs</h3>
          {data.handoffs.length === 0 ? <p className="text-muted">This session has not left one.</p>
            : data.handoffs.map((handoff, index) => (
              <p key={index} className="viber-handoff"><span className="viber-handoff-meta">{timeAgo(handoff.occurred_at)}</span>{'\n'}{handoff.content}</p>
            ))}
        </>
      )}
    </DetailPanel>
  );
}

export function SessionsPage() {
  const { project } = useProject();
  const { data, error, loading } = useApi<SessionRow[]>(projectPath(project, '/sessions/history'), 10000);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Sessions" description="Every Claude Code session registered with Viber, forks included." />
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <LoadingState shape="rows" rows={5} /> : (
        <Card padded={false}>
          <DataTable<SessionRow>
            label="Sessions" rows={data ?? []} rowKey={(row) => row.tag} selectedKey={open} onRowClick={(row) => setOpen(row.tag)}
            empty={<EmptyState icon="terminal" title="No sessions yet">Install the hook (see the README) and start a Claude Code session.</EmptyState>}
            columns={[
              { key: 'tag', header: 'Session', render: (row) => <NameCell name={row.tag} sub={row.parent_tag ? `fork of ${row.parent_tag}` : row.source ?? undefined} /> },
              { key: 'goal', header: 'Goal', render: (row) => row.goal ?? <span className="text-muted">not set</span> },
              { key: 'component', header: 'Component', hideBelow: 'md', render: (row) => row.component ?? row.repo ?? '-' },
              { key: 'files', header: 'Files', align: 'end', hideBelow: 'sm', render: (row) => row.files_touched },
              { key: 'handoffs', header: 'Handoffs', align: 'end', hideBelow: 'sm', render: (row) => row.handoffs },
              { key: 'state', header: 'State', align: 'end', render: (row) => (
                <StatusBadge tone={row.ended_at ? 'neutral' : row.active ? 'success' : 'warning'}>
                  {row.ended_at ? 'ended' : row.active ? row.state : 'stale'} · {timeAgo(row.last_seen)}
                </StatusBadge>) },
            ]}
          />
        </Card>
      )}
      {open && <Detail tag={open} onClose={() => setOpen(null)} />}
    </>
  );
}
