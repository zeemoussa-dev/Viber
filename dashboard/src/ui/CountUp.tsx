import { useEffect, useRef, useState } from 'react';

/** One number in a text, with what is around it: "$1,234.50 spent" is "$", 1234.5, " spent". */
const ONE_NUMBER = /^(\D*?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\D*)$/;
const DURATION_MS = 900;

function motionAllowed(): boolean {
  if (document.documentElement.getAttribute('data-motion') === 'reduced') return false;
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

/** The written form of `value` at `share` of the way from zero, in the text's own format: its
 *  grouping, its decimals and the words around it. */
function written(parts: RegExpMatchArray, share: number): string {
  const [, before, whole, fraction = '', after] = parts;
  const decimals = fraction ? fraction.length - 1 : 0;
  const target = Number(whole.replace(/,/g, '') + fraction);
  const now = target * share;
  const text = whole.includes(',')
    ? now.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : now.toFixed(decimals);
  return `${before}${text}${after}`;
}

/** A figure that counts up from zero the first time it comes into view (operator, 2026-11-19). Text
 *  that is not one plain number, and a reader who asked for less motion, get the value as it is. */
export function CountUp({ value }: { value: string | number }) {
  const text = String(value);
  const parts = text.match(ONE_NUMBER);
  const element = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(() => (parts && motionAllowed() ? written(parts, 0) : text));
  const counted = useRef(false);

  useEffect(() => {
    if (!parts || !motionAllowed() || counted.current) {
      setShown(text);
      return;
    }
    const target = element.current;
    if (!target || typeof IntersectionObserver === 'undefined') {
      setShown(text);
      return;
    }
    let frame = 0;
    const watcher = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return;
      watcher.disconnect();
      counted.current = true;
      const started = performance.now();
      const step = (now: number) => {
        const progress = Math.min((now - started) / DURATION_MS, 1);
        // Ease out: quick at first, settling on the figure.
        const eased = 1 - Math.pow(1 - progress, 3);
        setShown(progress < 1 ? written(parts, eased) : text);
        if (progress < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    });
    watcher.observe(target);
    return () => {
      watcher.disconnect();
      if (frame) {
        cancelAnimationFrame(frame);
        // A value that changed while counting is shown as it now is, not counted again.
        counted.current = true;
      }
    };
  // Counting is for the first sight of a figure; a later change of value just shows it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  // Read aloud as the figure itself, never the numbers it passes on the way.
  return <span ref={element} aria-label={text}>{shown}</span>;
}
