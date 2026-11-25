import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useApi } from './api';

const PROJECT_KEY = 'viber.project';

export interface ProjectSummary { key: string; name: string }

interface ProjectContextValue {
  /** The chosen project's key, or null while projects load or none exist. */
  project: string | null;
  projects: ProjectSummary[];
  choose: (key: string) => void;
  reloadProjects: () => void;
  loading: boolean;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

function remembered(): string | null {
  try { return localStorage.getItem(PROJECT_KEY); } catch { return null; }
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { data, loading, reload } = useApi<ProjectSummary[]>('/v1/projects');
  const [chosen, setChosen] = useState<string | null>(remembered);
  const projects = data ?? [];
  const project = projects.find((entry) => entry.key === chosen)?.key ?? projects[0]?.key ?? null;

  useEffect(() => {
    if (project) { try { localStorage.setItem(PROJECT_KEY, project); } catch { /* optional */ } }
  }, [project]);

  const value = useMemo<ProjectContextValue>(
    () => ({ project, projects, choose: setChosen, reloadProjects: reload, loading }),
    [project, projects, reload, loading],
  );
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) throw new Error('useProject outside ProjectProvider');
  return value;
}

/** A path under the chosen project, or null until one is chosen. */
export function projectPath(project: string | null, rest: string): string | null {
  return project ? `/v1/projects/${project}${rest}` : null;
}
