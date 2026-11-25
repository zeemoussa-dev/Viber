import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { useGlide } from './useGlide';

export interface TabItem {
  value: string;
  label: ReactNode;
  count?: number;
}

interface TabsProps {
  label: string;
  value: string;
  tabs: TabItem[];
  onChange: (value: string) => void;
  testId?: string;
}

// Sections of one thing. The page renders the chosen section itself, so a tab's
// content can stay mounted or not as the page needs.
export function Tabs({ label, value, tabs, onChange, testId }: TabsProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const row = useRef<HTMLDivElement>(null);
  const glide = useGlide(row, '.page-tab--active', value);

  function onKeyDown(event: KeyboardEvent, index: number) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + tabs.length) % tabs.length;
    onChange(tabs[next].value);
    buttons.current[next]?.focus();
  }

  return (
    <div ref={row} className={glide ? 'page-tabs has-glide' : 'page-tabs'} role="tablist" aria-label={label} data-testid={testId}>
      {glide && (
        <span
          className={glide.moving ? 'page-tabs-glide is-moving' : 'page-tabs-glide'}
          style={{ width: glide.width, transform: `translate(${glide.x}px, ${glide.y + glide.height - 2}px)` }}
          aria-hidden="true"
        />
      )}
      {tabs.map((tab, index) => (
        <button
          key={tab.value}
          ref={(element) => { buttons.current[index] = element; }}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          tabIndex={tab.value === value ? 0 : -1}
          className={tab.value === value ? 'page-tab page-tab--active' : 'page-tab'}
          data-testid={testId ? `${testId}-${tab.value}` : undefined}
          onClick={() => onChange(tab.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="page-tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}
