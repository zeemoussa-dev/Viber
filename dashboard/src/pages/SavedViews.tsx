import { useState } from 'react';
import { apiFetch, useApi } from '../api';
import { Icon } from '../ui/Icon';
import { Notice } from '../ui/Notice';

/** What a view remembers: how the list is grouped, what is filtered and what is searched. */
export interface ViewChoice { group: string; filters: Record<string, string[]>; query: string }
interface SavedView { id: string; name: string; choice: ViewChoice }

/** Two views are the same when they would show the same thing, whatever order the filters were picked in. */
function signature(choice: ViewChoice): string {
  const filters = Object.entries(choice.filters).filter(([, values]) => values.length)
    .map(([id, values]) => [id, [...values].sort()] as const).sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify([choice.group, filters, (choice.query ?? '').trim().toLowerCase()]);
}

interface Props {
  project: string;
  list: string;
  current: ViewChoice;
  plain: ViewChoice; // the list as it opens: nothing filtered, nothing searched
  onOpen: (choice: ViewChoice) => void;
}

/** "My views": each is one press. They are kept in Viber, so every browser sees the same ones. */
export function SavedViews({ project, list, current, plain, onOpen }: Props) {
  const base = `/v1/projects/${project}/saved-views`;
  const views = useApi<SavedView[]>(`${base}?list=${encodeURIComponent(list)}`);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const now = signature(current);
  const open = (views.data ?? []).find((view) => signature(view.choice) === now) ?? null;
  const narrowed = current.query.trim() !== '' || Object.values(current.filters).some((values) => values.length);
  const changed = !open && (narrowed || current.group !== plain.group);
  const replaces = (views.data ?? []).some((view) => view.name.toLowerCase() === name.trim().toLowerCase());

  const run = (request: Promise<unknown>, after: () => void) => request
    .then(() => { setError(null); after(); views.reload(); })
    .catch((failure: Error) => setError(failure.message));
  const save = () => run(apiFetch(base, { method: 'PUT', body: JSON.stringify({ list, name: name.trim(), choice: current }) }), () => { setNaming(false); setName(''); });

  return (
    <div className="viber-views">
      <div className="viber-views-row" role="group" aria-label="My views">
        <button type="button" className={`viber-view${!narrowed && !open ? ' is-open' : ''}`} aria-pressed={!narrowed && !open}
          onClick={() => { setRemoving(false); onOpen(plain); }}>All</button>
        {(views.data ?? []).map((view) => (
          <button key={view.id} type="button" className={`viber-view${open?.id === view.id ? ' is-open' : ''}`} aria-pressed={open?.id === view.id}
            onClick={() => { setRemoving(false); onOpen(view.choice); }}><Icon name="bookmark" />{view.name}</button>
        ))}
        <span className="viber-views-end">
          {changed && !naming && <button type="button" className="btn btn-sm" onClick={() => setNaming(true)}><Icon name="bookmark_add" /> Save view</button>}
          {open && !removing && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRemoving(true)}>Remove view</button>}
          {open && removing && (
            <>
              <span className="text-muted">Remove “{open.name}”? Nothing in the list is deleted.</span>
              <button type="button" className="btn btn-sm btn-danger-solid" onClick={() => run(apiFetch(`${base}/${open.id}`, { method: 'DELETE' }), () => setRemoving(false))}>Remove</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRemoving(false)}>Keep</button>
            </>
          )}
        </span>
      </div>
      {naming && (
        <form className="viber-views-name" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void save(); }}>
          <input type="text" value={name} maxLength={60} autoFocus placeholder="Name this view" aria-label="View name"
            onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setNaming(false); }} />
          <button type="submit" className="btn btn-primary btn-sm" disabled={!name.trim()}>{replaces ? 'Replace' : 'Save'}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setNaming(false)}>Cancel</button>
        </form>
      )}
      {(error ?? views.error) && <Notice tone="error">{error ?? views.error}</Notice>}
    </div>
  );
}
