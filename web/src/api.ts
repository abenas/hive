export type MissionStatus =
  | "received" | "interpreting" | "planning" | "awaiting_plan_approval" | "executing"
  | "awaiting_deploy_approval" | "completed" | "failed" | "rejected";

export interface Story {
  title: string;
  user_story: string;
  acceptance_criteria: string[];
  inputs_required: string[];
  outputs_expected: string[];
}

export interface Evidence { kind: string; title: string; detail: string; passed: boolean | null }

export interface Task {
  id: string; key: string; agent: string; title: string; story: Story; depends_on: string[];
  status: "pending" | "running" | "done" | "failed"; attempt: number;
  result: { summary: string; evidence: Evidence[]; passed: boolean; data: Record<string, unknown> } | null;
  feedback: string | null; cost_usd: number; tokens_in: number; tokens_out: number; models: string[];
  started_at: string | null; finished_at: string | null;
}

export interface Artifact {
  id: string; task_id: string; agent: string; name: string; version: number; sha256: string; size: number;
  created_at: string;
}

export interface Mission {
  id: string; title: string; request: string; channel: string; requester: string; status: MissionStatus;
  brief: Record<string, unknown> | null; approvals: Record<string, { approved: boolean; by: string; at: string; comment: string }>;
  budget_usd: number; cost_usd: number; deployment_url: string | null; error: string | null;
  created_at: string; updated_at: string;
}

export interface MissionDetail extends Mission { tasks: Task[]; artifacts: Artifact[] }

export interface HiveEvent {
  id: string; seq: number; mission_id: string; task_id: string | null; actor: string; type: string;
  message: string; data: Record<string, any>; ts: string; hash: string; prev_hash: string;
}

export interface Playbook { name: string; title: string; version: string }

export interface AgentCard {
  role: string; name: string; title: string; description: string; skills: string[]; produces: string[]; route: string;
  playbooks?: Playbook[];
}

export interface Audit {
  chain: { valid: boolean; events: number; head?: string; broken_at?: string };
  actors: { actor: string; events: number }[];
  responsibility: { task: string; title: string; agent: string; attempts: number; status: string; models: string[];
    cost_usd: number; artifacts: string[] }[];
  approvals: Mission["approvals"];
  costs: CostBreakdown;
}

export interface CostBreakdown {
  total_usd: number; budget_usd: number; budget_used_pct: number; calls: number; input_tokens: number;
  output_tokens: number; simulated: boolean;
  by_agent: { agent: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; share: number }[];
  by_model: { provider: string; model: string; calls: number; cost_usd: number }[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${r.status}`);
  }
  const type = r.headers.get("content-type") ?? "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  health: () => req<{ provider: string; routing: Record<string, string> }>("/api/health"),
  agents: () => req<AgentCard[]>("/api/agents"),
  missions: () => req<Mission[]>("/api/missions"),
  mission: (id: string) => req<MissionDetail>(`/api/missions/${id}`),
  events: (id: string) => req<HiveEvent[]>(`/api/missions/${id}/events`),
  audit: (id: string) => req<Audit>(`/api/missions/${id}/audit`),
  artifact: (id: string) => req<string>(`/api/artifacts/${id}`),
  previewUrl: (id: string, path = "index.html") => `/api/missions/${id}/preview/${path}`,
  finops: () => req<any>("/api/finops/summary"),
  create: (request: string) =>
    req<Mission>("/api/missions", { method: "POST", body: JSON.stringify({ request, requester: "console" }) }),
  retry: (id: string, budgetUsd?: number) =>
    req(`/api/missions/${id}/retry`, {
      method: "POST", body: JSON.stringify({ actor: "console", ...(budgetUsd ? { budget_usd: budgetUsd } : {}) }),
    }),
  approve: (id: string, gate: "plan" | "deploy", approved: boolean, comment = "") =>
    req(`/api/missions/${id}/approvals`, {
      method: "POST", body: JSON.stringify({ gate, approved, actor: "console", comment }),
    }),
};

export const AGENT_COLORS: Record<string, string> = {
  orchestrator: "#e6e1d3", product_owner: "#7aa2ff", architect: "#4fd1c5", designer: "#ff8fc7",
  copywriter: "#b69cff", fact_checker: "#9fd8cb", illustrator: "#f77bf0", developer: "#6fe0a0", qa: "#ff9d7a", cloud_engineer: "#6cc7ff",
  finops: "#c6e86a",
};

export const STATUS_LABEL: Record<string, string> = {
  received: "Recebida", interpreting: "Interpretando", planning: "Planejando",
  awaiting_plan_approval: "Aguardando aprovação do plano", executing: "Em execução",
  awaiting_deploy_approval: "Aguardando aprovação de deploy", completed: "Concluída", failed: "Falhou",
  rejected: "Rejeitada", pending: "Pendente", running: "Executando", done: "Concluída",
};

export const usd = (v: number, digits = 4) => `US$ ${v.toFixed(digits)}`;

export const HUMAN = { name: "Você", title: "Aprovações" };
export const agentColor = (role: string) => AGENT_COLORS[role] ?? "#8a90a6";
