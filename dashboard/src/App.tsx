import { useEffect, useState } from 'react';
import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router';
import { getToken, onUnauthorized, setToken } from './api';
import { ProjectProvider, useProject } from './project';
import { Card } from './ui/Card';
import { EmptyState } from './ui/EmptyState';
import { Notice } from './ui/Notice';
import { PageHeader } from './ui/PageHeader';
import { MapPage } from './pages/MapPage';
import { MemoryPage } from './pages/MemoryPage';
import { Overview } from './pages/Overview';
import { ProjectsPage } from './pages/ProjectsPage';
import { PromptsPage } from './pages/PromptsPage';
import { ReviewPage } from './pages/ReviewPage';
import { SessionsPage } from './pages/SessionsPage';
import { SystemPage } from './pages/SystemPage';
import { WorkPage } from './pages/WorkPage';

function NavItem({ to, icon, label, end }: { to: string; icon: string; label: string; end?: boolean }) {
  return (
    <NavLink to={to} end={end} title={label} className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}>
      <span className="nav-icon material-symbols-outlined" aria-hidden="true">{icon}</span>
      <span className="nav-label">{label}</span>
    </NavLink>
  );
}

function NavSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="nav-group is-open">
      <div className="nav-group-label"><span className="nav-group-text">{title}</span></div>
      {children}
    </div>
  );
}

function NoProject() {
  return (
    <>
      <PageHeader title="Welcome to Viber" />
      <EmptyState icon="folder_open" title="No project yet">
        Create one with the API (POST /v1/projects) and it will appear here.
      </EmptyState>
    </>
  );
}

function Shell() {
  const [collapsed, setCollapsed] = useState(false);
  const { project, projects } = useProject();
  const name = projects.find((entry) => entry.key === project)?.name ?? 'Viber';
  return (
    <div className={collapsed ? 'app-shell sidebar-collapsed' : 'app-shell'}>
      <nav className="sidebar" aria-label="Main">
        <div className="sidebar-header">
          <button type="button" className="burger-btn" aria-label="Toggle navigation" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
            <span className="material-symbols-outlined" aria-hidden="true">menu</span>
          </button>
          <h2 title={name}>Viber</h2>
        </div>
        <div className="sidebar-links">
          <div className="nav-home">
            <NavItem to="/" end icon="home" label="Overview" />
          </div>
          <NavSection title="Sessions">
            <NavItem to="/sessions" icon="terminal" label="Sessions" />
            <NavItem to="/review" icon="fact_check" label="Review queue" />
          </NavSection>
          <NavSection title="Project">
            <NavItem to="/work" icon="task_alt" label="Work" />
            <NavItem to="/map" icon="hub" label="Map" />
            <NavItem to="/memory" icon="psychology" label="Memory" />
            <NavItem to="/prompts" icon="chat" label="Prompts" />
          </NavSection>
          <NavSection title="Viber">
            <NavItem to="/system" icon="settings" label="System" />
          </NavSection>
        </div>
        <div className="sidebar-foot">
          <NavItem to="/projects" icon="folder_open" label={collapsed ? 'Projects' : `Project: ${project ?? 'none'}`} />
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/system" element={<SystemPage />} />
          {project === null ? (
            <Route path="*" element={<NoProject />} />
          ) : (
            <>
              <Route path="/" element={<Overview />} />
              <Route path="/sessions" element={<SessionsPage />} />
              <Route path="/review" element={<ReviewPage />} />
              <Route path="/work" element={<WorkPage />} />
              <Route path="/map" element={<MapPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/prompts" element={<PromptsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </>
          )}
        </Routes>
      </main>
    </div>
  );
}

function TokenGate() {
  const [value, setValue] = useState('');
  return (
    <div className="main" style={{ maxWidth: '40rem', margin: '10vh auto' }}>
      <PageHeader title="Viber" description="This Viber needs an access token." />
      <Card title="Access token" description="The same value as VIBER_TOKEN on the server. It is kept in this browser only.">
        <form className="viber-token" onSubmit={(event) => { event.preventDefault(); setToken(value.trim()); window.location.reload(); }}>
          <input type="password" value={value} autoFocus aria-label="Access token" onChange={(event) => setValue(event.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={!value.trim()}>Connect</button>
        </form>
        {getToken() && <Notice tone="error">The saved token was refused.</Notice>}
      </Card>
    </div>
  );
}

export function App() {
  const [needsToken, setNeedsToken] = useState(false);
  useEffect(() => onUnauthorized(() => setNeedsToken(true)), []);
  if (needsToken) return <TokenGate />;
  return (
    <HashRouter>
      <ProjectProvider>
        <Shell />
      </ProjectProvider>
    </HashRouter>
  );
}
