import { useState } from 'react';
import { apiFetch, post, useApi } from '../api';
import { useProject } from '../project';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';

interface Prompt { key: string; title: string; purpose: string }

export function PromptsPage() {
  const { project } = useProject();
  const list = useApi<Prompt[]>(project ? `/v1/projects/${project}/prompts` : null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [component, setComponent] = useState('');
  const [text, setText] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function open(key: string) {
    setProblem(null); setNote(null); setChosen(key);
    try {
      const suffix = component.trim() ? `?component=${encodeURIComponent(component.trim())}` : '';
      setText(await apiFetch<string>(`/v1/projects/${project}/prompts/${key}${suffix}`));
    } catch (failure) { setProblem((failure as Error).message); }
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
      <PageHeader title="Prompts" description={`What to give a session so it starts knowing what to do in ${project}. {project} and the component are filled in for you.`} />
      {problem && <Notice tone="error">{problem}</Notice>}
      <Card title="Component (only for the component prompt)" padded>
        <div className="viber-token">
          <input value={component} aria-label="Component" placeholder="for example sb-fleet" onChange={(event) => setComponent(event.target.value)} />
        </div>
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
