import { useState } from 'react';
import { post, timeAgo, useApi } from '../api';
import { projectPath, useProject } from '../project';
import { Card } from '../ui/Card';
import { DataTable } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { StatusBadge } from '../ui/StatusBadge';

interface Timed { id: string; text: string; scope: string; expires_at: string; valid_to?: string; set_by_operator: boolean }
interface ForNow { live: Timed[]; ended: Timed[] }

const LENGTHS = [
  { value: '2h', text: '2 hours' },
  { value: '12h', text: 'Overnight (12 h)' },
  { value: '1d', text: '1 day' },
  { value: '1w', text: '1 week' },
];
const SUGGESTIONS = ['Run unattended and do not wait for me.', 'Do not deploy anything.'];

function ends(iso: string): string {
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60000));
  const left = minutes < 60 ? `${minutes} min` : minutes < 2880 ? `${Math.round(minutes / 60)} h` : `${Math.round(minutes / 1440)} days`;
  return `${left} left (${new Date(iso).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })})`;
}

/** What is true only for now. Every session sees it first; it ends by itself. */
export function ForNowCard() {
  const { project } = useProject();
  const { data, reload } = useApi<ForNow>(projectPath(project, '/memory/for-now'), 15000);
  const [text, setText] = useState('');
  const [lasts, setLasts] = useState('12h');
  const [problem, setProblem] = useState<string | null>(null);

  async function add() {
    setProblem(null);
    try { await post(projectPath(project, '/memory/for-now')!, { text: text.trim(), lasts }); setText(''); reload(); }
    catch (failure) { setProblem((failure as Error).message); }
  }
  async function end(id: string) {
    setProblem(null);
    try { await post(`${projectPath(project, '/memory/for-now')}/${id}/end`); reload(); }
    catch (failure) { setProblem((failure as Error).message); }
  }

  return (
    <Card title="For now" description="Temporary instructions. Every new session sees them first, and each one ends by itself.">
      {problem && <Notice tone="error">{problem}</Notice>}
      <DataTable<Timed>
        label="In force now" rows={data?.live ?? []} rowKey={(row) => row.id}
        empty={<EmptyState icon="schedule" title="Nothing temporary is in force">Add one below.</EmptyState>}
        columns={[
          { key: 'text', header: 'Instruction', render: (row) => row.text },
          { key: 'who', header: 'From', render: (row) => <StatusBadge tone={row.set_by_operator ? 'success' : 'warning'}>{row.set_by_operator ? 'you' : 'a session'}</StatusBadge> },
          { key: 'ends', header: 'Ends', render: (row) => ends(row.expires_at) },
          { key: 'act', header: '', align: 'end', render: (row) => <button type="button" className="btn btn-ghost btn-sm" onClick={() => end(row.id)}>End now</button> },
        ]}
      />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', margin: '0.75rem 0 0.5rem' }}>
        {SUGGESTIONS.map((entry) => <button key={entry} type="button" className="btn btn-ghost btn-sm" onClick={() => setText(entry)}>{entry}</button>)}
      </div>
      <div className="viber-token">
        <input value={text} maxLength={500} aria-label="Temporary instruction" placeholder="What should be true for a while?" onChange={(event) => setText(event.target.value)} />
      </div>
      <div role="radiogroup" aria-label="How long" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', margin: '0.5rem 0' }}>
        {LENGTHS.map((entry) => (
          <button key={entry.value} type="button" role="radio" aria-checked={lasts === entry.value}
            className={lasts === entry.value ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => setLasts(entry.value)}>{entry.text}</button>
        ))}
        <button type="button" className="btn btn-primary btn-sm" disabled={!text.trim()} onClick={add}>Set for now</button>
      </div>
      {!!data?.ended.length && <p className="text-muted">Ended recently: {data.ended.slice(0, 3).map((row) => `${row.text} (${timeAgo(row.valid_to)})`).join('; ')}</p>}
    </Card>
  );
}
