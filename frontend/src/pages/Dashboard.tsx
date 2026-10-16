// Dashboard (docs/12 §2.3): per zone, current values against the setpoint range, 24 h
// mini-curves, actuator states, last image with its classifications, active alerts and
// proposals waiting for a validation.
import { BellOff, Moon, Sun } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useAcquitter, useTableau } from "@/api/hooks";
import type { Tuile } from "@/api/types";
import { MiniCourbe } from "@/components/Charts";
import { CarteProposition } from "@/components/CarteProposition";
import { Empty, ErrorBox, Loading, PageTitle } from "@/components/common";
import { ImageAnnotee, visionLabel } from "@/components/ImageAnnotee";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useZoneParam, ZoneTabs } from "@/components/ZoneTabs";
import { ACTUATOR_LABELS, fmtDateTime, fmtNum, fmtTime, SENSOR_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";

const TILE_STYLE: Record<Tuile["statut"], string> = {
  ok: "border-l-ok",
  attention: "border-l-warn",
  alerte: "border-l-bad",
  inconnu: "border-l-border",
};
const TILE_COLOR: Record<Tuile["statut"], string> = {
  ok: "var(--ok)",
  attention: "var(--warn)",
  alerte: "var(--bad)",
  inconnu: "var(--muted-foreground)",
};

export function TuileMesure({ t }: { t: Tuile }) {
  return (
    <div className={cn("rounded-lg border border-l-4 bg-card p-3", TILE_STYLE[t.statut])} data-testid="tuile">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {SENSOR_LABELS[t.type] ?? t.type}
          {t.emplacement && ` · ${t.emplacement}`}
        </span>
        <span title={fmtDateTime(t.ts)}>{fmtTime(t.ts)}</span>
      </div>
      <div className="mt-0.5 text-2xl font-semibold">
        {fmtNum(t.valeur, t.type === "ph" || t.type === "ec" ? 2 : 1)}
        <span className="ml-1 text-sm font-normal text-muted-foreground">{t.unite}</span>
      </div>
      <div className="text-xs text-muted-foreground">
        {t.plage ? `consigne ${fmtNum(t.plage[0])}–${fmtNum(t.plage[1])} ${t.unite}` : "pas de consigne"}
        {t.qualite !== "ok" && <Badge tone="warn" className="ml-1">{t.qualite}</Badge>}
      </div>
      <MiniCourbe points={t.points} plage={t.plage} color={TILE_COLOR[t.statut]} />
    </div>
  );
}

export function Dashboard() {
  const [params, setParams] = useSearchParams();
  const zone = useZoneParam(params.get("zone"));
  const { data, error, isLoading } = useTableau(zone);
  const acquitter = useAcquitter();

  return (
    <>
      <PageTitle title="Tableau de bord">
        <ZoneTabs value={zone} onChange={(z) => setParams(z ? { zone: z } : {})} />
      </PageTitle>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              {data.jour ? <Sun className="h-4 w-4 text-warn" /> : <Moon className="h-4 w-4" />}
              {data.jour ? "Jour (photopériode)" : "Nuit"}
              {data.consignes && (
                <span>· recettes : {(data.consignes.recettes as string[] | undefined)?.join(", ")}</span>
              )}
            </div>
            {data.mesures.length === 0 ? (
              <Card>
                <Empty>Aucune mesure sur les dernières 24 h.</Empty>
              </Card>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
                {data.mesures.map((t) => (
                  <TuileMesure key={`${t.type}-${t.emplacement}`} t={t} />
                ))}
              </div>
            )}
            <Card>
              <CardHeader title="Actionneurs" />
              <CardBody className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-2">
                {data.actionneurs.map((a) => {
                  const on = a.etat && a.etat.action !== "off";
                  return (
                    <div key={a.id} className="flex items-center justify-between rounded-md border px-2.5 py-1.5 text-sm">
                      <span>{ACTUATOR_LABELS[a.type] ?? a.type}</span>
                      {a.etat ? (
                        <Badge tone={on ? "ok" : "neutral"} title={fmtDateTime(a.etat.ts)}>
                          {a.etat.action === "pwm" ? `${fmtNum(a.etat.valeur, 0)} %` : a.etat.action}
                        </Badge>
                      ) : (
                        <Badge>inconnu</Badge>
                      )}
                    </div>
                  );
                })}
              </CardBody>
            </Card>
            <Card>
              <CardHeader
                title="Dernière image"
                action={data.image && <span className="text-xs text-muted-foreground">{data.image.camera} · {fmtDateTime(data.image.ts)}</span>}
              />
              <CardBody>
                {data.image ? (
                  <ImageAnnotee
                    className="max-w-2xl"
                    imageId={data.image.image_id}
                    annotations={data.image.detections.map((d) => ({
                      bbox: d.bbox,
                      label: visionLabel(d),
                      sain: d.sante === "sain",
                    }))}
                  />
                ) : (
                  <Empty>Aucune image reçue.</Empty>
                )}
              </CardBody>
            </Card>
          </div>
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader title={`Propositions en attente (${data.propositions.length})`} />
              <CardBody className="flex flex-col gap-2">
                {data.propositions.length === 0 && <Empty>Rien à valider.</Empty>}
                {data.propositions.map((d) => (
                  <CarteProposition key={d.id} decision={d} />
                ))}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={`Alertes actives (${data.alertes.length})`} />
              <CardBody className="flex flex-col gap-2">
                {data.alertes.length === 0 && <Empty>Aucune alerte.</Empty>}
                {data.alertes.map((a) => (
                  <div key={a.id} className="flex items-start justify-between gap-2 text-sm">
                    <div>
                      <Badge tone={a.niveau === "critique" ? "bad" : a.niveau === "warning" ? "warn" : "info"}>
                        {a.niveau}
                      </Badge>{" "}
                      {a.message}
                      <div className="text-xs text-muted-foreground">
                        {fmtDateTime(a.ts)} · {a.source}
                      </div>
                    </div>
                    <Button size="icon" variant="ghost" title="Acquitter" onClick={() => acquitter.mutate(a.id)}>
                      <BellOff className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </CardBody>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
