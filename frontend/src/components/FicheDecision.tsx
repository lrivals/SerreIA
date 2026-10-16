// Decision record (docs/12 §2.5): what was decided and why — vision evidence (image,
// Grad-CAM, classes), sensor evidence (curves centred on the decision, window used by the
// rule highlighted), forecast, setpoints — then the actions and their confirmation.
import { Bot, CheckCircle2, CircleDashed, Clock, XCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMesures } from "@/api/hooks";
import type { ActionDetail, DecisionRecord, PreuveCapteur } from "@/api/types";
import { ACTUATOR_LABELS, fmtDateTime, fmtNum, SENSOR_LABELS } from "@/lib/format";
import { Courbe } from "./Charts";
import { CarteProposition } from "./CarteProposition";
import { Empty, NiveauBadge, RefText, StatutBadge } from "./common";
import { ImageAnnotee } from "./ImageAnnotee";
import { Button } from "./ui/button";
import { Card, CardBody, CardHeader } from "./ui/card";

const H = 3600_000;

/** Time window (ms) the rule looked at, from the aggregate of the evidence. */
export function ruleWindow(p: PreuveCapteur, ts: string): [number, number] {
  const t = Date.parse(ts);
  if (p.agregat === "duree_au_dessus" && p.unite === "h") return [t - p.valeur * H, t];
  const hours = /(\d+(?:[.,]\d+)?)h/.exec(p.agregat);
  if (hours) return [t - Number(hours[1].replace(",", ".")) * H, t];
  if (p.agregat === "derniere") return [t - 10 * 60_000, t];
  if (p.agregat.startsWith("dli")) {
    const d = new Date(t);
    d.setHours(0, 0, 0, 0);
    return [d.getTime(), t];
  }
  return [t - H, t];
}

function consigneRange(consignes: Record<string, unknown>, type: string): [number, number] | null {
  const v = consignes[type];
  return Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "number") ? (v as [number, number]) : null;
}

function CourbePreuve({ d, p }: { d: DecisionRecord; p: PreuveCapteur }) {
  const type = p.topic.split("/").pop()!;
  const t = Date.parse(d.ts);
  const { data } = useMesures({
    zone: d.zone,
    type: [type],
    emplacement: p.emplacement ?? undefined,
    debut: new Date(t - 12 * H).toISOString(),
    fin: new Date(t + 12 * H).toISOString(),
    agregat: "moy_15min",
  });
  const serie = data?.series.find((s) => s.type === type && (s.emplacement ?? null) === (p.emplacement ?? null)) ?? data?.series[0];
  const unite = p.unite === "h" ? serie?.unite ?? "" : p.unite;
  return (
    <div className="border-b pb-3 last:border-0">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">
          {SENSOR_LABELS[type] ?? type}
          {p.emplacement && ` · ${p.emplacement}`}
        </span>
        <span className="text-xs text-muted-foreground">
          {p.agregat.replaceAll("_", " ")} = {fmtNum(p.valeur, 2)} {p.unite}
          {p.seuil !== null && ` · seuil ${fmtNum(p.seuil, 2)}`}
          {p.qualite !== "ok" && ` · ${p.qualite}`}
        </span>
      </div>
      {serie ? (
        <Courbe
          points={serie.points}
          unite={unite}
          instant={d.ts}
          fenetre={ruleWindow(p, d.ts)}
          seuil={p.unite === "h" ? null : p.seuil}
          plage={consigneRange(d.preuves.consignes, type)}
          height={130}
        />
      ) : (
        <Empty>Pas de mesures autour de la décision.</Empty>
      )}
    </div>
  );
}

const RESULT_ICON: Record<string, JSX.Element> = {
  confirmee: <CheckCircle2 className="h-4 w-4 text-ok" />,
  proposee: <Clock className="h-4 w-4 text-info" />,
  en_attente: <Clock className="h-4 w-4 text-warn" />,
  annulee: <CircleDashed className="h-4 w-4 text-muted-foreground" />,
};

function ActionLine({ a }: { a: ActionDetail }) {
  const [open, setOpen] = useState(false);
  const target = a.cible.startsWith("actionneur:") ? ACTUATOR_LABELS[a.cible.slice(11)] ?? a.cible : a.cible;
  return (
    <li className="text-sm">
      <button className="flex w-full cursor-pointer flex-wrap items-center gap-2 text-left" onClick={() => setOpen(!open)}>
        {RESULT_ICON[a.resultat] ?? <XCircle className="h-4 w-4 text-bad" />}
        <span className="font-medium">{a.label}</span>
        <span className="text-xs text-muted-foreground">{target}</span>
        <StatutBadge statut={a.resultat} />
        <span className="text-xs text-muted-foreground">
          {fmtDateTime(a.ts_debut)}
          {a.ts_fin && ` → ${fmtDateTime(a.ts_fin)}`}
        </span>
      </button>
      {open && a.commande && (
        <pre className="mt-1 ml-6 overflow-x-auto rounded bg-muted p-2 text-xs">{JSON.stringify(a.commande, null, 2)}</pre>
      )}
    </li>
  );
}

