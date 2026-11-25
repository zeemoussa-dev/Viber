import type { ReactNode } from 'react';

// The tone is the meaning, not a colour choice (UI-Guidelines §9), so a screen
// says "danger" and the theme decides what danger looks like.
export type StatusTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral' | 'accent';

interface StatusBadgeProps {
  tone: StatusTone;
  children: ReactNode;
  title?: string;
  testId?: string;
}

export function StatusBadge({ tone, children, title, testId }: StatusBadgeProps) {
  return (
    <span className={`badge badge-status badge-${tone}`} title={title} data-testid={testId}>
      {children}
    </span>
  );
}
