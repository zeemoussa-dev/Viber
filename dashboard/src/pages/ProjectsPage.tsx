import { useState } from 'react';
import { post } from '../api';
import { useProject } from '../project';
import { Card } from '../ui/Card';
import { DataTable } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { Notice } from '../ui/Notice';
import { PageHeader } from '../ui/PageHeader';
import { StatusBadge } from '../ui/StatusBadge';

export function ProjectsPage() {
  const { project, projects, choose, reloadProjects } = useProject();
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);

  async function create() {
    setProblem(null);
    try {
      await post('/v1/projects', { key: key.trim(), name: name.trim() || key.trim() });
      choose(key.trim());
      setKey(''); setName('');
      reloadProjects();
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  }

  return (
    <>
      <PageHeader title="Projects" description="Memory, work and the component map are kept per project." />
      <Card padded={false}>
        <DataTable<{ key: string; name: string }>
          label="Projects" rows={projects} rowKey={(row) => row.key}
          empty={<EmptyState icon="folder_open" title="No projects yet">Create the first one below.</EmptyState>}
          columns={[
            { key: 'name', header: 'Project', render: (row) => <>{row.name} <span className="text-muted viber-mono">{row.key}</span></> },
            { key: 'use', header: '', align: 'end', render: (row) => row.key === project
              ? <StatusBadge tone="success">current</StatusBadge>
              : <button type="button" className="btn btn-ghost btn-sm" onClick={() => choose(row.key)}>Use</button> },
          ]}
        />
      </Card>
      <Card title="New project" className="viber-section-gap">
        {problem && <Notice tone="error">{problem}</Notice>}
        <form className="viber-token" onSubmit={(event) => { event.preventDefault(); void create(); }}>
          <input value={key} placeholder="key (lowercase, e.g. sbos)" aria-label="Project key" onChange={(event) => setKey(event.target.value)} />
          <input value={name} placeholder="Name" aria-label="Project name" onChange={(event) => setName(event.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={!/^[a-z0-9][a-z0-9_-]*$/.test(key.trim())}>Create</button>
        </form>
      </Card>
    </>
  );
}
