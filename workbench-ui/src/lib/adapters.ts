import { mockWorkbenchData } from "./mockData";
import type { PillarHealth, PillarStatus, WorkbenchData } from "./types";

const env = import.meta.env;

interface EndpointConfig {
  name: PillarHealth["id"];
  label: string;
  url?: string;
  key?: string;
}

const endpointConfigs: EndpointConfig[] = [
  { name: "pillar1", label: "Pillar 1 · AFA Engine", url: env.VITE_PILLAR1_URL, key: env.VITE_PILLAR1_KEY },
  { name: "pillar2", label: "Pillar 2 · Email Intelligence", url: env.VITE_PILLAR2_URL, key: env.VITE_PILLAR2_KEY },
  { name: "pillar3", label: "Pillar 3 · Document AI", url: env.VITE_PILLAR3_URL, key: env.VITE_PILLAR3_KEY },
  { name: "pillar4", label: "Pillar 4 · Expense Hub", url: env.VITE_PILLAR4_URL, key: env.VITE_PILLAR4_KEY }
];

interface Pillar1IntakeResponse {
  success: boolean;
  count: number;
  invoices: Array<Record<string, unknown>>;
}

interface Pillar3UpdatesResponse {
  success: boolean;
  count: number;
  database_updates: Array<{
    update_id?: string;
    target_table?: string;
    source_summary?: {
      source?: string;
    };
    apply_state?: string;
    status?: string;
    reviewed_by?: string;
    proposed_at?: string;
  }>;
}

interface Pillar3DocumentsResponse {
  success: boolean;
  count: number;
  documents: Array<{
    document_id?: string;
    source?: string;
    status?: string;
    original_filename?: string;
    filing?: {
      requires_review?: boolean;
    };
  }>;
}

function classifyStatus(payload: unknown): PillarStatus {
  if (!payload || typeof payload !== "object") {
    return "offline";
  }

  const status = Reflect.get(payload, "status");
  return status === "healthy" ? "healthy" : "degraded";
}

function buildApiUrl(endpoint: EndpointConfig | undefined, route: string): string | undefined {
  if (!endpoint?.url || !endpoint.key) {
    return undefined;
  }

  const baseUrl = endpoint.url.replace(/\/+$/, "");
  return `${baseUrl}/${route.replace(/^\/+/, "")}?code=${encodeURIComponent(endpoint.key)}`;
}

async function fetchHealth(endpoint: EndpointConfig): Promise<PillarHealth | null> {
  const requestUrl = buildApiUrl(endpoint, "api/health");
  if (!requestUrl) {
    return null;
  }

  const startedAt = performance.now();

  try {
    const response = await fetch(requestUrl);
    const latencyMs = Math.round(performance.now() - startedAt);

    if (!response.ok) {
      return {
        id: endpoint.name,
        name: endpoint.label,
        status: "offline",
        latencyMs,
        summary: `HTTP ${response.status} while reading health`,
        href: requestUrl
      };
    }

    const payload = (await response.json()) as Record<string, unknown>;
    const readiness = payload.readiness;
    const summary =
      readiness && typeof readiness === "object"
        ? Object.entries(readiness as Record<string, unknown>)
            .filter(([, value]) => value === true)
            .slice(0, 2)
            .map(([key]) => key.replaceAll("_", " "))
            .join(" · ") || "Health endpoint reachable"
        : "Health endpoint reachable";

    return {
      id: endpoint.name,
      name: endpoint.label,
      status: classifyStatus(payload),
      latencyMs,
      summary,
      href: requestUrl
    };
  } catch {
    return {
      id: endpoint.name,
      name: endpoint.label,
      status: "offline",
      latencyMs: Math.round(performance.now() - startedAt),
      summary: "Health endpoint unreachable from browser",
      href: requestUrl
    };
  }
}

