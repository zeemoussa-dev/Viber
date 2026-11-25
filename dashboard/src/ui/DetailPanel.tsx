import type { ReactNode } from 'react';
import { Dialog } from './Dialog';

// A list, and the item picked from it opens as a flyover from the right (the same
// side drawer every other editor in the app uses), so the list stays in view behind it.
export function SplitView({ children, detail }: { children: ReactNode; detail?: ReactNode }) {
  return (
    <div className="split-view">
      <div className="split-view-main">{children}</div>
      {detail}
    </div>
  );
}

interface DetailPanelProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** StatusBadges and tags, under the title. */
  badges?: ReactNode;
  onClose?: () => void;
  /** The panel's own actions, at its foot. */
  actions?: ReactNode;
  testId?: string;
  children: ReactNode;
}

export function DetailPanel({ title, subtitle, badges, onClose, actions, testId, children }: DetailPanelProps) {
  return (
    <Dialog
      title={title}
      description={subtitle}
      onClose={onClose ?? (() => undefined)}
      footer={actions}
      placement="side"
      size="lg"
      testId={testId}
      confirmDiscard={false}
    >
      {badges && <div className="detail-panel-badges">{badges}</div>}
      {children}
    </Dialog>
  );
}
