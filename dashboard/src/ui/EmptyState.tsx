import type { ReactNode } from 'react';
import { Icon } from './Icon';

interface EmptyStateProps {
  icon?: string;
  title: ReactNode;
  /** What this list is for, in one line, so an empty page still teaches something. */
  children?: ReactNode;
  /** The action that fills it, usually the same as the page's primary. */
  action?: ReactNode;
  testId?: string;
}

export function EmptyState({ icon = 'inbox', title, children, action, testId }: EmptyStateProps) {
  return (
    <div className="empty-state" data-testid={testId}>
      <Icon name={icon} className="empty-state-icon" />
      <p className="empty-state-title">{title}</p>
      {children && <p className="empty-state-text">{children}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}

/** The shape of what is loading: lines of text, list rows, cards, stat tiles, a conversation,
 *  or a whole page (tiles over rows). */
export type LoadingShape = 'lines' | 'rows' | 'cards' | 'tiles' | 'chat' | 'page';

const lineWidth = (index: number) => `${92 - ((index * 17) % 40)}%`;

function SkeletonRows({ rows }: { rows: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className="skeleton-block skeleton-row">
          <span className="skeleton-dot" />
          <span className="skeleton-row-text">
            <span className="skeleton-line" style={{ width: lineWidth(index + 1) }} />
            <span className="skeleton-line skeleton-line-faint" style={{ width: lineWidth(index + 3) }} />
          </span>
        </span>
      ))}
    </>
  );
}

function SkeletonTiles({ count }: { count: number }) {
  return (
    <span className="skeleton-grid skeleton-grid-tiles">
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className="skeleton-block skeleton-tile">
          <span className="skeleton-line skeleton-line-faint" style={{ width: '50%' }} />
          <span className="skeleton-line skeleton-line-big" style={{ width: '70%' }} />
        </span>
      ))}
    </span>
  );
}

// Placeholders where the content will be, shaped like it, so the page keeps its shape while it
// loads and nothing jumps when the data lands (operator, 2026-11-19).
export function LoadingState({ rows = 4, label = 'Loading', shape = 'lines' }: { rows?: number; label?: string; shape?: LoadingShape }) {
  return (
    <div className={`loading-state loading-state-${shape}`} role="status" aria-label={label}>
      {shape === 'lines' && Array.from({ length: rows }, (_, index) => (
        <span key={index} className="skeleton-line" style={{ width: lineWidth(index) }} />
      ))}
      {shape === 'rows' && <SkeletonRows rows={rows} />}
      {shape === 'tiles' && <SkeletonTiles count={rows} />}
      {shape === 'cards' && (
        <span className="skeleton-grid skeleton-grid-cards">
          {Array.from({ length: rows }, (_, index) => (
            <span key={index} className="skeleton-block skeleton-card">
              <span className="skeleton-line skeleton-line-big" style={{ width: lineWidth(index) }} />
              <span className="skeleton-line skeleton-line-faint" />
              <span className="skeleton-line skeleton-line-faint" style={{ width: '64%' }} />
            </span>
          ))}
        </span>
      )}
      {shape === 'chat' && Array.from({ length: rows }, (_, index) => (
        <span key={index} className={`skeleton-block skeleton-bubble${index % 2 ? ' is-mine' : ''}`} style={{ width: `${46 + ((index * 23) % 30)}%` }}>
          <span className="skeleton-line" />
          <span className="skeleton-line skeleton-line-faint" style={{ width: '70%' }} />
        </span>
      ))}
      {shape === 'page' && (
        <>
          <span className="skeleton-line skeleton-line-big" style={{ width: '36%' }} />
          <SkeletonTiles count={4} />
          <SkeletonRows rows={rows} />
        </>
      )}
    </div>
  );
}
