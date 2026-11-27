import { useApi } from '../api';
import { useProject } from '../project';

interface Adr { context: string[]; decision: string[]; alternatives: string[]; consequences: string[]; supersedes: string | null; superseded_by: string | null }

/** A decision's statements, read when it is opened. */
export function DecisionBody({ adrKey }: { adrKey: string }) {
  const { project } = useProject();
  const { data, error } = useApi<Adr>(`/v1/projects/${project}/adr/${encodeURIComponent(adrKey)}`);
  if (error) return <p className="text-muted">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const parts: [string, string[]][] = [['Decision', data.decision], ['Why', data.context], ['Alternatives', data.alternatives], ['Consequences', data.consequences]];
  return (
    <div>
      {parts.filter(([, lines]) => lines.length > 0).map(([label, lines]) => (
        <div key={label}>
          <strong>{label}</strong>
          <ul>{lines.map((line, index) => <li key={index}>{line}</li>)}</ul>
        </div>
      ))}
      {data.supersedes && <p className="text-muted">Replaces {data.supersedes}</p>}
      {data.superseded_by && <p className="text-muted">Replaced by {data.superseded_by}</p>}
    </div>
  );
}
