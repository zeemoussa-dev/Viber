import type { KeyboardEvent, ReactNode } from 'react';

export interface Column<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  align?: 'start' | 'end';
  /** Hidden below this width, for a column that matters less on a phone. */
  hideBelow?: 'sm' | 'md';
  width?: string;
}

interface DataTableProps<Row> {
  /** The accessible name of the table. */
  label: string;
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  /** Makes each row open its detail. Row actions stop their own clicks from reaching it. */
  onRowClick?: (row: Row) => void;
  selectedKey?: string | null;
  /** Shown in place of the table when there are no rows: an EmptyState. */
  empty?: ReactNode;
  testId?: string;
  /** One id for every row, or one per row (channel-<platform>). */
  rowTestId?: string | ((row: Row) => string);
}

function cellClass(column: { align?: 'start' | 'end'; hideBelow?: 'sm' | 'md' }): string | undefined {
  const classes = [
    column.align === 'end' ? 'is-end' : '',
    column.hideBelow ? `hide-below-${column.hideBelow}` : '',
  ].filter(Boolean);
  return classes.length ? classes.join(' ') : undefined;
}

// Rows that share columns (UI-Guidelines §8). Wrapped so a wide table scrolls
// inside its card instead of widening the page.
export function DataTable<Row>({
  label, columns, rows, rowKey, onRowClick, selectedKey, empty, testId, rowTestId,
}: DataTableProps<Row>) {
  if (rows.length === 0 && empty) return <>{empty}</>;

  function onRowKeyDown(event: KeyboardEvent, row: Row) {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowClick?.(row);
    }
  }

  return (
    <div className="data-table-wrap">
      <table className="data-table" aria-label={label} data-testid={testId}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={cellClass(column)} style={column.width ? { width: column.width } : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const selected = selectedKey === key;
            return (
              <tr
                key={key}
                className={[onRowClick ? 'is-clickable' : '', selected ? 'is-selected' : ''].filter(Boolean).join(' ') || undefined}
                aria-selected={onRowClick ? selected : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                data-testid={typeof rowTestId === 'function' ? rowTestId(row) : rowTestId}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? (event) => onRowKeyDown(event, row) : undefined}
              >
                {columns.map((column) => (
                  <td key={column.key} className={cellClass(column)}>{column.render(row)}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// The two-line name cell every table starts with: the name, then the id people
// need for logs.
export function NameCell({ name, sub }: { name: ReactNode; sub?: ReactNode }) {
  return (
    <div className="name-cell">
      <span className="name-cell-name">{name}</span>
      {sub && <span className="name-cell-sub">{sub}</span>}
    </div>
  );
}

// Row actions: quiet until the row is hovered, and their clicks never open the row.
export function RowActions({ children }: { children: ReactNode }) {
  return (
    <div className="row-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
      {children}
    </div>
  );
}
