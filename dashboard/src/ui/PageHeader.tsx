import type { ReactNode } from 'react';

// Every screen's title row; the page's main action sits top right (same markup as second_brain's).
interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {description && <p className="text-muted">{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
