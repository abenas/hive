import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { agentColor, STATUS_LABEL, usd, type AgentCard, type MissionDetail, type Task } from "../api";

type AgentNodeData = {
  agentName: string; agentTitle: string; title: string; status: string; color: string;
  attempt?: number; cost?: number; selected?: boolean; isOrchestrator?: boolean;
};

function AgentNode({ data }: NodeProps<Node<AgentNodeData>>) {
  return (
    <div className={`agent-node status-${data.status} ${data.selected ? "is-selected" : ""}`}
      style={{ ["--agent" as string]: data.color }}>
      <Handle type="target" position={Position.Left} />
      <div className="agent-node-head">
        <span className="face" aria-hidden="true">{data.agentName[0]}</span>
        <div>
          <div className="agent-node-name">{data.agentName}</div>
          <div className="agent-node-role">{data.agentTitle}</div>
        </div>
        {data.attempt && data.attempt > 1 ? <span className="attempts" title="Tentativas">{data.attempt}ª vez</span> : null}
      </div>
      <div className="agent-node-title">{data.title}</div>
      <div className="agent-node-foot">
        <span className={`state st-${data.status === "done" ? "completed" : data.status === "running" ? "executing" : data.status}`}>
          {STATUS_LABEL[data.status] ?? data.status}</span>
        {data.cost ? <span className="cost">{usd(data.cost, 4)}</span> : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { agent: AgentNode };

function levels(tasks: Task[]): Map<string, number> {
  const byKey = new Map(tasks.map((t) => [t.key, t]));
  const memo = new Map<string, number>();
  const depth = (k: string): number => {
    if (memo.has(k)) return memo.get(k)!;
    const t = byKey.get(k);
    const d = t && t.depends_on.length ? 1 + Math.max(...t.depends_on.map(depth)) : 0;
    memo.set(k, d);
    return d;
  };
  tasks.forEach((t) => depth(t.key));
  return memo;
}

export function MissionGraph({ mission, agents, selected, onSelect }: {
  mission: MissionDetail; agents: Record<string, AgentCard>; selected: string | null; onSelect: (taskId: string | null) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const lv = levels(mission.tasks);
    const columns = new Map<number, Task[]>();
    mission.tasks.forEach((t) => columns.set(lv.get(t.key)!, [...(columns.get(lv.get(t.key)!) ?? []), t]));
    const orchStatus = ["received", "interpreting", "planning"].includes(mission.status) ? "running"
      : mission.status === "failed" ? "failed" : "done";
    const orch = agents.orchestrator;
    const nodes: Node<AgentNodeData>[] = [{
      id: "orchestrator", type: "agent", position: { x: 0, y: 140 },
      data: { agentName: orch?.name ?? "Atlas", agentTitle: "Orquestrador", title: "Briefing, plano e delegação",
        status: orchStatus, color: agentColor("orchestrator"), isOrchestrator: true },
    }];
    for (const [col, list] of columns) {
      list.forEach((t, i) => {
        const a = agents[t.agent];
        nodes.push({
          id: t.id, type: "agent",
          position: { x: 225 * (col + 1), y: 140 + (i - (list.length - 1) / 2) * 125 },
          data: { agentName: a?.name ?? t.agent, agentTitle: a?.title ?? t.agent, title: t.title, status: t.status,
            color: agentColor(t.agent), attempt: t.attempt, cost: t.cost_usd, selected: selected === t.id },
        });
      });
    }
    const idOf = new Map(mission.tasks.map((t) => [t.key, t.id]));
    const edges: Edge[] = [];
    for (const t of mission.tasks) {
      const sources = t.depends_on.length ? t.depends_on.map((k) => idOf.get(k)!) : ["orchestrator"];
      for (const s of sources) {
        edges.push({
          id: `${s}-${t.id}`, source: s, target: t.id, animated: t.status === "running",
          markerEnd: { type: MarkerType.ArrowClosed },
          className: t.status === "running" ? "edge-active" : t.status === "done" ? "edge-done" : "",
          style: s === "orchestrator" ? { strokeDasharray: "6 4" } : undefined,
        });
      }
    }
    return { nodes, edges };
  }, [mission, agents, selected]);

  if (!mission.tasks.length) {
    return <div className="graph-empty">O orquestrador está montando o plano. As tarefas aparecem aqui assim que ele terminar.</div>;
  }
  return (
    <div className="graph">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.08, maxZoom: 1.1 }} minZoom={0.4}
        nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onSelect(n.id === "orchestrator" ? null : n.id)}>
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
