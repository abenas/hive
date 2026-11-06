import { BookOpen, Coins, Cpu, GitCompareArrows, Hexagon, ListTodo, Moon, Sun, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { agentColor, api, STATUS_LABEL, usd, type AgentCard, type HiveEvent, type Mission, type MissionDetail } from "./api";
import { fmtDuration, metrics, type Metrics } from "./derive";
import { MissionView } from "./components/MissionView";
import { Face } from "./components/Panels";

const EXAMPLES = [
  { label: "Padaria", text: "Crie um site para a empresa Sabor da Vila, do segmento de padaria artesanal, apresente produtos, nossa história e depoimentos. Contato por WhatsApp e Instagram." },
  { label: "Startup", text: "Crie um site para a empresa TechNova, do segmento de tecnologia, apresente soluções, cases, equipe e planos." },
  { label: "Clínica", text: "Crie um site para a empresa Clínica Sorriso Pleno, do segmento de odontologia, apresente tratamentos, estrutura, convênios e depoimentos. Contato por telefone e WhatsApp." },
];

function useHashRoute(): string[] {
  const parse = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

function useTheme(): [string, () => void] {
  const read = () => { try { return localStorage.getItem("hive-theme") ?? ""; } catch { return ""; } };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("hive-theme", theme); } catch { /* sem armazenamento: tema vale só nesta aba */ }
  }, [theme]);
  const dark = theme ? theme === "dark" : !window.matchMedia("(prefers-color-scheme: light)").matches;
  return [dark ? "dark" : "light", () => setTheme(dark ? "light" : "dark")];
}

function Composer({ onCreated }: { onCreated: (id: string) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const m = await api.create(text);
      setText("");
      onCreated(m.id);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="composer">
      <label htmlFor="req">Nova missão</label>
      <textarea id="req" rows={5} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Descreva o que o cliente precisa: empresa, segmento, conteúdos e estilo." />
      <div className="examples" aria-label="Exemplos">
        {EXAMPLES.map((ex) => <button key={ex.label} className="example" onClick={() => setText(ex.text)}>{ex.label}</button>)}
      </div>
      {error && <p className="error">{error}</p>}
      <button className="btn full" disabled={busy || text.trim().length < 10} onClick={submit}>
        {busy ? "Enviando ao orquestrador…" : "Enviar ao orquestrador"}
      </button>
    </div>
  );
}

function useMissions() {
  const [missions, setMissions] = useState<Mission[]>([]);
  useEffect(() => {
    const load = () => api.missions().then(setMissions);
    load();
    const es = new EventSource("/api/stream");
    let t: number | undefined;
    es.addEventListener("hive", () => { window.clearTimeout(t); t = window.setTimeout(load, 500); });
    return () => es.close();
  }, []);
  return missions;
}

