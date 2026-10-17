// Action tree (docs/12 §2.6, docs/10 §6): greenhouse → zones → routines / exceptional /
// safety / manual → decisions → actions. Routine branches are aggregated and collapsed
// ("×14 cycles"), exceptional ones open; 24 h / 7 d cursor; a decision opens its record,
// an action shows its command and confirmed state.
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useArbre } from "@/api/hooks";
import type { TreeNode } from "@/api/types";
import { ErrorBox, Loading, PageTitle, StatutBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ZoneTabs } from "@/components/ZoneTabs";
import { ACTUATOR_LABELS, fmtDateTime, fmtDuration, fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const W = 230;
const H = 58;
const PERIODS: Record<string, number> = { "24 h": 24, "7 j": 168 };

const STATUS_BORDER: Record<string, string> = {
  executee: "border-ok",
  terminee: "border-ok",
  confirmee: "border-ok",
  proposee: "border-info",
  validee: "border-info",
  rejetee: "border-muted-foreground",
  expiree: "border-muted-foreground",
  annulee: "border-muted-foreground",
  bloquee_securite: "border-bad",
  bloquee: "border-bad",
  echec: "border-bad",
  non_confirmee: "border-warn",
  en_attente: "border-warn",
};

const ICONS: Record<string, string> = {
  ventilo: "🌀",
  chauffage: "🔥",
  brumisateur: "💨",
  led: "💡",
  pompe_nutri: "💧",
  pompe_ph_down: "🧪",
  pompe_nutri_a: "🧪",
  pompe_nutri_b: "🧪",
  alerte: "🔔",
  camera: "📷",
  plante: "🌱",
};

function icon(cible?: string) {
  if (!cible) return "";
  const [kind, what] = cible.split(":");
  return ICONS[what] ?? ICONS[kind] ?? "•";
}

interface Data extends Record<string, unknown> {
  node: TreeNode;
  parent?: string;
  expandable: boolean;
  expanded: boolean;
}

function TreeCard({ data }: NodeProps<Node<Data>>) {
  const n = data.node;
  const status = n.statut ?? n.resultat;
  let title: string = n.label ?? n.id;
  let sub = "";
  if (n.type === "decision") {
    title = n.resume ?? n.id;
    sub = `${fmtTime(n.ts)} · ${n.regle}`;
  } else if (n.type === "action") {
    title = `${icon(n.cible)} ${n.label}`;
    sub = n.cible?.startsWith("actionneur:") ? ACTUATOR_LABELS[n.cible.slice(11)] ?? n.cible : n.cible ?? "";
  } else if (n.type === "routine") {
    title = `${n.label}`;
    sub = `×${n.cycles} cycles · ${fmtDuration(n.duree_on_s as number)} en marche${(n.echecs as number) ? ` · ${n.echecs} échec(s)` : ""}`;
  }
  return (
    <div
      className={cn(
        "rounded-md border-2 bg-card px-2.5 py-1.5 text-xs shadow-sm",
        status ? STATUS_BORDER[status] ?? "border-border" : "border-border",
        (n.type === "serre" || n.type === "zone" || n.type === "groupe") && "bg-muted font-semibold",
      )}
      style={{ width: W, minHeight: H - 8 }}
    >
      <Handle type="target" position={Position.Left} className="!opacity-0" />
      <div className="line-clamp-2">{title}</div>
      {sub && <div className="truncate text-[11px] font-normal text-muted-foreground">{sub}</div>}
      {data.expandable && (
        <div className="text-[10px] text-primary">{data.expanded ? "▾ replier" : "▸ déplier"}</div>
      )}
      <Handle type="source" position={Position.Right} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { card: TreeCard };

/** Visible nodes and edges: a routine's decisions appear when it is expanded; groups and
 * decisions can be collapsed. */
export function flatten(root: TreeNode, expanded: Set<string>, collapsed: Set<string>) {
  const nodes: Node<Data>[] = [];
  const edges: Edge[] = [];
  const visit = (n: TreeNode, parent?: string) => {
    const kids: TreeNode[] =
      n.type === "routine"
        ? expanded.has(n.id)
          ? ((n.decisions as string[]) ?? []).map((id) => ({ id, type: "decision", resume: id, regle: n.regle as string }))
          : []
        : collapsed.has(n.id)
          ? []
          : n.children ?? [];
    const expandable = n.type === "routine" || ((n.children?.length ?? 0) > 0 && n.type !== "serre");
    const isOpen = n.type === "routine" ? expanded.has(n.id) : !collapsed.has(n.id);
    nodes.push({ id: n.id, type: "card", position: { x: 0, y: 0 }, data: { node: n, parent, expandable, expanded: isOpen } });
    if (parent) edges.push({ id: `${parent}->${n.id}`, source: parent, target: n.id, type: "smoothstep" });
    kids.forEach((k) => visit(k, n.id));
  };
  visit(root);
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 10, ranksep: 46 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  nodes.forEach((n) => {
    const p = g.node(n.id);
    n.position = { x: p.x - W / 2, y: p.y - H / 2 };
  });
  return { nodes, edges };
}

export default function Arbre() {
  const [params, setParams] = useSearchParams();
  const zone = params.get("zone") ?? undefined;
  const periode = params.get("periode") ?? "24 h";
  const fin = useMemo(() => new Date(), []);
  const { data, isLoading, error } = useArbre({
    zone,
    debut: new Date(fin.getTime() - PERIODS[periode] * 3600_000).toISOString(),
    fin: fin.toISOString(),
  });
  const [expanded, setExpanded] = useState(new Set<string>());
  const [collapsed, setCollapsed] = useState(new Set<string>());
  const [action, setAction] = useState<{ node: TreeNode; decision?: string } | null>(null);
  const navigate = useNavigate();
  const graph = useMemo(() => (data ? flatten(data, expanded, collapsed) : null), [data, expanded, collapsed]);

  const toggle = (set: Set<string>, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };
  const set = (k: string, v?: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next);
  };

  return (
    <>
      <PageTitle title="Arbre des actions">
        <ZoneTabs all value={zone} onChange={(z) => set("zone", z)} />
        <div className="inline-flex gap-1 rounded-lg bg-muted p-1">
          {Object.keys(PERIODS).map((p) => (
            <Button key={p} size="sm" variant={periode === p ? "outline" : "ghost"} onClick={() => set("periode", p)}>
              {p}
            </Button>
          ))}
        </div>
      </PageTitle>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {graph && (
        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          <Card className="h-[70vh] overflow-hidden">
            <ReactFlow
              nodes={graph.nodes}
              edges={graph.edges}
              nodeTypes={nodeTypes}
              fitView
              minZoom={0.1}
              nodesDraggable={false}
              nodesConnectable={false}
              proOptions={{ hideAttribution: true }}
              onNodeClick={(_, n) => {
                const t = n.data.node;
                if (t.type === "routine") setExpanded((s) => toggle(s, t.id));
                else if (t.type === "action") setAction({ node: t, decision: n.data.parent });
                else if (t.type === "decision" && !t.children?.length) navigate(`/decisions/${t.id}`);
                else if (t.type === "decision") setCollapsed((s) => toggle(s, t.id));
                else if (t.type !== "serre") setCollapsed((s) => toggle(s, t.id));
              }}
              onNodeDoubleClick={(_, n) => n.data.node.type === "decision" && navigate(`/decisions/${n.id}`)}
            >
              <Background gap={16} color="var(--border)" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </Card>
          <Card className="p-4 text-sm">
            {action ? (
              <div className="flex flex-col gap-2">
                <h2 className="font-semibold">
                  {icon(action.node.cible)} {action.node.label}
                </h2>
                <p className="font-mono text-xs text-muted-foreground">{action.node.cible}</p>
                <StatutBadge statut={action.node.resultat ?? ""} />
                <p>
                  {fmtDateTime(action.node.ts_debut)}
                  {action.node.ts_fin && ` → ${fmtDateTime(action.node.ts_fin)}`}
                </p>
                {action.decision && (
                  <Link className="text-primary hover:underline" to={`/decisions/${action.decision}`}>
                    Commande MQTT et confirmation dans la fiche décision
                  </Link>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground">
                Clic sur une routine : afficher ses cycles. Clic (ou double-clic) sur une décision : sa fiche. Clic sur une action : son détail.
              </p>
            )}
            <div className="mt-4 flex flex-col gap-1 border-t pt-3 text-xs text-muted-foreground">
              <span><span className="mr-1 inline-block h-2 w-3 rounded-sm border-2 border-ok" /> exécutée / confirmée</span>
              <span><span className="mr-1 inline-block h-2 w-3 rounded-sm border-2 border-info" /> proposée / validée</span>
              <span><span className="mr-1 inline-block h-2 w-3 rounded-sm border-2 border-muted-foreground" /> rejetée / expirée</span>
              <span><span className="mr-1 inline-block h-2 w-3 rounded-sm border-2 border-bad" /> bloquée / échec</span>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
