import type { ButtonHTMLAttributes } from 'react';

// Material Symbols, self-hosted (tokens.css). An icon beside text is decoration,
// so it is hidden from screen readers unless it is given a label.
export function Icon({ name, label, className }: { name: string; label?: string; className?: string }) {
  return (
    <span
      className={`material-symbols-outlined icon${className ? ` ${className}` : ''}`}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
    >
      {name}
    </span>
  );
}

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: string;
  /** The accessible name, shown as the tooltip too: an icon alone says nothing to a screen reader. */
  label: string;
}

export function IconButton({ icon, label, className, type = 'button', ...rest }: IconButtonProps) {
  return (
    <button
      type={type}
      className={`btn btn-ghost btn-icon${className ? ` ${className}` : ''}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
}
