import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { EmptyState } from '../ui/EmptyState';
import { SearchField, Toolbar } from '../ui/Toolbar';

/** One way to look at a long list: search, filter by any facet, group, fold, show a few at a time, select many.
 *  The choices are remembered in this browser, per list and project. Buttons only: no dropdowns. */
export interface Facet<T> { id: string; label: string; of: (row: T) => string[] }

interface Props<T> {
  id: string; // remembers the choices
  rows: T[];
  rowKey: (row: T) => string;
  text: (row: T) => string; // what search looks in
  facets: Facet<T>[]; // each can filter and group
  defaultGroup: string; // a facet id, or '' for no grouping
  render: (row: T) => ReactNode;
  actions?: (selected: T[], clear: () => void) => ReactNode; // shown when rows are selected
  empty?: string;
}

interface Choice { group: string; filters: Record<string, string[]> }
const PAGE = 15;
const CHIPS = 12;

function remembered(id: string, defaultGroup: string): Choice {
  try {
    const saved = JSON.parse(localStorage.getItem(`viber.list.${id}`) ?? 'null') as Choice | null;
    if (saved && typeof saved.group === 'string' && saved.filters) return saved;
  } catch { /* a blocked or old store only loses the choices */ }
  return { group: defaultGroup, filters: {} };
}

