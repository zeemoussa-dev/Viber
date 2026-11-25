import { projectPath, useProject } from '../project';
import { timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { StatTiles, type Stat } from '../ui/charts';
import { DataTable, NameCell } from '../ui/DataTable';
import { EmptyState, LoadingState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';

interface ActiveSession { id: string; tag: string; goal: string | null; state: string; repo: string | null; last_seen: string; files: string[] }
interface OverviewData {
  project: { key: string; name: string };
  counts: { active_sessions: number; open_bugs: number; open_items: number; awaiting_review: number; components: number; link_problems: number; facts: number; accepted_rules: number };
  session_stats: {
    context_packs: { packs: number; average_tokens: number; max_tokens: number };
    sessions: { total: number; forks: number; active: number };
    overlap_warnings: number; handoffs: number;
  };
  recent_changes: { occurred_on: string; kind: string; summary: string }[];
  recent_handoffs: { content: string; occurred_at: string; tag: string | null }[];
  active_sessions: ActiveSession[];
}

export function Overview() {
  const { project } = useProject();
  const { data, error, loading } = useApi<OverviewData>(projectPath(project, '/overview'), 10000);

  if (loading && !data) return <><PageHeader title="Overview" /><LoadingState shape="page" label="Loading overview" /></>;
  if (!data) return <><PageHeader title="Overview" /><Notice tone="error">{error ?? 'Nothing came back.'}</Notice></>;

  const { counts, session_stats: stats } = data;
  const tiles: Stat[] = [
    { key: 'active', label: 'Active sessions', value: counts.active_sessions, note: `${stats.sessions.forks} forks of ${stats.sessions.total} sessions` },
    { key: 'review', label: 'Awaiting your review', value: counts.awaiting_review, tone: counts.awaiting_review ? 'warning' : undefined, note: 'rules, decisions, flagged items' },
    { key: 'bugs', label: 'Open bugs', value: counts.open_bugs, note: `${counts.open_items} open items in all` },
    { key: 'pack', label: 'Context pack', value: `${stats.context_packs.average_tokens} tokens`, note: `largest ${stats.context_packs.max_tokens}, ${stats.context_packs.packs} sessions started` },
    { key: 'overlap', label: 'Collision warnings', value: stats.overlap_warnings, tone: stats.overlap_warnings ? 'warning' : undefined, note: 'two sessions on one file' },
    { key: 'handoffs', label: 'Handoffs left', value: stats.handoffs, note: 'carried to the next session or fork' },
    { key: 'components', label: 'Components', value: counts.components, note: `${counts.link_problems} link problems`, tone: counts.link_problems ? 'danger' : undefined },
    { key: 'memory', label: 'Memory', value: counts.facts, note: `facts, ${counts.accepted_rules} accepted rules` },
  ];

  return (
    <>
      <PageHeader title={data.project.name} description="What your sessions are doing and what needs you." />
      {error && <Notice tone="warning">Showing the last data: {error}</Notice>}
      <StatTiles stats={tiles} label="Project figures" />
      <div className="viber-grid">
        <Card title="Active sessions" description="Seen in the last 30 minutes" padded={false}>
          <DataTable<ActiveSession>
            label="Active sessions" rows={data.active_sessions} rowKey={(row) => row.id}
            empty={<EmptyState icon="terminal" title="No active sessions">Sessions appear here once the hook registers them.</EmptyState>}
            columns={[
              { key: 'tag', header: 'Session', render: (row) => <NameCell name={row.tag} sub={row.repo ?? undefined} /> },
              { key: 'goal', header: 'Goal', render: (row) => row.goal ?? <span className="text-muted">not set</span> },
              { key: 'files', header: 'Editing', hideBelow: 'md', render: (row) => <span className="viber-mono">{row.files.slice(0, 2).join(', ') || '-'}</span> },
              { key: 'seen', header: 'Last seen', align: 'end', render: (row) => <StatusBadge tone={row.state === 'working' ? 'success' : 'neutral'}>{row.state} · {timeAgo(row.last_seen)}</StatusBadge> },
            ]}
          />
        </Card>
        <Card title="Latest handoffs" description="What sessions left for the next one">
          {data.recent_handoffs.length === 0
            ? <EmptyState icon="forward_to_inbox" title="No handoffs yet">Sessions leave one with viber_handoff.</EmptyState>
            : data.recent_handoffs.map((handoff, index) => (
              <p key={index} className="viber-handoff">
                <span className="viber-handoff-meta">{handoff.tag ?? 'session'} · {timeAgo(handoff.occurred_at)}</span>{'\n'}{handoff.content}
              </p>
            ))}
        </Card>
        <Card title="Recent changes" padded={false}>
          <DataTable<OverviewData['recent_changes'][number]>
            label="Recent changes" rows={data.recent_changes} rowKey={(row) => `${row.occurred_on}-${row.summary}`}
            empty={<EmptyState icon="history" title="No changes logged">viber_quick logs one in a line.</EmptyState>}
            columns={[
              { key: 'when', header: 'Date', width: '8rem', render: (row) => row.occurred_on },
              { key: 'kind', header: 'Kind', width: '6rem', render: (row) => <StatusBadge tone="neutral">{row.kind}</StatusBadge> },
              { key: 'summary', header: 'Summary', render: (row) => row.summary },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
