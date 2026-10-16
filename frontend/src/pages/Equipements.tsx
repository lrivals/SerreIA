// Equipment (docs/12 §2.2): sensors (calibration reminder), actuators (current state,
// manual command), cameras, ESP32 nodes.
import { Pencil, Power } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useActionneurs, useCameras, useCapteurs, useNoeuds, useUpdateCapteur } from "@/api/hooks";
import type { Actionneur, Capteur } from "@/api/types";
import { CommandeManuelle } from "@/components/CommandeManuelle";
import { Empty, ErrorBox, Loading, PageTitle } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ZoneTabs } from "@/components/ZoneTabs";
import { ACTUATOR_LABELS, fmtDateTime, fmtNum, fmtTime, SENSOR_LABELS } from "@/lib/format";

export function Equipements() {
  const [params, setParams] = useSearchParams();
  const zone = params.get("zone") ?? undefined;
  const tab = params.get("onglet") ?? "capteurs";
  const set = (k: string, v?: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next);
  };
  return (
    <>
      <PageTitle title="Équipements">
        <ZoneTabs all value={zone} onChange={(z) => set("zone", z)} />
      </PageTitle>
      <Tabs value={tab} onValueChange={(v) => set("onglet", v)}>
        <TabsList className="mb-3">
          <TabsTrigger value="capteurs">Capteurs</TabsTrigger>
          <TabsTrigger value="actionneurs">Actionneurs</TabsTrigger>
          <TabsTrigger value="cameras">Caméras</TabsTrigger>
          <TabsTrigger value="noeuds">Nœuds</TabsTrigger>
        </TabsList>
        <TabsContent value="capteurs">
          <Capteurs zone={zone} />
        </TabsContent>
        <TabsContent value="actionneurs">
          <Actionneurs zone={zone} />
        </TabsContent>
        <TabsContent value="cameras">
          <Cameras zone={zone} />
        </TabsContent>
        <TabsContent value="noeuds">
          <Noeuds />
        </TabsContent>
      </Tabs>
    </>
  );
}

interface Device {
  id: string;
  channels: Capteur[];
}

