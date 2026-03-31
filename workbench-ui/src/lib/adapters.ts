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
    apply_state?: string;
    status?: string;
  }>;
}

function classifyStatus(payload: unknown): PillarStatus {
  if (!payload || typeof payload !== "object") {
    return "offline";
  }

  const status = Reflect.get(payload, "status");
  return status === "healthy" ? "healthy" : "degraded";
}

async function fetchHealth(endpoint: EndpointConfig): Promise<PillarHealth | null> {
  if (!endpoint.url || !endpoint.key) {
    return null;
  }

  const baseUrl = endpoint.url.replace(/\/+$/, "");
  const requestUrl = `${baseUrl}/api/health?code=${encodeURIComponent(endpoint.key)}`;
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
        summary: `HTTP ${response.status} while reading health`
      };
    }

    const payload = (await response.json()) as Record<string, unknown>;
    const readiness = payload.readiness;
    const summary = readiness && typeof readiness === "object"
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
      summary
    };
  } catch {
    return {
      id: endpoint.name,
      name: endpoint.label,
      status: "offline",
      latencyMs: Math.round(performance.now() - startedAt),
      summary: "Health endpoint unreachable from browser"
    };
  }
}

async function fetchJson<T>(endpoint: EndpointConfig, route: string): Promise<T | null> {
  if (!endpoint.url || !endpoint.key) {
    return null;
  }

  const baseUrl = endpoint.url.replace(/\/+$/, "");
  const requestUrl = `${baseUrl}/${route.replace(/^\/+/, "")}?code=${encodeURIComponent(endpoint.key)}`;

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
  const pillar3 = endpointConfigs.find((entry) => entry.name === "pillar3");

  const [pillar1Intake, pillar3Updates] = await Promise.all([
    fetchJson<Pillar1IntakeResponse>(pillar1!, "api/invoices/intake"),
    fetchJson<Pillar3UpdatesResponse>(pillar3!, "api/database-updates")
  ]);

  const pillars = mockWorkbenchData.pillars.map((pillar) => {
    const live = livePillars.find((entry) => entry?.id === pillar.id);
    return live ?? pillar;
  });

  const intakeCount = pillar1Intake?.count ?? null;
  const pendingApprovals = pillar3Updates?.database_updates.filter((update) => update.status === "pending_approval").length ?? null;
  const shadowApplied = pillar3Updates?.database_updates.filter((update) => update.apply_state === "shadow_applied").length ?? null;

  const details = structuredClone(mockWorkbenchData.details);

  if (intakeCount !== null) {
    details.ap.queueValue = `${intakeCount} queued invoices`;
    details.ap.sections[0].items[2] = {
      label: "Expense claims queued",
      value: String(intakeCount),
      meta: "Live Pillar 1 intake queue",
      tone: intakeCount > 0 ? "active" : "stable"
    };
  }

  if (pendingApprovals !== null && shadowApplied !== null) {
    details.approvals.queueValue = `${pendingApprovals} decisions`;
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
  }

  const heroStats = mockWorkbenchData.heroStats.map((stat) => ({ ...stat }));
  if (intakeCount !== null) {
    heroStats[0] = {
      label: "AP intake queue",
      value: String(intakeCount),
      tone: intakeCount > 0 ? "attention" : "stable"
    };
  }
  if (pendingApprovals !== null) {
    heroStats[2] = {
      label: "Pending approvals",
      value: String(pendingApprovals),
      tone: pendingApprovals > 0 ? "critical" : "stable"
    };
  }

  return {
    ...mockWorkbenchData,
    generatedAt: livePillars.some(Boolean)
      ? "Updated from live pillar health where available"
      : mockWorkbenchData.generatedAt,
    heroStats,
    details,
    pillars
  };
}
