export type WorkspaceId = "inbox" | "documents" | "ap" | "approvals";

export type PillarStatus = "healthy" | "degraded" | "offline";
export type QueueTone = "stable" | "attention" | "critical" | "active";

export interface SidebarItem {
  id: WorkspaceId;
  label: string;
  shortLabel: string;
  queueCount: number;
  tone: QueueTone;
  summary: string;
}

export interface HeroStat {
  label: string;
  value: string;
  tone: QueueTone;
  workspaceId?: WorkspaceId;
  href?: string;
}

export interface TimelineEntry {
  time: string;
  title: string;
  detail: string;
  tone: QueueTone;
}

export interface WorkspaceSection {
  eyebrow: string;
  title: string;
  description: string;
  items: Array<{
    label: string;
    value: string;
    meta: string;
    tone: QueueTone;
  }>;
}

export interface WorkspaceDetail {
  id: WorkspaceId;
  headline: string;
  narrative: string;
  queueLabel: string;
  queueValue: string;
  queueTone: QueueTone;
  primaryAction: string;
  secondaryAction: string;
  primaryActionHref?: string;
  secondaryActionHref?: string;
  primaryActionWorkspaceId?: WorkspaceId;
  secondaryActionWorkspaceId?: WorkspaceId;
  sections: WorkspaceSection[];
}

export interface PillarHealth {
  id: "pillar1" | "pillar2" | "pillar3" | "pillar4";
  name: string;
  status: PillarStatus;
  latencyMs: number;
  summary: string;
  href?: string;
}

export interface ApprovalRecord {
  id: string;
  type: string;
  source: string;
  status: string;
  owner: string;
  updatedAt: string;
  href?: string;
}

export interface WorkbenchData {
  generatedAt: string;
  headline: string;
  subheadline: string;
  heroStats: HeroStat[];
  sidebar: SidebarItem[];
  details: Record<WorkspaceId, WorkspaceDetail>;
  pillars: PillarHealth[];
  approvals: ApprovalRecord[];
  timeline: TimelineEntry[];
}
