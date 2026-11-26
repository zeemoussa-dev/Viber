import { useState } from 'react';
import { apiFetch, post, useApi } from '../api';
import { useProject } from '../project';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';

interface Prompt { key: string; title: string; purpose: string }
interface Component { key: string; lifecycle?: string }

export function PromptsPage() {
  const { project } = useProject();
  const list = useApi<Prompt[]>(project ? `/v1/projects/${project}/prompts` : null);
  const components = useApi<Component[]>(project ? `/v1/projects/${project}/components` : null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [component, setComponent] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [text, setText] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const names = (components.data ?? []).filter((entry) => !['deprecated', 'archived'].includes(entry.lifecycle ?? '')).map((entry) => entry.key).sort();
  // A component chosen in another project does not exist here.
  const picked = component && names.includes(component) ? component : null;
  const shown = names.filter((name) => name === picked || name.toLowerCase().includes(filter.trim().toLowerCase()));

  async function open(key: string, forComponent: string | null = picked) {
    setProblem(null); setNote(null); setChosen(key);
    try {
      const suffix = forComponent ? `?component=${encodeURIComponent(forComponent)}` : '';
      setText(await apiFetch<string>(`/v1/projects/${project}/prompts/${key}${suffix}`));
    } catch (failure) { setProblem((failure as Error).message); }
  }
  function pick(name: string | null) {
    setComponent(name);
    if (chosen) void open(chosen, name);  // the prompt on screen follows the choice
  }
  async function copy() {
    try { await navigator.clipboard.writeText(text ?? ''); setNote('Copied. Paste it as the first message of the session.'); }
    catch { setNote('The browser refused to copy. Select the text and copy it by hand.'); }
  }
  async function seed() {
    setProblem(null);
    try { await post(`/v1/projects/${project}/prompts/seed`); list.reload(); } catch (failure) { setProblem((failure as Error).message); }
  }

  return (
    <>
      <PageHeader title="Prompts" description={`What to give a session so it starts knowing what to do in ${project}. Each prompt carries the project's component list.`} />
      {problem && <Notice tone="error">{problem}</Notice>}
      <Card title={`Component${picked ? `: ${picked}` : ''}`} description={`Choose the one the session will work on, or none. ${names.length} in this project.`}>
        {names.length === 0 ? <p className="text-muted">This project has no components yet.</p> : (
          <>
            <div className="viber-token">
              <input value={filter} aria-label="Find a component" placeholder="Find a component, for example fleet" onChange={(event) => setFilter(event.target.value)} />
            </div>
            <div role="radiogroup" aria-label="Component" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginTop: '0.5rem', maxHeight: '11rem', overflowY: 'auto' }}>
              <button type="button" role="radio" aria-checked={picked === null} className={picked === null ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => pick(null)}>None</button>
              {shown.map((name) => (
                <button key={name} type="button" role="radio" aria-checked={picked === name} className={picked === name ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => pick(name)}>{name}</button>
              ))}
              {shown.length === 0 && <span className="text-muted">No component matches.</span>}
            </div>
          </>
        )}
      </Card>
      {!list.data?.length ? (
        <Card><EmptyState icon="chat" title="No prompts yet">Add the default set for this project.</EmptyState>
          <button type="button" className="btn btn-primary" onClick={seed}>Add the default prompts</button></Card>
      ) : (
        <Card title="Pick one" description="Each is a short list of steps that uses Viber's tools.">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {list.data.map((entry) => (
              <button key={entry.key} type="button" title={entry.purpose}
                className={chosen === entry.key ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm'} onClick={() => open(entry.key)}>{entry.title}</button>
            ))}
          </div>
        </Card>
      )}
      {text !== null && (
        <Card title={list.data?.find((entry) => entry.key === chosen)?.title ?? 'Prompt'} description={list.data?.find((entry) => entry.key === chosen)?.purpose}>
          <pre className="viber-mono" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{text}</pre>
          <div style={{ marginTop: '0.75rem' }}><button type="button" className="btn btn-primary" onClick={copy}>Copy this prompt</button></div>
          {note && <Notice tone="success">{note}</Notice>}
        </Card>
      )}
    </>
  );
}
