import { useState } from 'react';
import { apiFetch, post, timeAgo, useApi } from '../api';
import { Card } from '../ui/Card';
import { DataTable } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';

interface MemoryHealth {
  provider: string; model: string; mode: string; vectors: number; withheld: number; pending: number;
  last_ok_at: string | null; last_error: string | null; failures: number; healthy: boolean;
}
interface Token { id: string; name: string; role: string; project_keys: string[] | null; created_by: string | null; created_at: string; last_used_at: string | null; revoked_at: string | null }

const ROLES: { role: string; text: string }[] = [
  { role: 'read', text: 'Read: search and read only' },
  { role: 'write', text: 'Write: also record work (sessions)' },
  { role: 'review', text: 'Review: also accept rules and decisions' },
  { role: 'admin', text: 'Admin: also make projects and tokens' },
];

export function SystemPage() {
  const health = useApi<MemoryHealth>('/v1/memory-health', 10000);
  const tokens = useApi<Token[]>('/v1/tokens', 0);
  const [name, setName] = useState('');
  const [role, setRole] = useState('write');
  const projects = useApi<{ key: string; name: string }[]>('/v1/projects');
  const [scope, setScope] = useState<string[]>([]); // empty = every project
  const [fresh, setFresh] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  async function make() {
    setProblem(null); setFresh(null);
    try {
      const made = await post<{ token: string; name: string }>('/v1/tokens', { name: name.trim(), role, project_keys: scope.length ? scope : null });
      setFresh(made.token); setName(''); setScope([]);
      tokens.reload();
    } catch (failure) { setProblem((failure as Error).message); }
  }
  async function revoke(id: string) {
    setProblem(null);
    try { await apiFetch(`/v1/tokens/${id}`, { method: 'DELETE' }); tokens.reload(); } catch (failure) { setProblem((failure as Error).message); }
  }
  async function sync() {
    setSyncing(true); setProblem(null);
    try { await post('/v1/embeddings/sync'); health.reload(); } catch (failure) { setProblem((failure as Error).message); } finally { setSyncing(false); }
  }

  const h = health.data;
  return (
    <>
      <PageHeader title="System" description="How Viber's memory is doing, and who may do what." />
      {problem && <Notice tone="error">{problem}</Notice>}
      <Card title="Memory search" description="Viber searches by meaning as well as by words, with its own local model.">
        {!h ? <EmptyState icon="psychology" title="Loading">Reading the memory health.</EmptyState> : (
          <>
            <p>
              <StatusBadge tone={h.healthy ? 'success' : h.provider === 'none' ? 'neutral' : 'warning'}>{h.healthy ? 'healthy' : h.provider === 'none' ? 'keyword only' : 'needs attention'}</StatusBadge>{' '}
              <span className="text-muted">{h.mode}. Model {h.model} ({h.provider}).</span>
            </p>
            <p className="text-muted">
              {h.vectors} searchable by meaning, {h.pending} waiting, {h.withheld} withheld because they looked like secrets.
              {h.last_ok_at ? ` Last worked ${timeAgo(h.last_ok_at)}.` : ''}
            </p>
            {h.last_error && <Notice tone="warning">{h.last_error}</Notice>}
            <button type="button" className="btn btn-ghost btn-sm" disabled={syncing || h.provider === 'none'} onClick={sync}>{syncing ? 'Working...' : 'Fill in what is missing now'}</button>
          </>
        )}
      </Card>
      <Card title="Access tokens" description="The master token is admin. Give each person or session its own token with only the role it needs." padded={false}>
        <DataTable<Token>
          label="Access tokens" rows={tokens.data ?? []} rowKey={(row) => row.id}
          empty={<EmptyState icon="key" title="No extra tokens yet">Make one below. Sessions should use a Write token, not the master.</EmptyState>}
          columns={[
            { key: 'name', header: 'Name', render: (row) => row.name },
            { key: 'role', header: 'Role', render: (row) => <StatusBadge tone={row.role === 'admin' ? 'danger' : row.role === 'review' ? 'warning' : row.role === 'write' ? 'info' : 'neutral'}>{row.role}</StatusBadge> },
            { key: 'projects', header: 'Projects', render: (row) => (row.project_keys ? row.project_keys.join(', ') : 'all') },
            { key: 'used', header: 'Last used', render: (row) => (row.last_used_at ? timeAgo(row.last_used_at) : 'never') },
            { key: 'state', header: '', align: 'end', render: (row) => row.revoked_at
              ? <span className="text-muted">revoked {timeAgo(row.revoked_at)}</span>
              : <button type="button" className="btn btn-ghost btn-sm" onClick={() => revoke(row.id)}>Revoke</button> },
          ]}
        />
      </Card>
      <Card title="Make a token">
        <div className="viber-token">
          <input value={name} aria-label="Token name" placeholder="Name, for example session-s12" onChange={(event) => setName(event.target.value)} />
        </div>
        <div role="radiogroup" aria-label="Role" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', margin: '0.75rem 0' }}>
          {ROLES.map((entry) => (
            <button key={entry.role} type="button" role="radio" aria-checked={role === entry.role}
              className={role === entry.role ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => setRole(entry.role)}>{entry.text}</button>
          ))}
        </div>
        <p className="text-muted" style={{ margin: '0.5rem 0 0.25rem' }}>Projects it may use. Memory is per project, so limit a session's token to its own project.</p>
        <div role="group" aria-label="Projects" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <button type="button" aria-pressed={scope.length === 0} className={scope.length === 0 ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => setScope([])}>All projects</button>
          {(projects.data ?? []).map((entry) => (
            <button key={entry.key} type="button" aria-pressed={scope.includes(entry.key)}
              className={scope.includes(entry.key) ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'}
              onClick={() => setScope(scope.includes(entry.key) ? scope.filter((k) => k !== entry.key) : [...scope, entry.key])}>{entry.name}</button>
          ))}
        </div>
        <button type="button" className="btn btn-primary" disabled={!name.trim()} onClick={make}>Make token</button>
        {fresh && <Notice tone="success">Copy this token now, it is not shown again: <code className="viber-mono">{fresh}</code></Notice>}
      </Card>
    </>
  );
}
