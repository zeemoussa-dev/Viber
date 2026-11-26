import { useState } from 'react';
import { apiFetch, useApi } from '../api';
import { projectPath, useProject } from '../project';
import { Notice } from '../ui/Notice';

const label = (components: string[]) =>
  components.length === 0 ? 'Whole project' : components.length <= 3 ? components.join(', ') : `${components.slice(0, 2).join(', ')} and ${components.length - 2} more`;

function Picker({ ruleId, start, onDone }: { ruleId: string; start: string[]; onDone: (saved: boolean) => void }) {
  const { project } = useProject();
  const all = useApi<{ key: string }[]>(projectPath(project, '/components'));
  const [chosen, setChosen] = useState<string[]>(start);
  const [filter, setFilter] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const keys = (all.data ?? []).map((entry) => entry.key);
  const shown = keys.filter((key) => chosen.includes(key) || key.toLowerCase().includes(filter.trim().toLowerCase()));

  async function save() {
    setProblem(null);
    try {
      await apiFetch(`/v1/projects/${project}/memory/rules/${ruleId}/components`, { method: 'PUT', body: JSON.stringify({ components: chosen }) });
      onDone(true);
    } catch (failure) { setProblem((failure as Error).message); }
  }

  return (
    <div style={{ margin: '0.5rem 0' }}>
      {problem && <Notice tone="error">{problem}</Notice>}
      <div className="viber-token">
        <input value={filter} aria-label="Find a component" placeholder="Find a component, for example sb-" onChange={(event) => setFilter(event.target.value)} />
      </div>
      <div role="group" aria-label="Components this rule covers" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', margin: '0.5rem 0', maxHeight: '14rem', overflowY: 'auto' }}>
        <button type="button" aria-pressed={chosen.length === 0} className={chosen.length === 0 ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => setChosen([])}>Whole project</button>
        {shown.map((key) => (
          <button key={key} type="button" aria-pressed={chosen.includes(key)} className={chosen.includes(key) ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'}
            onClick={() => setChosen(chosen.includes(key) ? chosen.filter((c) => c !== key) : [...chosen, key])}>{key}</button>
        ))}
      </div>
      {filter.trim() && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setChosen([...new Set([...chosen, ...keys.filter((k) => k.toLowerCase().includes(filter.trim().toLowerCase()))])])}>
          Choose all that match
        </button>
      )}{' '}
      <button type="button" className="btn btn-primary btn-sm" onClick={save}>{chosen.length === 0 ? 'Save: whole project' : `Save: ${chosen.length} component${chosen.length === 1 ? '' : 's'}`}</button>{' '}
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => onDone(false)}>Cancel</button>
    </div>
  );
}

/** What a rule covers, and the way to change it. */
export function RuleReach({ ruleId, components, locked, onSaved }: { ruleId: string; components: string[]; locked?: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  if (open) return <Picker ruleId={ruleId} start={components} onDone={(saved) => { setOpen(false); if (saved) onSaved(); }} />;
  if (locked) return <span title={components.join(', ')}>{label(components)}</span>;
  return (
    <button type="button" className="btn btn-ghost btn-sm" title={`${components.join(', ') || 'Every session in this project'}. Press to change what the rule covers.`} onClick={() => setOpen(true)}>
      {label(components)} ✎
    </button>
  );
}
