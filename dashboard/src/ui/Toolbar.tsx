import type { KeyboardEvent, ReactNode } from 'react';
import { Icon } from './Icon';

// Filters and secondary actions above the list they act on (`ADR-091` rule 5).
// `end` pushes its contents to the right edge, where a Refresh belongs.
export function Toolbar({ children, end }: { children?: ReactNode; end?: ReactNode }) {
  return (
    <div className="page-toolbar">
      {children}
      {end && <div className="page-toolbar-end">{end}</div>}
    </div>
  );
}

interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Says what is searched: "Search jobs". Also the accessible name. */
  placeholder: string;
  testId?: string;
  autoFocus?: boolean;
  /** Enter to commit a search, Escape to clear it, where a page wants that. */
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
}

export function SearchField({ value, onChange, placeholder, testId, autoFocus, onKeyDown }: SearchFieldProps) {
  return (
    <label className="search-field">
      <Icon name="search" />
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        data-testid={testId}
        autoFocus={autoFocus}
        onKeyDown={onKeyDown}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
