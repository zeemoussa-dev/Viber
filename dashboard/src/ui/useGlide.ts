import { useLayoutEffect, useState, type RefObject } from 'react';

export interface GlideBox {
  x: number;
  y: number;
  width: number;
  height: number;
  /** False on the first placement, so the highlight appears where it belongs instead of
   *  sliding in from the corner. */
  moving: boolean;
}

/** Where the chosen option of a group sits inside it, kept current as the choice, the group's
 *  size or its wrapping changes, so one highlight can glide from option to option (operator,
 *  2026-11-19). `selector` finds the chosen option; the container must be the options'
 *  offset parent (position: relative). */
export function useGlide(container: RefObject<HTMLElement | null>, selector: string, chosen: unknown): GlideBox | null {
  const [box, setBox] = useState<GlideBox | null>(null);

  useLayoutEffect(() => {
    const group = container.current;
    if (!group) return undefined;
    const measure = () => {
      const option = group.querySelector<HTMLElement>(selector);
      if (!option) { setBox(null); return; }
      const next = { x: option.offsetLeft, y: option.offsetTop, width: option.offsetWidth, height: option.offsetHeight };
      setBox((current) => {
        if (current && current.x === next.x && current.y === next.y && current.width === next.width && current.height === next.height) return current;
        return { ...next, moving: current !== null };
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(group);
    for (const child of Array.from(group.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [container, selector, chosen]);

  return box;
}

export function glideStyle(box: GlideBox) {
  return {
    width: box.width,
    height: box.height,
    transform: `translate(${box.x}px, ${box.y}px)`,
  };
}
