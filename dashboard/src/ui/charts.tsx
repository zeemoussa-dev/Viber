import type { ReactNode } from 'react';
import { CountUp } from './CountUp';

/** Shared charts (operator, 2026-11-02: "as much as possible use visuals and charts,
 * and make them readable"). Every chart names what it shows: a legend for two or more
 * series, a value on each bar or segment, an axis with units, and the exact figure on
 * hover. Colours are the `--chart-*` tokens in `styles/charts.css`, assigned in order
 * by slot and never cycled. */

/** A state, not a series: a part or bar that is a warning (a disk nearly full) takes the
 * app's own warning, danger or success colour in place of its series colour. Framework
 * API 14.1. */
export type ChartTone = 'warning' | 'danger' | 'success';

export interface ChartSegment { key: string; label: string; value: number; slot: number; tone?: ChartTone }

export const chartColor = (slot: number) => `var(--chart-${((slot - 1) % 8) + 1})`;

const TONE_COLOR: Record<ChartTone, string> = {
  warning: 'var(--color-warning)', danger: 'var(--color-danger)', success: 'var(--color-success)',
};

/** The colour a part is drawn in: its tone when it has one, else its series colour. */
export const partColor = (slot: number, tone?: ChartTone) => (tone ? TONE_COLOR[tone] : chartColor(slot));

export function ChartLegend({ items, format }: {
  items: Array<{ key: string; label: ReactNode; slot: number; tone?: ChartTone; value?: number }>;
  format?: (value: number) => string;
}) {
  return (
    <ul className="chart-legend">
      {items.map((item) => (
        <li key={item.key}>
          <span className={`chart-swatch${item.tone ? ' is-toned' : ''}`} style={{ backgroundColor: partColor(item.slot, item.tone) }} aria-hidden="true" />
          <span className="chart-legend-label">{item.label}</span>
          {item.value !== undefined && format && <span className="chart-legend-value">{format(item.value)}</span>}
        </li>
      ))}
    </ul>
  );
}

/** One whole split into its parts, as one bar, with each part's share written on it
 * when it is wide enough and always in the legend underneath. */
export function StackedBar({ segments, format, label, testId }: {
  segments: ChartSegment[]; format: (value: number) => string; label: string; testId?: string;
}) {
  const shown = segments.filter((segment) => segment.value > 0);
  const total = shown.reduce((sum, segment) => sum + segment.value, 0);
  if (total === 0) return null;
  const percent = (value: number) => Math.round((value / total) * 100);
  return (
    <figure className="chart" data-testid={testId}>
      <div className="chart-stack" role="img" aria-label={`${label}: ${shown.map((s) => `${s.label} ${format(s.value)}`).join(', ')}`}>
        {shown.map((segment) => (
          <span
            key={segment.key}
            className={`chart-stack-part${segment.tone ? ' is-toned' : ''}`}
            style={{ flexGrow: segment.value, backgroundColor: partColor(segment.slot, segment.tone) }}
            title={`${segment.label}: ${format(segment.value)} (${percent(segment.value)}%)`}
          >
            {percent(segment.value) >= 8 && <span className="chart-stack-text">{percent(segment.value)}%</span>}
          </span>
        ))}
      </div>
      <ChartLegend
        items={shown.map((segment) => ({
          key: segment.key, slot: segment.slot, tone: segment.tone, value: segment.value,
          label: <>{segment.label} <span className="text-muted">{percent(segment.value)}%</span></>,
        }))}
        format={format}
      />
    </figure>
  );
}

export interface BarRow { key: string; label: ReactNode; sub?: ReactNode; value: number; slot?: number; failed?: boolean; tone?: ChartTone }

/** How far one thing is towards its whole: a download, a disk, a quota. The value is
 * written beside the bar, and a tone marks a state such as nearly full. Framework API 14.1. */
export function ProgressBar({ value, max = 100, label, format, tone, testId }: {
  value: number; max?: number; label: ReactNode; format?: (value: number, max: number) => string;
  tone?: ChartTone; testId?: string;
}) {
  const share = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;
  const written = format ? format(value, max) : `${Math.round(share * 100)}%`;
  return (
    <div className="progress" data-testid={testId}>
      <div className="progress-head">
        <span className="progress-label">{label}</span>
        <span className="progress-value">{written}</span>
      </div>
      <div
        className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}
        aria-valuetext={written}
      >
        <span className={`progress-fill${tone ? ' is-toned' : ''}`} style={{ width: `${share * 100}%`, backgroundColor: partColor(1, tone) }} />
      </div>
    </div>
  );
}

export interface Stat { key: string; label: ReactNode; value: ReactNode; note?: ReactNode; tone?: ChartTone }