const chip = (on: boolean) => (on ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm');
const row = { display: 'flex', flexWrap: 'wrap', gap: '0.35rem', alignItems: 'center', margin: '0.35rem 0' } as const;

export function GroupedList<T>({ id, rows, rowKey, text, facets, defaultGroup, render, actions, empty }: Props<T>) {
  const [choice, setChoice] = useState<Choice>(() => remembered(id, defaultGroup));
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [limit, setLimit] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => { setChoice(remembered(id, defaultGroup)); setSelected(new Set()); }, [id, defaultGroup]);
  useEffect(() => { try { localStorage.setItem(`viber.list.${id}`, JSON.stringify(choice)); } catch { /* optional */ } }, [id, choice]);

  // A remembered filter for a value that no longer exists is ignored, so it can never hide everything unseen.
  const available = useMemo(() => Object.fromEntries(facets.map((facet) => {
    const counts = new Map<string, number>();
    rows.forEach((r) => facet.of(r).forEach((v) => counts.set(v, (counts.get(v) ?? 0) + 1)));
    return [facet.id, [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))];
  })), [rows, facets]);

  const active = (facetId: string) => (choice.filters[facetId] ?? []).filter((v) => available[facetId]?.some(([name]) => name === v));
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = rows.filter((r) => facets.every((facet) => {
    const wanted = active(facet.id);
    return wanted.length === 0 || facet.of(r).some((v) => wanted.includes(v));
  }) && words.every((w) => text(r).toLowerCase().includes(w)));

  const groupFacet = facets.find((facet) => facet.id === choice.group);
  const groups = new Map<string, T[]>();
  if (groupFacet) shown.forEach((r) => (groupFacet.of(r).length ? groupFacet.of(r) : ['(none)']).forEach((name) => groups.set(name, [...(groups.get(name) ?? []), r])));
  else groups.set('', shown);
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  const filtering = words.length > 0 || facets.some((facet) => active(facet.id).length > 0);
  const picked = shown.filter((r) => selected.has(rowKey(r))); // only what is still visible can be acted on

  const toggleFilter = (facetId: string, value: string) => {
    const now = active(facetId);
    setChoice({ ...choice, filters: { ...choice.filters, [facetId]: now.includes(value) ? now.filter((v) => v !== value) : [...now, value] } });
  };
  const selectMany = (list: T[], on: boolean) => setSelected((held) => {
    const next = new Set(held);
    list.forEach((r) => (on ? next.add(rowKey(r)) : next.delete(rowKey(r))));
    return next;
  });

  return (
    <div>
      <Toolbar><SearchField value={query} onChange={setQuery} placeholder="Search these" /></Toolbar>
      <div style={row} role="radiogroup" aria-label="Group by">
        <span className="text-muted">Group by</span>
        {[...facets.map((f) => ({ id: f.id, label: f.label })), { id: '', label: 'Nothing' }].map((option) => (
          <button key={option.id} type="button" role="radio" aria-checked={choice.group === option.id} className={chip(choice.group === option.id)}
            onClick={() => { setChoice({ ...choice, group: option.id }); setOpen({}); }}>{option.label}</button>
        ))}
      </div>
      {facets.filter((facet) => (available[facet.id]?.length ?? 0) > 1).map((facet) => {
        const values = available[facet.id];
        const wanted = active(facet.id);
        const visible = expanded[facet.id] ? values : values.filter(([name], index) => index < CHIPS || wanted.includes(name));
        return (
          <div key={facet.id} style={row} role="group" aria-label={`Filter by ${facet.label}`}>
            <span className="text-muted">{facet.label}</span>
            {visible.map(([name, count]) => (
              <button key={name} type="button" aria-pressed={wanted.includes(name)} className={chip(wanted.includes(name))} onClick={() => toggleFilter(facet.id, name)}>{name} · {count}</button>
            ))}
            {values.length > CHIPS && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded({ ...expanded, [facet.id]: !expanded[facet.id] })}>
                {expanded[facet.id] ? 'Show fewer' : `${values.length - visible.length} more…`}
              </button>
            )}
          </div>
        );
      })}
      <div style={row}>
        <strong>{shown.length}</strong><span className="text-muted">of {rows.length} shown</span>
        {filtering && <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setQuery(''); setChoice({ ...choice, filters: {} }); }}>Clear filters</button>}
        {groupFacet && ordered.length > 1 && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(Object.fromEntries(ordered.map(([name]) => [name, !ordered.every(([n]) => open[n])])))}>{ordered.every(([n]) => open[n]) ? 'Fold all' : 'Open all'}</button>}
        {actions && shown.length > 0 && <button type="button" className="btn btn-ghost btn-sm" onClick={() => selectMany(shown, picked.length !== shown.length)}>{picked.length === shown.length ? 'Select none' : `Select all ${shown.length} shown`}</button>}
      </div>
      {actions && picked.length > 0 && (
        <div style={{ ...row, position: 'sticky', top: 0, zIndex: 2, padding: '0.5rem', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '0.5rem' }}>
          <strong>{picked.length} selected</strong>
          {actions(picked, () => setSelected(new Set()))}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}
      {shown.length === 0 && <EmptyState icon="filter_alt_off" title={rows.length === 0 ? (empty ?? 'Nothing here') : 'Nothing matches the filters'} />}
      {shown.length > 0 && ordered.map(([name, list]) => {
        // With one group, or while searching, there is nothing to fold away.
        const isOpen = !groupFacet || ordered.length === 1 || words.length > 0 || !!open[name];
        const max = limit[name] ?? PAGE;
        const all = list.every((r) => selected.has(rowKey(r)));
        return (
          <section key={name || 'all'} style={{ marginTop: '0.5rem' }}>
            {groupFacet && (
              <div style={row}>
                <button type="button" className="btn btn-ghost" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [name]: !isOpen })}>{isOpen ? '▾' : '▸'} {name} · {list.length}</button>
                {actions && <button type="button" className="btn btn-ghost btn-sm" onClick={() => selectMany(list, !all)}>{all ? 'Unselect group' : 'Select group'}</button>}
              </div>
            )}
            {isOpen && list.slice(0, max).map((r) => (
              <div key={rowKey(r)} className="viber-review-item" style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                {actions && <input type="checkbox" aria-label="Select" style={{ marginTop: '0.35rem' }} checked={selected.has(rowKey(r))} onChange={(event) => selectMany([r], event.target.checked)} />}
                <div style={{ flex: 1, minWidth: 0 }}>{render(r)}</div>
              </div>
            ))}
            {isOpen && list.length > max && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLimit({ ...limit, [name]: max + 50 })}>Show more ({list.length - max} left)</button>}
          </section>
        );
      })}
    </div>
  );
}

/** Where a rule or fact came from, in words a person knows. */
export function sourceName(source: string | null | undefined): string {
  if (!source) return 'Written in a session';
  const names: Record<string, string> = {
    core: 'Core rules', 'v2-memory': 'v2 memory', 'v2-memory-branch': 'v2 memory (branch)', 'v2-claude-md': 'v2 CLAUDE.md', 'v2-pipeline': 'v2 old pipeline',
    'v2-learnings': 'v2 learnings', 'sbos-memory': 'Your feedback notes', 'v2-claude-memory': 'v2 Claude memory', 'v3repos:MEMORY.md': 'v3 repo memory',
    'v3repos:CLAUDE.md': 'v3 repo CLAUDE.md', 'v3repos:PROJECTS.md': 'v3 project list', consolidation: 'Consolidation', reflection: 'Reflection', 'rule-review': 'Rule review',
  };
  return names[source] ?? source;
}
