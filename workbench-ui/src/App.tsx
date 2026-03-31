import { useEffect, useState } from "react";
import { loadWorkbenchData } from "./lib/adapters";
import type {
  ApprovalRecord,
  PillarHealth,
  QueueTone,
  SidebarItem,
  TimelineEntry,
  WorkbenchData,
  WorkspaceId
} from "./lib/types";

const toneLabels: Record<QueueTone, string> = {
  stable: "Stable",
  active: "Active",
  attention: "Attention",
  critical: "Critical"
};

function App() {
  const [data, setData] = useState<WorkbenchData | null>(null);
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>("ap");

  useEffect(() => {
    let cancelled = false;

    loadWorkbenchData().then((next) => {
      if (!cancelled) {
        setData(next);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!data) {
    return (
      <main className="app-shell loading-shell">
        <div className="loading-mark">Peak10</div>
        <p className="loading-copy">Building the workbench surface...</p>
      </main>
    );
  }

  const detail = data.details[activeWorkspace];

  return (
    <main className="app-shell">
      <div className="app-backdrop" />
      <aside className="side-rail">
        <div className="brand-block">
          <span className="brand-chip">Peak 10 Energy</span>
          <h1>Workbench</h1>
          <p>
            Operate email, documents, AP, and approvals in one governed surface.
          </p>
        </div>

        <nav className="workspace-nav" aria-label="Workbench sections">
          {data.sidebar.map((item) => (
            <WorkspaceButton
              key={item.id}
              item={item}
              active={item.id === activeWorkspace}
              onClick={() => setActiveWorkspace(item.id)}
            />
          ))}
        </nav>

        <div className="side-rail-footer">
          <span className="footer-label">Workbench state</span>
          <strong>{data.generatedAt}</strong>
          <p>Mock-first data model with live health overlays where available.</p>
        </div>
      </aside>

      <section className="main-canvas">
        <header className="hero-panel">
          <div className="hero-copy">
            <span className="eyebrow">Operational command layer</span>
            <h2>{data.headline}</h2>
            <p>{data.subheadline}</p>
          </div>
          <div className="hero-stats">
            {data.heroStats.map((stat) => (
              <div className={`hero-stat tone-${stat.tone}`} key={stat.label}>
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </div>
            ))}
          </div>
        </header>

        <section className="workspace-stage">
          <div className="workspace-header">
            <div>
              <span className="eyebrow">Current lane</span>
              <h3>{detail.headline}</h3>
            </div>
            <div className={`queue-chip tone-${detail.queueTone}`}>
              <span>{detail.queueLabel}</span>
              <strong>{detail.queueValue}</strong>
            </div>
          </div>

          <p className="workspace-narrative">{detail.narrative}</p>

          <div className="action-row">
            <button className="primary-action">{detail.primaryAction}</button>
            <button className="secondary-action">{detail.secondaryAction}</button>
          </div>

          <div className="section-grid">
            {detail.sections.map((section) => (
              <article className="stage-section" key={section.title}>
                <span className="eyebrow">{section.eyebrow}</span>
                <h4>{section.title}</h4>
                <p>{section.description}</p>
                <div className="metric-list">
                  {section.items.map((item) => (
                    <div className="metric-row" key={`${section.title}-${item.label}`}>
                      <div>
                        <span className="metric-label">{item.label}</span>
                        <small>{item.meta}</small>
                      </div>
                      <div className={`metric-value tone-${item.tone}`}>
                        <strong>{item.value}</strong>
                        <span>{toneLabels[item.tone]}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="signal-band">
          <div className="signal-copy">
            <span className="eyebrow">Flow visibility</span>
            <h3>Cross-pillar traffic should be obvious before it becomes risky.</h3>
          </div>
          <div className="timeline-list">
            {data.timeline.map((entry) => (
              <TimelineCard key={`${entry.time}-${entry.title}`} entry={entry} />
            ))}
          </div>
        </section>
      </section>

      <aside className="inspector">
        <section className="inspector-section">
          <div className="section-title">
            <span className="eyebrow">Live pillars</span>
            <h3>Service state</h3>
          </div>
          <div className="pillar-list">
            {data.pillars.map((pillar) => (
              <PillarRow key={pillar.id} pillar={pillar} />
            ))}
          </div>
        </section>

        <section className="inspector-section">
          <div className="section-title">
            <span className="eyebrow">Human decisions</span>
            <h3>Approval queue</h3>
          </div>
          <div className="approval-list">
            {data.approvals.map((approval) => (
              <ApprovalRow key={approval.id} approval={approval} />
            ))}
          </div>
        </section>
      </aside>
    </main>
  );
}

function WorkspaceButton({
  item,
  active,
  onClick
}: {
  item: SidebarItem;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`workspace-button ${active ? "is-active" : ""}`}
      onClick={onClick}
    >
      <div className="workspace-button-top">
        <span>{item.shortLabel}</span>
        <strong>{item.queueCount}</strong>
      </div>
      <h3>{item.label}</h3>
      <p>{item.summary}</p>
    </button>
  );
}

function PillarRow({ pillar }: { pillar: PillarHealth }) {
  return (
    <article className={`pillar-row status-${pillar.status}`}>
      <div>
        <h4>{pillar.name}</h4>
        <p>{pillar.summary}</p>
      </div>
      <div className="pillar-meta">
        <strong>{pillar.latencyMs}ms</strong>
        <span>{pillar.status}</span>
      </div>
    </article>
  );
}

function ApprovalRow({ approval }: { approval: ApprovalRecord }) {
  return (
    <article className="approval-row">
      <div>
        <span className="approval-id">{approval.id}</span>
        <h4>{approval.type}</h4>
        <p>{approval.source}</p>
      </div>
      <div className="approval-meta">
        <strong>{approval.status}</strong>
        <span>{approval.owner}</span>
        <small>{approval.updatedAt}</small>
      </div>
    </article>
  );
}

function TimelineCard({ entry }: { entry: TimelineEntry }) {
  return (
    <article className={`timeline-card tone-${entry.tone}`}>
      <span className="timeline-time">{entry.time}</span>
      <h4>{entry.title}</h4>
      <p>{entry.detail}</p>
    </article>
  );
}

export default App;