async function fetchJson<T>(endpoint: EndpointConfig | undefined, route: string): Promise<T | null> {
  const requestUrl = buildApiUrl(endpoint, route);
  if (!requestUrl) {
    return null;
  }

  try {
    const response = await fetch(requestUrl);
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function loadWorkbenchData(): Promise<WorkbenchData> {
  const livePillars = await Promise.all(endpointConfigs.map(fetchHealth));
  const pillar1 = endpointConfigs.find((entry) => entry.name === "pillar1");
  const pillar2 = endpointConfigs.find((entry) => entry.name === "pillar2");
  const pillar3 = endpointConfigs.find((entry) => entry.name === "pillar3");
  const pillar4 = endpointConfigs.find((entry) => entry.name === "pillar4");

  const pillar1HealthUrl = buildApiUrl(pillar1, "api/health");
  const pillar2HealthUrl = buildApiUrl(pillar2, "api/health");
  const pillar3HealthUrl = buildApiUrl(pillar3, "api/health");
  const pillar4HealthUrl = buildApiUrl(pillar4, "api/health");
  const pillar1IntakeUrl = buildApiUrl(pillar1, "api/invoices/intake");
  const pillar3UpdatesUrl = buildApiUrl(pillar3, "api/database-updates");
  const pillar3DocumentsUrl = buildApiUrl(pillar3, "api/documents");

  const [pillar1Intake, pillar3Updates, pillar3Documents] = await Promise.all([
    fetchJson<Pillar1IntakeResponse>(pillar1, "api/invoices/intake"),
    fetchJson<Pillar3UpdatesResponse>(pillar3, "api/database-updates"),
    fetchJson<Pillar3DocumentsResponse>(pillar3, "api/documents")
  ]);

  const pillars = mockWorkbenchData.pillars.map((pillar) => {
    const live = livePillars.find((entry) => entry?.id === pillar.id);
    return live ?? pillar;
  });

  const intakeCount = pillar1Intake?.count ?? null;
  const pendingApprovals =
    pillar3Updates?.database_updates.filter((update) => update.status === "pending_approval").length ?? null;
  const shadowApplied =
    pillar3Updates?.database_updates.filter((update) => update.apply_state === "shadow_applied").length ?? null;
  const documentCount = pillar3Documents?.count ?? null;
  const documentPending =
    pillar3Documents?.documents.filter((document) => document.status === "pending").length ?? null;
  const documentReview =
    pillar3Documents?.documents.filter((document) => document.filing?.requires_review === true).length ?? null;
  const documentClassified =
    pillar3Documents?.documents.filter((document) => document.status === "classified").length ?? null;

  const sidebar = mockWorkbenchData.sidebar.map((item) => ({ ...item }));
  const details = structuredClone(mockWorkbenchData.details);
  const approvals = mockWorkbenchData.approvals.map((item) => ({ ...item }));

  details.documents.primaryActionHref = pillar3Documents ? pillar3DocumentsUrl : pillar3HealthUrl;
  details.documents.secondaryActionHref = pillar3Updates ? pillar3UpdatesUrl : undefined;
  details.approvals.primaryActionHref = pillar3Updates ? pillar3UpdatesUrl : undefined;
  details.approvals.secondaryActionHref = pillar3Documents ? pillar3DocumentsUrl : undefined;
  details.ap.primaryActionHref = pillar1Intake ? pillar1IntakeUrl : pillar1HealthUrl;
  details.ap.secondaryActionHref = pillar1HealthUrl;
  details.inbox.primaryActionHref = pillar2HealthUrl ?? pillar3UpdatesUrl ?? pillar3DocumentsUrl;
  details.inbox.secondaryActionHref = pillar3Documents ? pillar3DocumentsUrl : pillar2HealthUrl;

  if (!pillar3Documents) {
    details.documents.primaryAction = "Open Document AI health";
    details.documents.primaryActionWorkspaceId = undefined;
  }

  if (!pillar3Updates) {
    details.documents.secondaryAction = "Open approvals lane";
    details.documents.secondaryActionWorkspaceId = "approvals";
  }

  if (!pillar2HealthUrl) {
    details.inbox.primaryAction = pillar3Updates ? "Open approval queue" : "Open documents lane";
    details.inbox.primaryActionWorkspaceId = undefined;
  }

  if (!pillar3Documents) {
    details.inbox.secondaryAction = pillar2HealthUrl ? "Open email service health" : "Open approvals lane";
    details.inbox.secondaryActionWorkspaceId = pillar2HealthUrl ? undefined : "approvals";
  }

  if (intakeCount !== null) {
    sidebar.find((item) => item.id === "ap")!.queueCount = intakeCount;
    details.ap.queueValue = `${intakeCount} queued invoices`;
    details.ap.primaryAction = "Open intake queue";
    details.ap.secondaryAction = "Open AP service health";
    details.ap.sections[0].items[2] = {
      label: "Expense claims queued",
      value: String(intakeCount),
      meta: "Live Pillar 1 intake queue",
      tone: intakeCount > 0 ? "active" : "stable"
    };
  }

  if (!pillar1Intake) {
    details.ap.primaryAction = "Open AP service health";
    details.ap.primaryActionWorkspaceId = undefined;
    details.ap.secondaryAction = "Inspect expense intake";
    details.ap.secondaryActionWorkspaceId = "ap";
  }

  if (pendingApprovals !== null && shadowApplied !== null) {
    sidebar.find((item) => item.id === "approvals")!.queueCount = pendingApprovals;
    details.approvals.queueValue = `${pendingApprovals} decisions`;
    details.approvals.primaryAction = "Open approval queue";
    details.approvals.secondaryAction = "Open filing queue";
    details.approvals.sections[0].items[0] = {
      label: "Pending approval",
      value: String(pendingApprovals),
      meta: "Live Pillar 3 approval queue",
      tone: pendingApprovals > 0 ? "attention" : "stable"
    };
    details.approvals.sections[0].items[1] = {
      label: "Shadow applied",
      value: String(shadowApplied),
      meta: "No-write apply confirmations",
      tone: shadowApplied > 0 ? "stable" : "attention"
    };
    approvals.splice(
      0,
      approvals.length,
      ...pillar3Updates!.database_updates.slice(0, 3).map((update, index) => ({
        id: update.update_id ?? `DB-LIVE-${index + 1}`,
        type: update.target_table ?? "Database update",
        source: update.source_summary?.source ?? "Pillar 3",
        status: update.status ?? "unknown",
        owner: update.reviewed_by || "Pending owner",
        updatedAt: update.proposed_at ? new Date(update.proposed_at).toLocaleString() : "Recently updated",
        href: pillar3Updates ? pillar3UpdatesUrl : undefined
      }))
    );
  }

  if (documentCount !== null && documentPending !== null && documentReview !== null && documentClassified !== null) {
    sidebar.find((item) => item.id === "documents")!.queueCount = documentCount;
    details.documents.queueValue = `${documentCount} recent documents`;
    details.documents.sections[0].items[0] = {
      label: "Ready to file",
      value: String(documentClassified),
      meta: "Live classified queue",
      tone: documentClassified > 0 ? "active" : "stable"
    };
    details.documents.sections[0].items[1] = {
      label: "Needs review",
      value: String(documentReview),
      meta: "Filing requires human confirmation",
      tone: documentReview > 0 ? "attention" : "stable"
    };
    details.documents.sections[0].items[2] = {
      label: "Still pending",
      value: String(documentPending),
      meta: "Not yet classified or queued",
      tone: documentPending > 0 ? "critical" : "stable"
    };
  }

  const heroStats = mockWorkbenchData.heroStats.map((stat) => ({ ...stat }));
  if (intakeCount !== null) {
    heroStats[0] = {
      label: "AP intake queue",
      value: String(intakeCount),
      tone: intakeCount > 0 ? "attention" : "stable",
      workspaceId: "ap",
      href: pillar1Intake ? pillar1IntakeUrl : undefined
    };
  }
  if (documentCount !== null) {
    heroStats[1] = {
      label: "Documents staged",
      value: String(documentCount),
      tone: documentCount > 0 ? "active" : "stable",
      workspaceId: "documents",
      href: pillar3Documents ? pillar3DocumentsUrl : undefined
    };
  }
  if (pendingApprovals !== null) {
    heroStats[2] = {
      label: "Pending approvals",
      value: String(pendingApprovals),
      tone: pendingApprovals > 0 ? "critical" : "stable",
      workspaceId: "approvals",
      href: pillar3Updates ? pillar3UpdatesUrl : undefined
    };
  }
  heroStats[3] = {
    ...heroStats[3],
    workspaceId: "ap",
    href: pillar4HealthUrl ?? pillar3HealthUrl ?? pillar1HealthUrl
  };

  return {
    ...mockWorkbenchData,
    generatedAt: livePillars.some(Boolean)
      ? "Updated from live pillar health where available"
      : mockWorkbenchData.generatedAt,
    heroStats,
    sidebar,
    details,
    pillars,
    approvals
  };
}
