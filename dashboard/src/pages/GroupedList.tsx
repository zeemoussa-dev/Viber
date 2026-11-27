import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { EmptyState } from '../ui/EmptyState';
import { Icon } from '../ui/Icon';
import { SearchField } from '../ui/Toolbar';
import { FilterPanel } from './ListFilters';
import { SavedViews, type ViewChoice } from './SavedViews';

/** One way to look at a long list: search, filter in a side panel, group, fold, show a few at a time, select many.
 *  The last choices are remembered in this browser; named views are kept in Viber. Buttons only: no dropdowns. */
export interface Facet<T> { id: string; label: string; of: (row: T) => string[] }

interface Props<T> {
  id: string; // "<project>.<list>": remembers the choices and holds the saved views
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

function remembered(id: string, defaultGroup: string): Choice {
  try {
    const saved = JSON.parse(localStorage.getItem(`viber.list.${id}`) ?? 'null') as Choice | null;
    if (saved && typeof saved.group === 'string' && saved.filters) return saved;
  } catch { /* a blocked or old store only loses the choices */ }
  return { group: defaultGroup, filters: {} };
}

export function GroupedList<T>({ id, rows, rowKey, text, facets, defaultGroup, render, actions, empty }: Props<T>) {
  const [choice, setChoice] = useState<Choice>(() => remembered(id, defaultGroup));
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [limit, setLimit] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);
  const project = id.slice(0, id.lastIndexOf('.'));
  const list = id.slice(id.lastIndexOf('.') + 1);

  useEffect(() => { setChoice(remembered(id, defaultGroup)); setSelected(new Set()); setQuery(''); setOpen({}); }, [id, defaultGroup]);
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

  const applied = facets.flatMap((facet) => active(facet.id).map((value) => ({ facet, value })));
  const sections = facets.map((facet) => ({ id: facet.id, label: facet.label, values: available[facet.id], chosen: active(facet.id) }))
    .filter((section) => section.values.length > 1);
  const openView = (view: ViewChoice) => {
    setChoice({ group: view.group, filters: view.filters });
    setQuery(view.query ?? '');
    setOpen({});
    setSelected(new Set());
  };
  const clearFilters = () => { setQuery(''); setChoice({ ...choice, filters: {} }); };
  const allOpen = ordered.every(([name]) => open[name]);

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
    <div className="viber-list">
      <SavedViews project={project} list={list} current={{ group: choice.group, filters: Object.fromEntries(facets.map((f) => [f.id, active(f.id)]).filter(([, v]) => v.length)), query }}
        plain={{ group: defaultGroup, filters: {}, query: '' }} onOpen={openView} />
      <div className="viber-list-bar">
        <SearchField value={query} onChange={setQuery} placeholder="Search these" />
        {sections.length > 0 && (
          <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setFiltersOpen(true)}>
            <Icon name="tune" /> Filters{applied.length > 0 && <span className="viber-badge-count">{applied.length}</span>}
          </button>
        )}
        <div className="viber-list-group">
          <span className="text-muted">Group by</span>
          <div className="segmented segmented-sm" role="radiogroup" aria-label="Group by">
            {[...facets.map((f) => ({ id: f.id, label: f.label })), { id: '', label: 'None' }].map((option) => (
              <button key={option.id} type="button" role="radio" aria-checked={choice.group === option.id} className={`segmented-option${choice.group === option.id ? ' is-chosen' : ''}`}
                onClick={() => { setChoice({ ...choice, group: option.id }); setOpen({}); }}>{option.label}</button>
            ))}
          </div>
        </div>
      </div>
      {filtersOpen && <FilterPanel sections={sections} shown={shown.length} onToggle={toggleFilter} onClear={() => setChoice({ ...choice, filters: {} })} onClose={() => setFiltersOpen(false)} />}
      {applied.length > 0 && (
        <div className="viber-applied" aria-label="Filters in use">
          {applied.map(({ facet, value }) => (
            <button key={`${facet.id}:${value}`} type="button" className="viber-applied-chip" aria-label={`Remove filter ${facet.label}: ${value}`} onClick={() => toggleFilter(facet.id, value)}>
              <span className="text-muted">{facet.label}:</span> {value} <Icon name="close" />
            </button>
          ))}
        </div>
      )}
      <div className="viber-list-summary">
        <span><strong>{shown.length}</strong> <span className="text-muted">{filtering ? `of ${rows.length}` : 'in this list'}</span></span>
        {filtering && <button type="button" className="btn-link" onClick={clearFilters}>Clear</button>}
        <span className="viber-list-summary-end">
          {groupFacet && ordered.length > 1 && <button type="button" className="btn-link" onClick={() => setOpen(Object.fromEntries(ordered.map(([name]) => [name, !allOpen])))}>{allOpen ? 'Fold all' : 'Open all'}</button>}
          {actions && shown.length > 0 && <button type="button" className="btn-link" onClick={() => selectMany(shown, picked.length !== shown.length)}>{picked.length === shown.length ? 'Select none' : `Select all ${shown.length}`}</button>}
        </span>
      </div>
      {actions && picked.length > 0 && (
        <div className="viber-selection">
          <strong>{picked.length} selected</strong>
          {actions(picked, () => setSelected(new Set()))}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}
      {shown.length === 0 && <EmptyState icon="filter_alt_off" title={rows.length === 0 ? (empty ?? 'Nothing here') : 'Nothing matches the filters'} />}
      {shown.length > 0 && ordered.map(([name, items]) => {
        // With one group, or while searching, there is nothing to fold away.
        const alwaysOpen = !groupFacet || ordered.length === 1 || words.length > 0;
        const isOpen = alwaysOpen || !!open[name];
        const max = limit[name] ?? PAGE;
        const all = items.every((r) => selected.has(rowKey(r)));
        return (
          <section key={name || 'all'}>
            {groupFacet && (
              <div className="viber-group-head">
                <button type="button" className="viber-row-button" aria-expanded={isOpen} disabled={alwaysOpen} onClick={() => setOpen({ ...open, [name]: !isOpen })}>
                  <Icon name={isOpen ? 'expand_more' : 'chevron_right'} />
                  <span className="viber-row-name">{name}</span>
                  <span className="viber-row-count">{items.length}</span>
                </button>
                {actions && <button type="button" className="btn-link" onClick={() => selectMany(items, !all)}>{all ? 'Unselect' : 'Select'}</button>}
              </div>
            )}
            {isOpen && items.slice(0, max).map((r) => (
              <div key={rowKey(r)} className="viber-review-item viber-list-row">
                {actions && <input type="checkbox" aria-label="Select" checked={selected.has(rowKey(r))} onChange={(event) => selectMany([r], event.target.checked)} />}
                <div className="viber-list-row-body">{render(r)}</div>
              </div>
            ))}
            {isOpen && items.length > max && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLimit({ ...limit, [name]: max + 50 })}>Show more ({items.length - max} left)</button>}
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