/** Headline figures, as many to a row as fit: a label, the figure, and a short note
 * (a change, a limit). A tone colours the figure for a state. Framework API 14.1. */
export function StatTiles({ stats, label, testId }: { stats: Stat[]; label: string; testId?: string }) {
  return (
    <div className="stat-tiles" role="list" aria-label={label} data-testid={testId}>
      {stats.map((stat) => (
        <div className="stat-tile" role="listitem" key={stat.key}>
          <span className="stat-tile-label">{stat.label}</span>
          <span className={`stat-tile-value${stat.tone ? ` is-${stat.tone}` : ''}`}>
            {typeof stat.value === 'string' || typeof stat.value === 'number' ? <CountUp value={stat.value} /> : stat.value}
          </span>
          {stat.note && <span className="stat-tile-note">{stat.note}</span>}
        </div>
      ))}
    </div>
  );
}

/** Ranked rows: a name, a bar to scale against the largest, and the value written out. */
export function HorizontalBars({ rows, format, label, testId }: {
  rows: BarRow[]; format: (value: number) => string; label: string; testId?: string;
}) {
  const highest = Math.max(...rows.map((row) => row.value), 0);
  if (rows.length === 0 || highest === 0) return null;
  return (
    <div className="chart-hbars" role="list" aria-label={label} data-testid={testId}>
      {rows.map((row) => (
        <div className="chart-hbar" role="listitem" key={row.key} title={`${typeof row.label === 'string' ? row.label : ''} ${format(row.value)}`.trim()}>
          <span className="chart-hbar-label">
            {row.label}
            {row.sub && <span className="chart-hbar-sub">{row.sub}</span>}
          </span>
          <span className="chart-hbar-track">
            <span
              className={`chart-hbar-fill${row.failed ? ' is-failed' : ''}${row.tone && !row.failed ? ' is-toned' : ''}`}
              style={{ width: `${Math.max((row.value / highest) * 100, 1)}%`, backgroundColor: row.failed ? undefined : partColor(row.slot ?? 1, row.tone) }}
            />
          </span>
          <span className="chart-hbar-value">{format(row.value)}</span>
        </div>
      ))}
    </div>
  );
}

export interface StackedRow { key: string; label: ReactNode; sub?: ReactNode; segments: ChartSegment[] }

/** One bar per thing, split into its parts and scaled against the largest whole: what
 * succeeded and what failed of each task on a single line, never two lines for one thing
 * (operator, 2026-11-19). The total is written beside the bar, each part on hover, and the
 * legend names the parts once. */
