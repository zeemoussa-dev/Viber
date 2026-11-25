import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';

export type NoticeTone = 'error' | 'warning' | 'success' | 'info';

const ICON_BY_TONE: Record<NoticeTone, string> = {
  error: 'error',
  warning: 'warning',
  success: 'check_circle',
  info: 'info',
};

interface NoticeProps {
  tone: NoticeTone;
  children: ReactNode;
  /** A Dismiss button, for a message about something already finished. */
  onDismiss?: () => void;
  /** A follow-up action, such as Retry, at the right of the message. */
  action?: ReactNode;
  testId?: string;
}

const TOAST_SHOWN_MS = 4500;
const TOAST_LEAVING_MS = 220;

function toastRegion(): HTMLElement {
  let region = document.getElementById('toast-region');
  if (!region) {
    region = document.createElement('div');
    region.id = 'toast-region';
    region.className = 'toast-region';
    document.body.appendChild(region);
  }
  return region;
}

/** A finished thing that can be dismissed ("Saved.") floats as a glass toast and closes by itself
 *  after a few seconds, a thin line showing the time left (operator, 2026-11-19). It stays while
 *  the pointer rests on it. Portalled to the page's root, so a frosted card or window it was
 *  raised in cannot trap it. */
function Toast({ children, onDismiss, action, testId }: { children: ReactNode; onDismiss: () => void; action?: ReactNode; testId?: string }) {
  const [leaving, setLeaving] = useState(false);
  const [paused, setPaused] = useState(false);
  const dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;

  useEffect(() => {
    if (paused || leaving) return undefined;
    const timer = window.setTimeout(() => setLeaving(true), TOAST_SHOWN_MS);
    return () => window.clearTimeout(timer);
  }, [paused, leaving]);

  useEffect(() => {
    if (!leaving) return undefined;
    const timer = window.setTimeout(() => dismiss.current(), TOAST_LEAVING_MS);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  return createPortal(
    <div
      className={`notice notice-success toast${leaving ? ' is-leaving' : ''}${paused ? ' is-paused' : ''}`}
      role="status"
      data-testid={testId}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
    >
      <Icon name={ICON_BY_TONE.success} className="notice-icon" />
      <div className="notice-text">{children}</div>
      {action && <div className="notice-action">{action}</div>}
      <button type="button" className="notice-dismiss" aria-label="Dismiss" title="Dismiss" onClick={() => setLeaving(true)}>
        <Icon name="close" />
      </button>
      {/* Keyed on the pause: leaving the toast starts the time over, bar and timer together. */}
      <span key={paused ? 'paused' : 'running'} className="toast-timer" style={{ animationDuration: `${TOAST_SHOWN_MS}ms` }} aria-hidden="true" />
    </div>,
    toastRegion(),
  );
}

// An error interrupts a screen reader; anything else waits its turn.
export function Notice({ tone, children, onDismiss, action, testId }: NoticeProps) {
  if (tone === 'success' && onDismiss) {
    return <Toast onDismiss={onDismiss} action={action} testId={testId}>{children}</Toast>;
  }
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'} data-testid={testId}>
      <Icon name={ICON_BY_TONE[tone]} className="notice-icon" />
      <div className="notice-text">{children}</div>
      {action && <div className="notice-action">{action}</div>}
      {onDismiss && (
        <button type="button" className="notice-dismiss" aria-label="Dismiss" title="Dismiss" onClick={onDismiss}>
          <Icon name="close" />
        </button>
      )}
    </div>
  );
}
