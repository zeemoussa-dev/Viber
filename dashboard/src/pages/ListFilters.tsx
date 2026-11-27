import { useState } from 'react';
import { Dialog } from '../ui/Dialog';
import { Icon } from '../ui/Icon';

/** The filter panel of a long list: one section per filter, one value per line, counts in a column. */
export interface FilterSection { id: string; label: string; values: [string, number][]; chosen: string[] }

const SHORT = 6;

function Section({ section, onToggle }: { section: FilterSection; onToggle: (value: string) => void }) {
  const [open, setOpen] = useState(section.chosen.length > 0);
  const [all, setAll] = useState(false);
  const [find, setFind] = useState('');
  const wanted = find.trim().toLowerCase();
  const matching = section.values.filter(([name]) => name.toLowerCase().includes(wanted));
  const visible = all || wanted ? matching : matching.filter(([name], index) => index < SHORT || section.chosen.includes(name));
  return (
    <section className="viber-filter">
      <button type="button" className="viber-row-button viber-filter-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name={open ? 'expand_more' : 'chevron_right'} />
        <span className="viber-row-name">{section.label}</span>
        <span className="viber-row-count">{section.chosen.length ? `${section.chosen.length} picked` : section.values.length}</span>
      </button>
      {open && (
        <div role="group" aria-label={section.label}>
          {section.values.length > SHORT * 2 && (
            <input className="viber-filter-find" type="search" value={find} placeholder={`Find in ${section.label.toLowerCase()}`}
              aria-label={`Find in ${section.label}`} onChange={(event) => setFind(event.target.value)} />
          )}
          {visible.map(([name, count]) => (
            <label key={name} className="viber-filter-value">
              <input type="checkbox" checked={section.chosen.includes(name)} onChange={() => onToggle(name)} />
              <span className="viber-row-name">{name}</span>
              <span className="viber-row-count">{count}</span>
            </label>
          ))}
          {!wanted && section.values.length > visible.length && (
            <button type="button" className="btn-link viber-filter-more" onClick={() => setAll(true)}>Show all {section.values.length}</button>
          )}
          {!wanted && all && section.values.length > SHORT && (
            <button type="button" className="btn-link viber-filter-more" onClick={() => setAll(false)}>Show fewer</button>
          )}
        </div>
      )}
    </section>
  );
}

interface Props {
  sections: FilterSection[];
  shown: number;
  onToggle: (sectionId: string, value: string) => void;
  onClear: () => void;
  onClose: () => void;
}

export function FilterPanel({ sections, shown, onToggle, onClear, onClose }: Props) {
  const picked = sections.reduce((total, section) => total + section.chosen.length, 0);
  return (
    <Dialog title="Filters" placement="side" size="sm" confirmDiscard={false} onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" disabled={picked === 0} onClick={onClear}>Clear all</button>
          <button type="button" className="btn btn-primary" onClick={onClose}>Show {shown}</button>
        </>
      }>
      {sections.map((section) => <Section key={section.id} section={section} onToggle={(value) => onToggle(section.id, value)} />)}
    </Dialog>
  );
}