export function StackedBars({ rows, format, label, testId }: {
  rows: StackedRow[]; format: (value: number) => string; label: string; testId?: string;
}) {
  const totalOf = (row: StackedRow) => row.segments.reduce((sum, segment) => sum + Math.max(segment.value, 0), 0);
  const highest = Math.max(...rows.map(totalOf), 0);
  if (rows.length === 0 || highest === 0) return null;
  const legend = new Map<string, ChartSegment>();
  for (const row of rows) for (const segment of row.segments) if (!legend.has(segment.key)) legend.set(segment.key, segment);
  return (
    <figure className="chart" data-testid={testId}>
      <div className="chart-hbars" role="list" aria-label={label}>
        {rows.map((row) => {
          const total = totalOf(row);
          const parts = row.segments.filter((segment) => segment.value > 0);
          const spelled = parts.map((segment) => `${segment.label} ${format(segment.value)}`).join(', ');
          return (
            <div className="chart-hbar" role="listitem" key={row.key}
              title={`${typeof row.label === 'string' ? `${row.label}: ` : ''}${spelled || format(0)}`}>
              <span className="chart-hbar-label">
                {row.label}
                {row.sub && <span className="chart-hbar-sub">{row.sub}</span>}
              </span>
              <span className="chart-hbar-track">
                <span className="chart-hbar-stack" style={{ width: `${Math.max((total / highest) * 100, total ? 1 : 0)}%` }}>
                  {parts.map((segment) => (
                    <span
                      key={segment.key}
                      className={`chart-hbar-part${segment.tone ? ' is-toned' : ''}`}
                      style={{ flexGrow: segment.value, backgroundColor: partColor(segment.slot, segment.tone) }}
                      title={`${segment.label}: ${format(segment.value)}`}
                    />
                  ))}
                </span>
              </span>
              <span className="chart-hbar-value">
                {format(total)}
                {parts.filter((segment) => segment.tone).map((segment) => (
                  <span key={segment.key} className="text-muted">{` · ${format(segment.value)} ${segment.label.toLowerCase()}`}</span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
      {legend.size > 1 && (
        <ChartLegend items={[...legend.values()].map((segment) => ({ key: segment.key, label: segment.label, slot: segment.slot, tone: segment.tone }))} />
      )}
    </figure>
  );
}

export interface RangeRow { key: string; label: ReactNode; sub?: ReactNode; usual: number; slow: number }

/** How long something usually takes and how long it takes when it is slow, on one
 * shared scale, so the step worth improving is the longest bar. */
export function RangeBars({ rows, format, label, testId }: {
  rows: RangeRow[]; format: (value: number) => string; label: string; testId?: string;
}) {
  const highest = Math.max(...rows.map((row) => Math.max(row.slow, row.usual)), 0);
  if (rows.length === 0 || highest === 0) return null;
  return (
    <figure className="chart" data-testid={testId}>
      <div className="chart-hbars" role="list" aria-label={label}>
        {rows.map((row) => (
          <div className="chart-hbar" role="listitem" key={row.key} title={`usual ${format(row.usual)}, slow ${format(row.slow)}`}>
            <span className="chart-hbar-label">
              {row.label}
              {row.sub && <span className="chart-hbar-sub">{row.sub}</span>}
            </span>
            <span className="chart-hbar-track">
              <span className="chart-hbar-fill chart-range-slow" style={{ width: `${Math.max((row.slow / highest) * 100, 1)}%` }} />
              <span className="chart-hbar-fill chart-range-usual" style={{ width: `${Math.max((row.usual / highest) * 100, 1)}%` }} />
            </span>
            <span className="chart-hbar-value">{format(row.usual)} <span className="text-muted">/ {format(row.slow)}</span></span>
          </div>
        ))}
      </div>
      <ul className="chart-legend">
        <li><span className="chart-swatch chart-range-usual" aria-hidden="true" /><span className="chart-legend-label">Usual (median)</span></li>
        <li><span className="chart-swatch chart-range-slow" aria-hidden="true" /><span className="chart-legend-label">Slow (1 in 20 takes longer)</span></li>
      </ul>
    </figure>
  );
}

export interface ColumnPoint { key: string; label: string; values: Record<string, number> }
export interface ColumnSeries { key: string; label: string; slot: number; failed?: boolean }

function niceTop(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((candidate) => candidate * magnitude >= value) ?? 10;
  return step * magnitude;
}

/** Counts over time as stacked columns, with a value axis, gridlines, date labels that
 * thin out to stay readable, a legend, and each day's figures on hover. */
export function ColumnChart({ points, series, unit, label, testId, height = 180 }: {
  points: ColumnPoint[]; series: ColumnSeries[]; unit: string; label: string; testId?: string; height?: number;
}) {
  const totals = points.map((point) => series.reduce((sum, each) => sum + (point.values[each.key] ?? 0), 0));
  const top = niceTop(Math.max(...totals, 0));
  // Counts have no halves: a middle tick shows only when it is a whole number.
  const ticks = Number.isInteger(top / 2) ? [top, top / 2, 0] : [top, 0];
  const labelEvery = Math.max(1, Math.ceil(points.length / 10));
  if (points.length === 0) return null;
  return (
    <figure className="chart" data-testid={testId}>
      <div className="chart-columns" role="img" aria-label={label} style={{ height }}>
        <div className="chart-axis-y" aria-hidden="true">
          {ticks.map((tick) => <span key={tick}>{Number.isInteger(tick) ? tick : tick.toFixed(1)}</span>)}
        </div>
        <div className="chart-plot">
          {ticks.map((tick) => <span key={tick} className="chart-grid" style={{ bottom: `${(tick / top) * 100}%` }} />)}
          <div className="chart-plot-columns">
            {points.map((point, index) => (
              <div
                className="chart-column" key={point.key}
                title={`${point.label}: ${series.map((each) => `${point.values[each.key] ?? 0} ${each.label.toLowerCase()}`).join(', ')}`}
              >
                <div className="chart-column-stack">
                  {series.map((each) => {
                    const value = point.values[each.key] ?? 0;
                    return value > 0 ? (
                      <span
                        key={each.key}
                        className={`chart-column-part${each.failed ? ' is-failed' : ''}`}
                        style={{ height: `${(value / top) * 100}%`, background: each.failed ? undefined : chartColor(each.slot) }}
                      />
                    ) : null;
                  })}
                </div>
                <span className="chart-column-label">{index % labelEvery === 0 ? point.label : ''}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <figcaption className="chart-caption">
        <span className="text-muted">{unit} per day</span>
        {series.length > 1 && (
          <ul className="chart-legend">
            {series.map((each) => (
              <li key={each.key}>
                <span className={`chart-swatch${each.failed ? ' is-failed' : ''}`} style={each.failed ? undefined : { background: chartColor(each.slot) }} aria-hidden="true" />
                <span className="chart-legend-label">{each.label}</span>
              </li>
            ))}
          </ul>
        )}
      </figcaption>
    </figure>
  );
}