export function FicheDecision({ d }: { d: DecisionRecord }) {
  const navigate = useNavigate();
  const [gradcam, setGradcam] = useState(false);
  const [why] = d.explication.split(" → ");
  const consignes = Object.entries(d.preuves.consignes ?? {}).filter(([k]) => k !== "recettes");

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardBody className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono">{d.id}</span>
            <NiveauBadge niveau={d.niveau} />
            <span className="text-muted-foreground">
              règle {d.regle.id} v{d.regle.version}
            </span>
            <StatutBadge statut={d.statut} />
            <span className="text-muted-foreground">
              {d.type} · {d.origine} · {fmtDateTime(d.ts)}
            </span>
          </div>
          <p className="text-base">
            <RefText text={d.explication} />
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {d.config_version !== null && <span>config v{d.config_version}</span>}
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                navigate(`/agent?message=${encodeURIComponent(`Explique la décision ${d.id} : ${why}`)}`)
              }
            >
              <Bot className="h-3.5 w-3.5" /> Demander à l'agent
            </Button>
          </div>
        </CardBody>
      </Card>

      {d.statut === "proposee" && <CarteProposition decision={d} />}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader
            title="Vision"
            action={
              d.preuves.vision.length > 0 && (
                <label className="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" checked={gradcam} onChange={(e) => setGradcam(e.target.checked)} /> Grad-CAM
                </label>
              )
            }
          />
          <CardBody className="flex flex-col gap-4">
            {d.preuves.vision.length === 0 && <Empty>Pas de preuve visuelle.</Empty>}
            {d.preuves.vision.map((v) => (
              <div key={v.image_id + v.classe} className="flex flex-col gap-2">
                <ImageAnnotee
                  imageId={v.image_id}
                  gradcam={gradcam}
                  annotations={[{ bbox: v.bbox, label: `${v.emplacement ?? ""} ${v.classe}`, sain: v.sante === "sain" }]}
                />
                <table className="text-sm">
                  <tbody>
                    {v.espece && (
                      <tr>
                        <td className="pr-3 text-muted-foreground">espèce</td>
                        <td>{v.espece}</td>
                        <td className="text-right">{fmtNum(v.espece_conf, 2)}</td>
                      </tr>
                    )}
                    <tr>
                      <td className="pr-3 text-muted-foreground">santé</td>
                      <td>{v.sante}</td>
                      <td className="text-right">{fmtNum(v.sante_conf, 2)}</td>
                    </tr>
                    <tr>
                      <td className="pr-3 text-muted-foreground">classe</td>
                      <td>{v.classe}</td>
                      <td className="text-right">
                        {fmtNum(v.classe_conf, 2)}
                        {v.confirmations > 1 && ` ×${v.confirmations} conf.`}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p className="text-xs text-muted-foreground">
                  {v.camera} · {v.modele} · <span className="font-mono">{v.image_id}</span>
                </p>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Capteurs (± 12 h, fenêtre de la règle surlignée)" />
          <CardBody className="flex flex-col gap-3">
            {d.preuves.capteurs.length === 0 && <Empty>Pas de preuve capteur.</Empty>}
            {d.preuves.capteurs.map((p, i) => (
              <CourbePreuve key={i} d={d} p={p} />
            ))}
            {d.preuves.prevision.length > 0 && (
              <div className="text-sm">
                <span className="font-medium">Prévision</span>{" "}
                {d.preuves.prevision.map((p) => `${p.grandeur} ${p.horizon} = ${fmtNum(p.valeur, 1)} (${p.modele})`).join(" · ")}
              </div>
            )}
            {consignes.length > 0 && (
              <div className="text-sm">
                <span className="font-medium">Consignes</span>{" "}
                {(d.preuves.consignes.recettes as string[] | undefined)?.join(", ")} :{" "}
                {consignes.map(([k, v]) => `${k} ${JSON.stringify(v)}`).join(" · ")}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Actions" />
        <CardBody>
          {d.actions_detail.length === 0 ? (
            <Empty>Aucune action.</Empty>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {d.actions_detail.map((a) => (
                <ActionLine key={a.id} a={a} />
              ))}
            </ul>
          )}
          {d.commandes.length > 0 && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-muted-foreground">{d.commandes.length} commande(s) MQTT</summary>
              <ul className="mt-1 space-y-0.5 font-mono text-xs">
                {d.commandes.map((c) => (
                  <li key={c.ts + c.actionneur}>
                    {fmtDateTime(c.ts)} cmd/{c.actionneur} {c.action}
                    {c.valeur !== null && ` ${c.valeur}`}
                    {c.duree_s !== null && ` ${c.duree_s} s`} · {c.source}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
