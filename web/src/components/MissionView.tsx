import { Calendar, ChartGantt, CircleAlert, Globe, Hand, MessageSquare, RotateCcw, User, Workflow } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, STATUS_LABEL, usd, type AgentCard, type Artifact, type HiveEvent, type MissionDetail } from "../api";
import { fmtDuration, metrics } from "../derive";
import { Gantt } from "./Gantt";
import { MissionGraph } from "./MissionGraph";
import { AgentChip, ArtifactViewer, AuditPanel, CostPanel, Delivery, TaskDrawer, Timeline } from "./Panels";

const TRACK = [
  { key: "received", label: "Pedido" },
  { key: "interpreting", label: "Briefing" },
  { key: "planning", label: "Plano" },
  { key: "awaiting_plan_approval", label: "Sua aprovação" },
  { key: "executing", label: "Produção" },
  { key: "awaiting_deploy_approval", label: "Go-live" },
  { key: "completed", label: "No ar" },
];

function trackIndex(m: MissionDetail): number {
  if (m.status === "executing" && m.approvals.deploy?.approved) return 5;
  if (m.status === "failed" || m.status === "rejected") {
    return m.approvals.deploy ? 5 : m.approvals.plan?.approved ? 4 : m.tasks.length ? 3 : 1;
  }
  return Math.max(0, TRACK.findIndex((j) => j.key === m.status));
}

type Tab = "delivery" | "timeline" | "audit" | "costs" | "artifacts";

