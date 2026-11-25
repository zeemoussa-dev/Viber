import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconButton } from './Icon';

interface DialogProps {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  /** The foot: FormActions order, Cancel then the primary at the right. */
  footer?: ReactNode;
  /** `xl` fills the screen, for a preview that needs the room (`UI-Guidelines.md` §2: use the width). */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  testId?: string;
  /** The Close button's id, where an existing one must be kept. */
  closeTestId?: string;
  /** Whether closing by Escape, the backdrop or the X asks first once something was typed.
   * On by default; the dialog's own Cancel button is a deliberate discard and never asks. */
  confirmDiscard?: boolean;
  /** `side` slides in from the right at full height: the edit drawer of a settings sheet
   * (`EditDrawer`, `UI-Guidelines.md` §2), so the page it edits stays in view beside it. */
  placement?: 'center' | 'side';
  children?: ReactNode;
}

// Open dialogs, oldest first. Each listens on the document, so without this a dialog opened
// over another (a folder picker over a drawer, a confirm over a form) closed both on one
// Escape. Only the newest answers Escape and Tab.
const openDialogs: symbol[] = [];

const FOCUSABLE ='button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

// The one popup (UI-Guidelines §10): Escape closes it, Tab stays inside it, and
// focus goes back to whatever opened it. Once something was typed in it, a close by
// Escape, the backdrop or the X asks "Discard changes?" first: those are the closes
// people make by accident, and they used to drop the form without a word (2026-11-07).
export function Dialog({
  title, description, onClose, footer, size = 'md', testId, closeTestId, confirmDiscard = true, placement = 'center', children,
}: DialogProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const edited = useRef(false);
  const [askingDiscard, setAskingDiscard] = useState(false);
  const askingRef = useRef(false);
  askingRef.current = askingDiscard;
  const closeRef = useRef(onClose);
  closeRef.current = () => {
    if (confirmDiscard && edited.current) setAskingDiscard(true);
    else onClose();
  };
  // Read during the first render: by the time the effect runs, a field's own
  // autoFocus has already moved focus into the dialog.
  const opener = useRef(document.activeElement as HTMLElement | null);

  useEffect(() => {
    const returnFocusTo = opener.current;
    // A field that asked for focus keeps it; otherwise the first control of the
    // content, not the Close button in the head.
    if (!panel.current?.contains(document.activeElement)) {
      const first = panel.current?.querySelector<HTMLElement>(`.dialog-body :is(${FOCUSABLE}), .dialog-foot :is(${FOCUSABLE})`)
        ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? panel.current)?.focus();
    }

    const me = Symbol('dialog');
    openDialogs.push(me);

    function onKeyDown(event: globalThis.KeyboardEvent) {
      // A dialog opened over this one (including "Discard changes?") owns the keys.
      if (openDialogs[openDialogs.length - 1] !== me) return;
      if (askingRef.current) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab' || !panel.current) return;
      const focusable = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (focusable.length === 0) return;
      const firstItem = focusable[0];
      const lastItem = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      openDialogs.splice(openDialogs.indexOf(me), 1);
      returnFocusTo?.focus?.();
    };
  }, []);

  // Portalled to the body: rendered inside a table cell or a transformed panel it
  // would inherit that alignment, font size and stacking context.
  return createPortal(
    <div
      className={`dialog-overlay${placement === 'side' ? ' dialog-overlay--side' : ''}`}
      onMouseDown={(event) => { if (event.target === event.currentTarget) closeRef.current(); }}
    >
      <div
        ref={panel}
        className={`dialog dialog-${size}${placement === 'side' ? ' dialog--side' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid={testId}
        onInput={() => { edited.current = true; }}
        onChange={() => { edited.current = true; }}
      >
        <header className="dialog-head">
          <h2 id={titleId} className="dialog-title">{title}</h2>
          <IconButton icon="close" label="Close" onClick={() => closeRef.current()} data-testid={closeTestId} />
        </header>
        {description && <p className="dialog-description">{description}</p>}
        {children && <div className="dialog-body">{children}</div>}
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </div>
      {askingDiscard && (
        <ConfirmDialog
          title="Discard changes?" confirmLabel="Discard changes" testId="dialog-discard"
          onConfirm={() => { setAskingDiscard(false); onClose(); }}
          onCancel={() => setAskingDiscard(false)}
        >
          What you changed in this window is not saved. Discard it, or go back and save it.
        </ConfirmDialog>
      )}
    </div>,
    document.body,
  );
}

interface ConfirmDialogProps {
  title: ReactNode;
  /** What will happen, and what will not: "The job is removed. The agent it runs is not." */
  children: ReactNode;
  /** A verb for what happens: "Delete job", never "OK". */
  confirmLabel: string;
  tone?: 'danger' | 'primary';
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  testId?: string;
  /** The confirm button's own id, where an existing one must be kept. Defaults to `<testId>-confirm`. */
  confirmTestId?: string;
}

export function ConfirmDialog({
  title, children, confirmLabel, tone = 'danger', busy, onConfirm, onCancel, testId, confirmTestId,
}: ConfirmDialogProps) {
  return (
    <Dialog
      title={title}
      onClose={onCancel}
      size="sm"
      testId={testId}
      confirmDiscard={false}
      footer={
        <>
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            type="button"
            className={tone === 'danger' ? 'btn btn-danger-solid' : 'btn btn-primary'}
            onClick={onConfirm}
            disabled={busy}
            data-testid={confirmTestId ?? (testId ? `${testId}-confirm` : undefined)}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="dialog-message">{children}</div>
    </Dialog>
  );
}
