import type { ReactNode } from 'react';
import { InfoButton } from './InfoButton';

interface CardProps {
  title?: ReactNode;
  /** A help entry's id: an ⓘ beside the title (`ADR-118`). */
  info?: string;
  description?: ReactNode;
  /** Sits at the right of the title row: a card's own actions, never the page's main one. */
  actions?: ReactNode;
  /** False for a card whose child draws its own edge to edge, such as a DataTable. */
  padded?: boolean;
  className?: string;
  testId?: string;
  children: ReactNode;
}

export function Card({ title, info, description, actions, padded = true, className, testId, children }: CardProps) {
  return (
    <section className={`card card-framed${className ? ` ${className}` : ''}`} data-testid={testId}>
      {(title || actions) && (
        <header className="card-head">
          <div className="card-head-text">
            {title && <h2 className="card-title">{title}{info && <InfoButton topic={info} className="card-title-info" />}</h2>}
            {description && <p className="card-description">{description}</p>}
          </div>
          {actions && <div className="card-head-actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'card-body' : 'card-body card-body-flush'}>{children}</div>
    </section>
  );
}