function MissionsPage({ selected, agents }: { selected?: string; agents: Record<string, AgentCard> }) {
  const missions = useMissions();
  return (
    <div className={`layout ${selected ? "has-selection" : ""}`}>
      <aside className="rail">
        <Composer onCreated={(id) => { window.location.hash = `#/missions/${id}`; }} />
        <h3 className="rail-title">Missões</h3>
        <ul className="missions">
          {missions.map((m) => (
            <li key={m.id}>
              <a href={`#/missions/${m.id}`} aria-current={selected === m.id ? "page" : undefined} className={`st-${m.status}`}>
                <span className="state-dot" aria-hidden="true" />
                <span className="m-title">{m.title}</span>
                <span className="m-meta">{STATUS_LABEL[m.status]}, {new Date(m.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
                  <span className="num">{usd(m.cost_usd, 3)}</span></span>
              </a>
            </li>
          ))}
          {!missions.length && <li className="muted small">Nenhuma missão ainda. Escolha um exemplo acima para começar.</li>}
        </ul>
      </aside>
      <main className="content">
        {selected ? <MissionView id={selected} agents={agents} /> : (
          <div className="empty">
            <h2>Do pedido ao site no ar, com cada agente rastreável.</h2>
            <p>Escreva uma missão ao lado. Atlas, o orquestrador, transforma o pedido num plano e delega cada parte a um especialista.</p>
            <ol>
              <li>Você aprova o plano antes de qualquer trabalho começar.</li>
              <li>Os especialistas entregam com evidências; o QA verifica e devolve o que não passar.</li>
              <li>Você autoriza a publicação. Tudo fica numa trilha de auditoria à prova de adulteração.</li>
            </ol>
          </div>
        )}
      </main>
    </div>
  );
}

function AgentsPage({ agents }: { agents: AgentCard[] }) {
  return (
    <div className="page">
      <h2>A colônia</h2>
      <p className="lead">Cada especialista tem uma função, entregas definidas e, quando faz sentido, playbooks com o conhecimento do ofício. O roteamento define qual modelo cada um usa.</p>
      <div className="agent-grid">
        {agents.map((a) => (
          <article key={a.role} className="agent-card" style={{ ["--agent" as string]: agentColor(a.role) }}>
            <header><Face role={a.role} name={a.name} size="lg" /><div><h3>{a.name}</h3><div className="muted">{a.title}</div></div></header>
            <p>{a.description}</p>
            <ul className="tags" aria-label="Habilidades">{a.skills.map((s) => <li key={s}>{s}</li>)}</ul>
            <p className="small">Entrega: {a.produces.join(", ")}</p>
            {a.playbooks && a.playbooks.length > 0 && (
              <p className="playbooks"><BookOpen className="icon" aria-hidden="true" /> {a.playbooks.map((p) => `${p.title} (v${p.version})`).join(", ")}</p>
            )}
            <div className="route"><Cpu className="icon" aria-hidden="true" /><code>{a.route}</code></div>
          </article>
        ))}
      </div>
    </div>
  );
}

function CostsPage({ agents }: { agents: Record<string, AgentCard> }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { api.finops().then(setData); }, []);
  if (!data) return <div className="page muted">Carregando…</div>;
  const missions = data.missions.reduce((n: number, m: any) => n + m.count, 0);
  return (
    <div className="page">
      <h2>Custos da plataforma</h2>
      <p className="lead">Quanto os modelos custaram, somando todas as missões. Missões em modo simulado entram com o custo estimado do modelo de referência.</p>
      <div className="figures">
        <div className="figure"><span>Gasto com modelos</span><b>{usd(data.total_usd)}</b></div>
        <div className="figure"><span>Missões</span><b>{missions}</b></div>
        <div className="figure"><span>Média por missão</span><b>{usd(missions ? data.total_usd / missions : 0)}</b></div>
      </div>
      <h4>Por agente e modelo</h4>
      <div className="table-wrap"><table>
        <thead><tr><th>Agente</th><th>Provedor</th><th>Modelo</th><th className="n">Chamadas</th><th className="n">Tokens lidos</th><th className="n">Tokens escritos</th><th className="n">Custo</th></tr></thead>
        <tbody>{data.by_agent_model.map((r: any, i: number) => (
          <tr key={i}><td>{agents[r.agent]?.name ?? r.agent}</td><td>{r.provider}</td><td>{r.model}</td><td className="n">{r.calls}</td>
            <td className="n">{r.input_tokens?.toLocaleString("pt-BR")}</td><td className="n">{r.output_tokens?.toLocaleString("pt-BR")}</td><td className="n">{usd(r.cost_usd)}</td></tr>))}
        </tbody></table></div>
    </div>
  );
}

function ComparePage() {
  const missions = useMissions();
  const [picked, setPicked] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, { m: MissionDetail; x: Metrics }>>({});
  useEffect(() => {
    if (!picked.length && missions.length) setPicked(missions.filter((m) => m.status === "completed").slice(0, 3).map((m) => m.id));
  }, [missions]);
  useEffect(() => {
    picked.filter((id) => !rows[id]).forEach(async (id) => {
      const [m, ev] = await Promise.all([api.mission(id), api.events(id)]) as [MissionDetail, HiveEvent[]];
      setRows((r) => ({ ...r, [id]: { m, x: metrics(m, ev) } }));
    });
  }, [picked]);
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const cols = picked.map((id) => rows[id]).filter(Boolean);
  // f devolve null quando a métrica não se aplica à missão (ex.: missão sem ilustradora).
  const line = (label: string, f: (c: { m: MissionDetail; x: Metrics }) => number | null, fmt: (v: number) => string,
    lower: boolean | null = true) => {
    const vals = cols.map(f).filter((v): v is number => v !== null);
    const target = lower === null || new Set(vals).size < 2 ? null : lower ? Math.min(...vals) : Math.max(...vals);
    return (
      <tr><th>{label}</th>{cols.map((c) => {
        const v = f(c);
        return <td key={c.m.id} className={`n ${v !== null && v === target ? "best" : ""}`}>{v === null ? "—" : fmt(v)}</td>;
      })}</tr>
    );
  };
  return (
    <div className="page">
      <h2>Comparar missões</h2>
      <p className="lead">Escolha missões para comparar modelos, tempo, custo e qualidade lado a lado. O melhor valor de cada linha fica em destaque.</p>
      <div className="compare-pick">
        {missions.map((m) => (
          <button key={m.id} className="pick" aria-pressed={picked.includes(m.id)} onClick={() => toggle(m.id)}>
            <span className={`state-dot st-${m.status}`} style={{ width: 8, height: 8, borderRadius: 99, display: "inline-block" }} />
            {m.title} <span className="faint">{new Date(m.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
          </button>
        ))}
      </div>
      {cols.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Métrica</th>{cols.map((c) => <th key={c.m.id} className="n">{c.m.title}<br /><span className="faint small">{c.x.models.join(", ") || "sem modelo"}</span></th>)}</tr></thead>
          <tbody>
            <tr><th>Situação</th>{cols.map((c) => <td key={c.m.id} className="n"><span className={`state st-${c.m.status}`}>{STATUS_LABEL[c.m.status]}</span></td>)}</tr>
            {line("Tempo dos agentes", ({ x }) => x.agentMs, fmtDuration)}
            {line("Espera por você", ({ x }) => x.humanMs, fmtDuration, null)}
            {line("Chamadas de modelo", ({ x }) => x.calls, String)}
            {line("Tokens escritos", ({ x }) => x.tokensOut, (v) => v.toLocaleString("pt-BR"), null)}
            {line("Velocidade média", ({ x }) => x.tokensPerSec, (v) => `${v.toFixed(1)} tokens/s`, false)}
            {line("Custo", ({ x }) => x.costUsd, (v) => usd(v))}
            {line("Retrabalhos", ({ x }) => x.reworks, String)}
            {line("Ilustrações feitas pelo modelo", ({ m, x }) => (m.tasks.some((t) => t.agent === "illustrator")
              ? x.images.llm : null), (v) => String(v), false)}
            {line("Ilustrações procedurais (plano B)", ({ m, x }) => (m.tasks.some((t) => t.agent === "illustrator")
              ? x.images.procedural : null), (v) => String(v))}
            <tr><th>Custo é estimado?</th>{cols.map((c) => <td key={c.m.id} className="n">{c.x.simulated ? "sim, modo simulado" : "não"}</td>)}</tr>
          </tbody>
        </table></div>
      ) : <p className="muted">Selecione ao menos uma missão.</p>}
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [theme, toggleTheme] = useTheme();
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [engine, setEngine] = useState("");
  useEffect(() => {
    api.agents().then(setAgents);
    api.health().then((h) => setEngine(h.routing.orchestrator ?? h.provider));
  }, []);
  const byRole = Object.fromEntries(agents.map((a) => [a.role, a]));
  const page = route[0] ?? "missions";
  const nav = [
    { key: "missions", label: "Missões", icon: ListTodo },
    { key: "compare", label: "Comparar", icon: GitCompareArrows },
    { key: "agents", label: "Agentes", icon: Users },
    { key: "costs", label: "Custos", icon: Coins },
  ];
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand"><Hexagon aria-hidden="true" />Hive</a>
        <nav aria-label="Principal">
          {nav.map(({ key, label, icon: Icon }) => (
            <a key={key} href={`#/${key}`} aria-current={page === key ? "page" : undefined}><Icon className="icon" aria-hidden="true" />{label}</a>
          ))}
        </nav>
        {engine && <span className="engine"><Cpu className="icon" aria-hidden="true" />Modelo do orquestrador: <b>{engine}</b></span>}
        <button className="theme-toggle" onClick={toggleTheme} aria-label={theme === "dark" ? "Usar tema claro" : "Usar tema escuro"}>
          {theme === "dark" ? <Sun className="icon" /> : <Moon className="icon" />}
        </button>
      </header>
      {page === "agents" ? <AgentsPage agents={agents} />
        : page === "costs" ? <CostsPage agents={byRole} />
        : page === "compare" ? <ComparePage />
        : <MissionsPage selected={route[1]} agents={byRole} />}
    </div>
  );
}