function Capteurs({ zone }: { zone?: string }) {
  const { data, isLoading, error } = useCapteurs(zone);
  const [edit, setEdit] = useState<Device | null>(null);
  const devices = useMemo(() => {
    const out = new Map<string, Device>();
    for (const c of data ?? []) {
      const id = c.materiel ?? c.id;
      if (!out.has(id)) out.set(id, { id, channels: [] });
      out.get(id)!.channels.push(c);
    }
    return [...out.values()];
  }, [data]);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <Card>
      <Table>
        <thead>
          <tr>
            <Th>Capteur</Th>
            <Th>Modèle</Th>
            <Th>Mesures</Th>
            <Th>Nœud</Th>
            <Th>Zone</Th>
            <Th>Emplacements</Th>
            <Th>Plage</Th>
            <Th>Étalonnage</Th>
            <Th>Dernière mesure</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {devices.map(({ id, channels }) => {
            const c = channels[0];
            const late = channels.some((x) => x.etalonnage_en_retard);
            const last = channels.map((x) => x.derniere_mesure).filter(Boolean).sort((a, b) => b!.ts.localeCompare(a!.ts))[0];
            return (
              <tr key={id}>
                <Td className="font-mono text-xs">{id}</Td>
                <Td>{c.modele ?? "—"}</Td>
                <Td>{channels.map((x) => SENSOR_LABELS[x.type] ?? x.type).join(", ")}</Td>
                <Td className="font-mono text-xs">{c.noeud}</Td>
                <Td>{c.zone}</Td>
                <Td className="text-xs">{c.cuve_id ? `cuve ${c.cuve_id}` : c.emplacements_couverts.join(", ") || "—"}</Td>
                <Td className="whitespace-nowrap">{c.plage_min !== null ? `${fmtNum(c.plage_min)} – ${fmtNum(c.plage_max)}` : "—"}</Td>
                <Td>
                  {c.etalonnage?.date ? (
                    <span className={late ? "font-medium text-warn" : ""} title={`échéance ${c.etalonnage_echeance}`}>
                      {c.etalonnage.date}
                      {late && <Badge tone="warn" className="ml-1">à refaire</Badge>}
                    </span>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td className="whitespace-nowrap">{last ? `${fmtNum(last.valeur, 2)} · ${fmtTime(last.ts)}` : "—"}</Td>
                <Td>
                  <Button variant="ghost" size="icon" onClick={() => setEdit({ id, channels })} aria-label={`Modifier ${id}`}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      {devices.length === 0 && <Empty>Aucun capteur.</Empty>}
      {edit && <EditCapteur device={edit} onClose={() => setEdit(null)} />}
    </Card>
  );
}

function EditCapteur({ device, onClose }: { device: Device; onClose: () => void }) {
  const c = device.channels[0];
  const update = useUpdateCapteur();
  const [f, setF] = useState({
    modele: c.modele ?? "",
    date: c.etalonnage?.date ?? "",
    methode: c.etalonnage?.methode ?? "",
    plage_min: c.plage_min?.toString() ?? "",
    plage_max: c.plage_max?.toString() ?? "",
  });
  const save = async () => {
    const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
    for (const ch of device.channels)
      await update.mutateAsync({
        id: ch.id,
        modele: f.modele || null,
        etalonnage: f.date ? { ...(ch.etalonnage ?? {}), date: f.date, methode: f.methode || undefined } : ch.etalonnage,
        plage_min: num(f.plage_min),
        plage_max: num(f.plage_max),
      });
    onClose();
  };
  return (
    <Dialog open onOpenChange={onClose} title={`Capteur ${device.id}`} description={`${device.channels.length} canal(aux) : ${device.channels.map((x) => x.type).join(", ")}`}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Modèle">
          <Input value={f.modele} onChange={(e) => setF({ ...f, modele: e.target.value })} />
        </Field>
        <Field label="Dernier étalonnage">
          <Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        </Field>
        <Field label="Méthode" className="col-span-2">
          <Input value={f.methode} onChange={(e) => setF({ ...f, methode: e.target.value })} placeholder="2 points (4,0 / 7,0)" />
        </Field>
        <Field label="Plage min">
          <Input value={f.plage_min} onChange={(e) => setF({ ...f, plage_min: e.target.value })} inputMode="decimal" />
        </Field>
        <Field label="Plage max">
          <Input value={f.plage_max} onChange={(e) => setF({ ...f, plage_max: e.target.value })} inputMode="decimal" />
        </Field>
        {update.error && (
          <div className="col-span-2">
            <ErrorBox error={update.error} />
          </div>
        )}
        <Button className="col-span-2 justify-self-end" onClick={save} disabled={update.isPending}>
          Enregistrer
        </Button>
      </div>
    </Dialog>
  );
}

function Actionneurs({ zone }: { zone?: string }) {
  const { data, isLoading, error } = useActionneurs(zone);
  const [cmd, setCmd] = useState<Actionneur | null>(null);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <Card>
      <Table>
        <thead>
          <tr>
            <Th>Actionneur</Th>
            <Th>Type</Th>
            <Th>Zone</Th>
            <Th>Nœud</Th>
            <Th>Puissance</Th>
            <Th>Débit</Th>
            <Th>PPFD max</Th>
            <Th>Durée max</Th>
            <Th>État</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {data?.map((a) => (
            <tr key={a.id}>
              <Td className="font-mono text-xs">{a.id}</Td>
              <Td>{ACTUATOR_LABELS[a.type] ?? a.type}</Td>
              <Td>{a.zone_id}</Td>
              <Td className="font-mono text-xs">{a.noeud}</Td>
              <Td>{a.puissance_w !== null ? `${fmtNum(a.puissance_w, 0)} W` : "—"}</Td>
              <Td>{a.debit_l_h !== null ? `${fmtNum(a.debit_l_h)} L/h` : a.debit_ml_min !== null ? `${fmtNum(a.debit_ml_min)} mL/min` : "—"}</Td>
              <Td>{a.ppfd_max ?? "—"}</Td>
              <Td>{a.duree_max_s !== null ? `${fmtNum(a.duree_max_s, 0)} s` : "—"}</Td>
              <Td>
                {a.etat ? (
                  <Badge tone={a.etat.action === "off" ? "neutral" : "ok"} title={fmtDateTime(a.etat.ts)}>
                    {a.etat.action === "pwm" ? `${fmtNum(a.etat.valeur, 0)} %` : a.etat.action}
                  </Badge>
                ) : (
                  <Badge>inconnu</Badge>
                )}
              </Td>
              <Td>
                <Button size="sm" variant="outline" onClick={() => setCmd(a)}>
                  <Power className="h-3.5 w-3.5" /> Commande
                </Button>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {cmd && <CommandeManuelle actionneur={cmd} onClose={() => setCmd(null)} />}
    </Card>
  );
}

function Cameras({ zone }: { zone?: string }) {
  const { data, isLoading, error } = useCameras(zone);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <Card>
      <Table>
        <thead>
          <tr>
            <Th>Caméra</Th>
            <Th>Zone</Th>
            <Th>Emplacements visibles</Th>
            <Th>Dernière image</Th>
          </tr>
        </thead>
        <tbody>
          {data?.map((c) => (
            <tr key={c.id}>
              <Td className="font-mono text-xs">{c.id}</Td>
              <Td>{c.zone_id}</Td>
              <Td>
                {c.regions.map((r) => `${r.emplacement_id}${r.bbox ? " ✓" : ""}`).join(", ") || "—"}
              </Td>
              <Td>{c.derniere_image ? fmtDateTime(c.derniere_image.ts) : "—"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p className="px-3 py-2 text-xs text-muted-foreground">Les régions se dessinent depuis le constructeur (caméras de la zone).</p>
    </Card>
  );
}

function Noeuds() {
  const { data, isLoading, error } = useNoeuds();
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <Card>
      <Table>
        <thead>
          <tr>
            <Th>Nœud</Th>
            <Th>Statut</Th>
            <Th>Depuis</Th>
            <Th>Dernière mesure</Th>
            <Th>Zones</Th>
          </tr>
        </thead>
        <tbody>
          {data?.map((n) => (
            <tr key={n.id}>
              <Td className="font-mono text-xs">{n.id}</Td>
              <Td>
                <Badge tone={n.status === "online" ? "ok" : n.status === "offline" ? "bad" : "neutral"}>{n.status ?? "inconnu"}</Badge>
              </Td>
              <Td>{fmtDateTime(n.status_ts)}</Td>
              <Td>{fmtDateTime(n.derniere_mesure)}</Td>
              <Td>{n.zones.join(", ")}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}
