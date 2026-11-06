import {
  Brain, Check, CircleAlert, ClipboardList, ExternalLink, FileText, Flag, Hand, Inbox, Lock, Package, Play,
  RotateCcw, Send, ShieldAlert, Sparkles, ThumbsDown, ThumbsUp, Wrench, X, type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { agentColor, api, STATUS_LABEL, usd, type AgentCard, type Artifact, type Audit, type HiveEvent,
  type MissionDetail, type Task } from "../api";

export function Face({ role, name, size }: { role: string; name: string; size?: "lg" }) {
  const human = role === "human" || role.startsWith("user:");
  return (
    <span className={`face ${human ? "human" : ""} ${size ?? ""}`} style={{ ["--agent" as string]: agentColor(role) }}
      aria-hidden="true">{name[0]?.toUpperCase()}</span>
  );
}

export function AgentChip({ role, agents }: { role: string; agents: Record<string, AgentCard> }) {
  const human = role.startsWith("user:");
  const a = agents[role];
  const name = human ? role.slice(5) : role === "system" ? "Plataforma" : a?.name ?? role;
  return (
    <span className="agent-chip" style={{ ["--agent" as string]: human ? "var(--honey)" : agentColor(role) }}
      title={a ? `${a.name}, ${a.title}` : name}>
      <Face role={human ? "human" : role} name={name} />{name}
    </span>
  );
}

const EVENT_ICON: Record<string, [LucideIcon, string?]> = {
  "mission.received": [Inbox], "orchestrator.interpreting": [Brain], "mission.brief": [FileText],
  "orchestrator.planning": [ClipboardList], "plan.created": [ClipboardList], "plan.dor_validated": [Check, "good"],
  "plan.corrected": [Wrench, "attn"], "gate.awaiting": [Hand, "attn"], "gate.approved": [ThumbsUp, "good"],
  "gate.rejected": [ThumbsDown, "bad"], "task.delegated": [Send], "task.started": [Play], "llm.call": [Sparkles],
  "artifact.created": [Package], "task.completed": [Check, "good"], "task.rework": [RotateCcw, "attn"],
  "agent.self_review": [RotateCcw], "task.failed": [ShieldAlert, "bad"], "task.dor_failed": [ShieldAlert, "bad"],
  "task.rework_exhausted": [ShieldAlert, "bad"], "mission.retried": [RotateCcw, "attn"], "mission.completed": [Flag, "good"], "mission.failed": [CircleAlert, "bad"],
};

const EVENT_LABEL: Record<string, string> = {
  "llm.call": "chamada de modelo", "task.delegated": "delegação", "task.started": "início", "task.completed": "entrega",
  "artifact.created": "artefato", "task.rework": "retrabalho", "gate.awaiting": "aguardando decisão",
  "gate.approved": "aprovação", "gate.rejected": "rejeição", "mission.brief": "briefing", "plan.created": "plano",
  "plan.dor_validated": "DoR validado", "agent.self_review": "autorrevisão", "mission.retried": "nova tentativa",
};

export function Timeline({ events, agents, onSelectTask }: {
  events: HiveEvent[]; agents: Record<string, AgentCard>; onSelectTask: (id: string) => void;
}) {
  const [actor, setActor] = useState("all");
  const [hideLLM, setHideLLM] = useState(true);
  const actors = useMemo(() => [...new Set(events.map((e) => e.actor))], [events]);
  const shown = events.filter((e) => (actor === "all" || e.actor === actor) && !(hideLLM && e.type === "llm.call"));
  return (
    <div>
      <div className="toolbar">
        <select value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Filtrar por participante">
          <option value="all">Todos os participantes</option>
          {actors.map((a) => <option key={a} value={a}>{agents[a]?.name ?? a.replace("user:", "")}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={hideLLM} onChange={(e) => setHideLLM(e.target.checked)} />
          Esconder chamadas de modelo</label>
        <span className="faint small">{shown.length} de {events.length} eventos, do mais recente ao mais antigo</span>
      </div>
      <ol className="timeline">
        {[...shown].reverse().map((e) => {
          const [Icon, tone] = EVENT_ICON[e.type] ?? [FileText];
          return (
            <li key={e.id} className={`ev ${tone ?? ""} ${e.type === "llm.call" ? "llm" : ""}`}>
              <time dateTime={e.ts}>{new Date(e.ts).toLocaleTimeString("pt-BR")}</time>
              <span className="ev-icon"><Icon className="icon" aria-hidden="true" /></span>
              <div>
                <div className="ev-line"><AgentChip role={e.actor} agents={agents} />
                  <span className="faint small">{EVENT_LABEL[e.type] ?? e.type}</span></div>
                <div className="ev-msg">{e.message}</div>
                <div className="ev-meta">
                  {e.task_id && <button className="link" onClick={() => onSelectTask(e.task_id!)}>Abrir tarefa</button>}
                  <span className="hash" title={`Hash anterior ${e.prev_hash}`}>evento {e.seq}, hash {e.hash.slice(0, 12)}</span>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function TaskDrawer({ task, mission, agents, events, onOpenArtifact, onClose }: {
  task: Task; mission: MissionDetail; agents: Record<string, AgentCard>; events: HiveEvent[];
  onOpenArtifact: (a: Artifact) => void; onClose: () => void;
}) {
  const a = agents[task.agent];
  const arts = mission.artifacts.filter((x) => x.task_id === task.id);
  const calls = events.filter((e) => e.task_id === task.id && e.type === "llm.call");
  const delegated = [...events].reverse().find((e) => e.task_id === task.id && e.type === "task.delegated");
  const playbooks: string[] = delegated?.data.playbooks ?? [];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="drawer" style={{ ["--agent" as string]: agentColor(task.agent) }} aria-label={`Tarefa: ${task.title}`}>
      <div className="drawer-head">
        <Face role={task.agent} name={a?.name ?? task.agent} size="lg" />
        <div><h3>{task.title}</h3><div className="who">{a?.name}, {a?.title}</div></div>
        <button className="icon-btn" onClick={onClose} aria-label="Fechar"><X className="icon" /></button>
      </div>
      <dl className="kv">
        <dt>Situação</dt><dd>{STATUS_LABEL[task.status]}{task.attempt > 1 && `, ${task.attempt}ª tentativa`}</dd>
        <dt>Custo</dt><dd className="num">{usd(task.cost_usd)}</dd>
        <dt>Tokens</dt><dd className="num">{task.tokens_in.toLocaleString("pt-BR")} lidos, {task.tokens_out.toLocaleString("pt-BR")} escritos</dd>
        <dt>Modelo</dt><dd>{task.models.join(", ") || "Nenhum: verificação determinística"}</dd>
        {playbooks.length > 0 && <><dt>Playbooks</dt><dd>{playbooks.join(", ")}</dd></>}
      </dl>

      <h4>História</h4>
      <p className="story">{task.story.user_story}</p>
      <div className="io">
        <div><p>Precisa receber</p><ul className="files">{task.story.inputs_required.map((i) => <li key={i}>{i}</li>)}
          {!task.story.inputs_required.length && <li>nada</li>}</ul></div>
        <div><p>Deve entregar</p><ul className="files">{task.story.outputs_expected.map((i) => <li key={i}>{i}</li>)}</ul></div>
      </div>
      <h4>Critérios de aceite</h4>
      <ul className="criteria">{task.story.acceptance_criteria.map((c) => <li key={c}>{c}</li>)}</ul>

      {task.feedback && <><h4>Apontamentos que voltaram para correção</h4><pre className="feedback">{task.feedback}</pre></>}

      {task.result && <>
        <h4>Relatório do agente</h4>
        <p>{task.result.summary}</p>
        <h4>Evidências</h4>
        <ul className="evidence">
          {task.result.evidence.map((e, i) => (
            <li key={i} className={e.passed === false ? "fail" : ""}>
              {e.passed === true ? <Check className="icon pass-icon" aria-label="Aprovado" />
                : e.passed === false ? <X className="icon fail-icon" aria-label="Reprovado" />
                : <FileText className="icon faint" aria-hidden="true" />}
              <div><b>{e.title}</b>{e.detail && <div className="detail">
                {e.kind === "link" ? <a href={e.detail} target="_blank" rel="noreferrer">{e.detail}</a> : e.detail}</div>}</div>
            </li>
          ))}
        </ul>
      </>}

      <h4>Artefatos</h4>
      <ul className="artifacts">
        {arts.map((x) => (
          <li key={x.id}><button className="link" onClick={() => onOpenArtifact(x)}>{x.name}, versão {x.version}</button>
            <span className="hash faint">{x.sha256.slice(0, 10)}</span></li>
        ))}
        {!arts.length && <li className="faint">Nenhum até agora</li>}
      </ul>

      {calls.length > 0 && <><h4>Chamadas de modelo</h4>
        <ul className="artifacts small">{calls.map((c) => <li key={c.id} className="muted">{c.message}</li>)}</ul></>}
    </aside>
  );
}

export function Delivery({ mission }: { mission: MissionDetail }) {
  const [images, setImages] = useState<{ file: string; alt: string; section_id: string; source: string }[]>([]);
  const manifest = [...mission.artifacts].reverse().find((a) => a.name === "images.json");
  const built = mission.artifacts.some((a) => a.name === "index.html");
  useEffect(() => {
    if (!manifest) return;
    api.artifact(manifest.id).then((body) => setImages(JSON.parse(body)));
  }, [manifest?.id]);
  const src = mission.deployment_url ?? (built ? api.previewUrl(mission.id) : null);
  return (
    <div className="delivery">
      <div className="browser">
        <div className="browser-bar">
          <Lock className="icon" aria-hidden="true" />
          <span className="url">{mission.deployment_url ?? (built ? "Prévia do build, ainda não publicado" : "Aguardando o desenvolvedor")}</span>
          {src && <a className="btn quiet" href={src} target="_blank" rel="noreferrer"><ExternalLink className="icon" />Abrir</a>}
        </div>
        {src ? <iframe title="Prévia do site" src={src} sandbox="" loading="lazy" />
          : <div className="graph-empty">A prévia aparece quando o desenvolvedor entregar a primeira versão.</div>}
      </div>
      <div>
        <h4 style={{ marginTop: 0 }}>Ilustrações</h4>
        {images.length ? (
          <div className="gallery">
            {images.map((im) => (
              <figure key={im.file}>
                <img src={api.previewUrl(mission.id, im.file)} alt={im.alt} loading="lazy" />
                <figcaption><span>{im.section_id === "hero" ? "Destaque" : im.section_id}</span>
                  <span className={`source ${im.source}`}>{{ llm: "SVG do modelo", comfyui: "gerada (SDXL)" }[im.source] ?? "plano B"}</span></figcaption>
              </figure>
            ))}
          </div>
        ) : <p className="muted">Sem ilustrações nesta missão ainda.</p>}
      </div>
    </div>
  );
}

export function AuditPanel({ missionId, agents, version }: { missionId: string; agents: Record<string, AgentCard>; version: number }) {
  const [audit, setAudit] = useState<Audit | null>(null);
  useEffect(() => { api.audit(missionId).then(setAudit); }, [missionId, version]);
  if (!audit) return <p className="muted">Carregando auditoria…</p>;
  return (
    <div>
      <div className={`chain ${audit.chain.valid ? "ok" : "bad"}`}>
        {audit.chain.valid ? <Check className="icon" /> : <ShieldAlert className="icon" />}
        {audit.chain.valid
          ? `Trilha íntegra: ${audit.chain.events} eventos encadeados por SHA-256.`
          : `Trilha adulterada: a cadeia quebra no evento ${audit.chain.broken_at}.`}
        {audit.chain.head && <span className="hash">último hash {audit.chain.head.slice(0, 16)}</span>}
      </div>
      <h4>Quem fez o quê</h4>
      <div className="table-wrap"><table>
        <thead><tr><th>Etapa</th><th>Responsável</th><th className="n">Tentativas</th><th>Modelo</th><th>Entregou</th><th className="n">Custo</th></tr></thead>
        <tbody>{audit.responsibility.map((r) => (
          <tr key={r.task}><td>{r.title}</td><td><AgentChip role={r.agent} agents={agents} /></td><td className="n">{r.attempts}</td>
            <td className="small">{r.models.join(", ") || "sem modelo"}</td><td className="small">{r.artifacts.join(", ")}</td>
            <td className="n">{usd(r.cost_usd)}</td></tr>))}</tbody>
      </table></div>
      <h4>Decisões humanas</h4>
      {Object.keys(audit.approvals).length ? (
        <ul>{Object.entries(audit.approvals).map(([g, a]) => (
          <li key={g}>{g === "plan" ? "Plano" : "Publicação"} {a.approved ? "aprovado" : "rejeitado"} por <b>{a.by}</b> em{" "}
            {new Date(a.at).toLocaleString("pt-BR")}{a.comment && `, com o comentário “${a.comment}”`}.</li>))}</ul>
      ) : <p className="muted">Nenhuma decisão registrada ainda.</p>}
    </div>
  );
}

export function CostPanel({ missionId, agents, version }: { missionId: string; agents: Record<string, AgentCard>; version: number }) {
  const [audit, setAudit] = useState<Audit | null>(null);
  useEffect(() => { api.audit(missionId).then(setAudit); }, [missionId, version]);
  if (!audit) return null;
  const c = audit.costs;
  const max = Math.max(...c.by_agent.map((a) => a.cost_usd), 1e-9);
  return (
    <div>
      <div className="figures">
        <div className="figure"><span>Custo de produção</span><b>{usd(c.total_usd)}</b>
          <em>{c.simulated ? "estimado: modo simulado" : "medido nas chamadas"}</em></div>
        <div className="figure"><span>Orçamento usado</span><b>{c.budget_used_pct}%</b><em>limite de {usd(c.budget_usd, 2)}</em></div>
        <div className="figure"><span>Chamadas de modelo</span><b>{c.calls}</b></div>
        <div className="figure"><span>Tokens</span><b>{(c.input_tokens + c.output_tokens).toLocaleString("pt-BR")}</b>
          <em>{c.input_tokens.toLocaleString("pt-BR")} lidos, {c.output_tokens.toLocaleString("pt-BR")} escritos</em></div>
      </div>
      <h4>Por agente</h4>
      <ul className="bars">{c.by_agent.map((a) => (
        <li key={a.agent} style={{ ["--agent" as string]: agentColor(a.agent) }}>
          <span>{agents[a.agent]?.name ?? a.agent}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(a.cost_usd / max) * 100}%` }} /></span>
          <span className="bar-value">{usd(a.cost_usd)}, {a.share}%</span>
        </li>))}</ul>
      <h4>Por modelo</h4>
      <div className="table-wrap"><table><thead><tr><th>Provedor</th><th>Modelo</th><th className="n">Chamadas</th><th className="n">Custo</th></tr></thead>
        <tbody>{c.by_model.map((m) => <tr key={m.provider + m.model}><td>{m.provider}</td><td>{m.model}</td>
          <td className="n">{m.calls}</td><td className="n">{usd(m.cost_usd)}</td></tr>)}</tbody></table></div>
    </div>
  );
}

export function ArtifactViewer({ artifact, onClose }: { artifact: Artifact; onClose: () => void }) {
  const raster = /\.(webp|png|jpe?g)$/i.test(artifact.name);
  const [body, setBody] = useState("Carregando…");
  useEffect(() => { if (!raster) api.artifact(artifact.id).then(setBody); }, [artifact.id, raster]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={artifact.name} onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <header>
          <div><b>{artifact.name}</b> <span className="faint small">versão {artifact.version}, {artifact.size} bytes, sha256 {artifact.sha256.slice(0, 16)}</span></div>
          <button className="icon-btn" onClick={onClose} aria-label="Fechar"><X className="icon" /></button>
        </header>
        {raster
          ? <div className="svg-preview"><img alt={artifact.name} src={`/api/artifacts/${artifact.id}`} /></div>
          : artifact.name.endsWith(".svg")
          ? <div className="svg-preview"><img alt={artifact.name} src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(body)}`} /></div>
          : <pre className="artifact-body">{body}</pre>}
      </div>
    </div>
  );
}