export function MissionView({ id, agents }: { id: string; agents: Record<string, AgentCard> }) {
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [events, setEvents] = useState<HiveEvent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"gantt" | "flow" | null>(null);
  const [tab, setTab] = useState<Tab>("delivery");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [budget, setBudget] = useState("");
  const timer = useRef<number>();

  const refresh = useCallback(async () => {
    const [m, ev] = await Promise.all([api.mission(id), api.events(id)]);
    setMission(m);
    setEvents(ev);
    setVersion((v) => v + 1);
  }, [id]);

  useEffect(() => {
    setSelected(null);
    setView(null);
    refresh();
    const es = new EventSource(`/api/stream?mission_id=${id}`);
    es.addEventListener("hive", (msg) => {
      const e: HiveEvent = JSON.parse((msg as MessageEvent).data);
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e]));
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(refresh, 300);
    });
    return () => es.close();
  }, [id, refresh]);

  if (!mission) return <p className="muted">Carregando missão…</p>;

  const gate = mission.status === "awaiting_plan_approval" ? "plan" : mission.status === "awaiting_deploy_approval" ? "deploy" : null;
  const decide = async (approved: boolean) => {
    setBusy(true);
    setError("");
    try { await api.approve(mission.id, gate!, approved); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const retry = async () => {
    setBusy(true);
    setError("");
    try { await api.retry(mission.id, budget ? Number(budget) : undefined); setBudget(""); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const task = mission.tasks.find((t) => t.id === selected);
  const ti = trackIndex(mission);
  const m = metrics(mission, events);
  const crew = [...new Set(["orchestrator", ...mission.tasks.filter((t) => t.attempt > 0).map((t) => t.agent)])];
  const current = view ?? (mission.tasks.some((t) => t.attempt > 0) ? "gantt" : "flow");
  const stuck = mission.status === "failed" || mission.status === "rejected";
  const factTask = mission.tasks.find((t) => t.agent === "fact_checker");
  const factWarnings = ((factTask?.result?.data as { warnings?: string[] } | undefined)?.warnings) ?? [];

  return (
    <div className="mission">
      <a className="back-link" href="#/missions">Voltar às missões</a>
      <header className="mission-head">
        <div>
          <div className="origin">
            <span><MessageSquare className="icon" aria-hidden="true" />via {mission.channel}</span>
            <span><User className="icon" aria-hidden="true" />{mission.requester}</span>
            <span><Calendar className="icon" aria-hidden="true" />{new Date(mission.created_at).toLocaleString("pt-BR")}</span>
          </div>
          <h2>{mission.title}</h2>
          <p className="request">{mission.request}</p>
        </div>
        <div className="facts">
          <div className="fact"><span>Situação</span><b className={`state st-${mission.status}`} style={{ fontSize: "1rem" }}>{STATUS_LABEL[mission.status]}</b></div>
          <div className="fact"><span>Tempo dos agentes</span><b>{fmtDuration(m.agentMs)}</b></div>
          <div className="fact"><span>Custo</span><b title={`Orçamento: ${usd(mission.budget_usd, 2)}`}>{usd(mission.cost_usd, 3)}</b></div>
        </div>
        {mission.deployment_url && (
          <div className="mission-actions">
            <a className="btn" href={mission.deployment_url} target="_blank" rel="noreferrer"><Globe className="icon" />Ver site publicado</a>
          </div>
        )}
      </header>

      <ol className="track" aria-label="Etapas da missão">
        {TRACK.map((j, i) => {
          const cls = mission.status === "completed" || i < ti ? "done" : i === ti ? `current ${gate ? "waiting" : ""} ${stuck ? "failed" : ""}` : "";
          return <li key={j.key} className={cls} aria-current={i === ti ? "step" : undefined}>{j.label}</li>;
        })}
      </ol>

      {gate && (
        <section className="decision" aria-live="polite">
          <Hand aria-hidden="true" />
          <div>
            <h3>{gate === "plan" ? "O plano está pronto para você revisar" : "O site passou no QA. Publicar agora?"}</h3>
            <p>{gate === "plan"
              ? `${mission.tasks.length} tarefas para ${new Set(mission.tasks.map((t) => t.agent)).size} especialistas. Clique em uma tarefa no fluxo para ler a história e os critérios de aceite.`
              : "Veja a prévia na aba Entrega antes de decidir. Sua decisão fica registrada na trilha de auditoria."}</p>
            {gate === "deploy" && factWarnings.length > 0 && (
              <div className="fact-warnings">
                <b>A verificação de fatos deixou {factWarnings.length} afirmação(ões) sem fonte para você decidir:</b>
                <ul>{factWarnings.map((w) => <li key={w}>{w}</li>)}</ul>
                <button className="link" onClick={() => setSelected(factTask!.id)}>Abrir relatório da verificação</button>
              </div>
            )}
            {error && <p className="error"><CircleAlert className="icon" />{error}</p>}
          </div>
          <div className="actions">
            {gate === "deploy" && <button className="btn quiet" onClick={() => setTab("delivery")}>Ver prévia</button>}
            <button className="btn quiet" disabled={busy} onClick={() => decide(false)}>Rejeitar</button>
            <button className="btn decide" disabled={busy} onClick={() => decide(true)}>{gate === "plan" ? "Aprovar plano" : "Publicar site"}</button>
          </div>
        </section>
      )}
      {mission.status === "failed" && (
        <section className="failure" aria-live="polite">
          <CircleAlert aria-hidden="true" />
          <div>
            <h3>A missão parou: {mission.error}</h3>
            <p>Tentar de novo retoma do ponto em que parou. O que já foi entregue e aprovado é mantido, e a nova
              tentativa fica registrada na trilha de auditoria.</p>
            {error && <p className="error"><CircleAlert className="icon" />{error}</p>}
          </div>
          <div className="actions">
            <label className="budget-field">Novo orçamento (US$, opcional)
              <input type="number" min="0" step="0.5" value={budget} onChange={(e) => setBudget(e.target.value)}
                placeholder={mission.budget_usd.toFixed(2)} />
            </label>
            <button className="btn" disabled={busy} onClick={retry}><RotateCcw className="icon" />Tentar de novo</button>
          </div>
        </section>
      )}
      {mission.error && mission.status !== "failed" && <p className="error"><CircleAlert className="icon" />{mission.error}</p>}

      <div className="crew" aria-label="Participantes">
        {crew.map((p) => <AgentChip key={p} role={p} agents={agents} />)}
      </div>

      <section className="stage">
        <div className="stage-head">
          <div className="segmented" role="group" aria-label="Visualização">
            <button aria-pressed={current === "gantt"} onClick={() => setView("gantt")}><ChartGantt className="icon" />Cronograma</button>
            <button aria-pressed={current === "flow"} onClick={() => setView("flow")}><Workflow className="icon" />Fluxo de delegação</button>
          </div>
          {current === "gantt" ? (
            <div className="legend">
              <span><i style={{ background: "var(--info)" }} />trabalho</span>
              <span><i style={{ background: "repeating-linear-gradient(135deg, var(--info) 0 4px, transparent 4px 8px)" }} />retrabalho</span>
              <span><i style={{ border: "2px dashed var(--honey)" }} />esperando você</span>
              <span>riscos verticais: chamadas de modelo</span>
            </div>
          ) : <span className="faint small">Clique em um agente para ver a história e as evidências</span>}
        </div>
        {current === "gantt"
          ? <Gantt mission={mission} events={events} agents={agents} onSelect={setSelected} />
          : <MissionGraph mission={mission} agents={agents} selected={selected} onSelect={setSelected} />}
      </section>

      <div className="tabs" role="tablist">
        {([["delivery", "Entrega"], ["timeline", "Linha do tempo"], ["audit", "Auditoria"], ["costs", "Custos"],
          ["artifacts", "Artefatos"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
            {label}{k === "artifacts" && <span className="count">{mission.artifacts.length}</span>}
            {k === "timeline" && <span className="count">{events.length}</span>}
          </button>
        ))}
      </div>
      <section>
        {tab === "delivery" && <Delivery mission={mission} />}
        {tab === "timeline" && <Timeline events={events} agents={agents} onSelectTask={setSelected} />}
        {tab === "audit" && <AuditPanel missionId={mission.id} agents={agents} version={version} />}
        {tab === "costs" && <CostPanel missionId={mission.id} agents={agents} version={version} />}
        {tab === "artifacts" && (
          <div className="table-wrap" style={{ marginTop: 16 }}><table>
            <thead><tr><th>Artefato</th><th className="n">Versão</th><th>Autor</th><th>SHA-256</th><th className="n">Tamanho</th></tr></thead>
            <tbody>{mission.artifacts.map((a) => (
              <tr key={a.id}><td><button className="link" onClick={() => setArtifact(a)}>{a.name}</button></td><td className="n">{a.version}</td>
                <td><AgentChip role={a.agent} agents={agents} /></td><td className="hash">{a.sha256.slice(0, 16)}</td>
                <td className="n">{a.size.toLocaleString("pt-BR")} B</td></tr>))}
            </tbody></table></div>
        )}
      </section>

      {task && <TaskDrawer task={task} mission={mission} agents={agents} events={events}
        onOpenArtifact={setArtifact} onClose={() => setSelected(null)} />}
      {artifact && <ArtifactViewer artifact={artifact} onClose={() => setArtifact(null)} />}
    </div>
  );
}
