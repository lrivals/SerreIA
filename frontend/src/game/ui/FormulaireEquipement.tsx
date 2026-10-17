// Window asked when a sensor, an actuator or a camera is dropped in the builder (docs/13 §4):
// model, node and power; the object is created with its position (`disposition`).
import { useState } from "react";
import { useCreateActionneur, useCreateCamera, useCreateCapteur, useNoeuds } from "@/api/hooks";
import type { Disposition, Schemas } from "@/api/types";
import { ErrorBox } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { ACTUATOR_LABELS, SENSOR_LABELS } from "@/lib/format";
import type { Article } from "./Inventaire";

export interface Cree {
  genre: "capteur" | "actionneur" | "camera";
  id: string;
}

export function FormulaireEquipement({
  article,
  zone,
  disposition,
  emplacements,
  onClose,
  onCreated,
}: {
  article: Extract<Article, { famille: "capteur" | "actionneur" | "camera" }>;
  zone: string;
  disposition: Disposition;
  emplacements: string[];
  onClose: () => void;
  onCreated: (c: Cree) => void;
}) {
  const noeuds = useNoeuds();
  const capteur = useCreateCapteur();
  const actionneur = useCreateActionneur();
  const camera = useCreateCamera();
  const type = article.famille === "camera" ? "camera" : article.type;
  const [f, setF] = useState({
    id: article.famille === "camera" ? `cam-${zone}-${Math.random().toString(36).slice(2, 4)}` : `${type.replace(/_/g, "-")}-${zone}`,
    noeud: noeuds.data?.find((n) => n.zones.includes(zone))?.id ?? `esp32-${zone}`,
    materiel: "",
    modele: "",
    emplacement: "",
    commande: "on_off",
    puissance_w: "",
  });
  const erreur = capteur.error ?? actionneur.error ?? camera.error;
  const enCours = capteur.isPending || actionneur.isPending || camera.isPending;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const valider = () => {
    if (article.famille === "capteur")
      capteur.mutate(
        {
          noeud: f.noeud,
          zone,
          type: article.type as Schemas["CapteurIn"]["type"],
          materiel: f.materiel || null,
          modele: f.modele || null,
          emplacement: f.emplacement || null,
          disposition,
        },
        { onSuccess: (c) => (onCreated({ genre: "capteur", id: c.id }), onClose()) },
      );
    else if (article.famille === "actionneur")
      actionneur.mutate(
        {
          id: f.id,
          zone_id: zone,
          type: article.type as Schemas["ActionneurIn"]["type"],
          noeud: f.noeud,
          commande: f.commande,
          puissance_w: f.puissance_w === "" ? null : Number(f.puissance_w),
          disposition,
        },
        { onSuccess: (a) => (onCreated({ genre: "actionneur", id: a.id }), onClose()) },
      );
    else camera.mutate({ id: f.id, zone_id: zone, disposition }, { onSuccess: (c) => (onCreated({ genre: "camera", id: c.id }), onClose()) });
  };

  const titre =
    article.famille === "capteur"
      ? `Nouveau capteur ${SENSOR_LABELS[article.type] ?? article.type}`
      : article.famille === "actionneur"
        ? `Nouvel actionneur ${ACTUATOR_LABELS[article.type] ?? article.type}`
        : "Nouvelle caméra";

  return (
    <Dialog open onOpenChange={onClose} title={`${titre} · ${zone}`} description={`case (${disposition.x}, ${disposition.y})`}>
      <form
        className="grid grid-cols-2 gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          valider();
        }}
      >
        {article.famille !== "capteur" && (
          <Field label="Identifiant">
            <Input value={f.id} onChange={set("id")} pattern="[a-z0-9][a-z0-9_\-]{0,63}" required />
          </Field>
        )}
        {article.famille !== "camera" && (
          <Field label="Nœud ESP32">
            <Input value={f.noeud} onChange={set("noeud")} list="jeu-noeuds" required />
            <datalist id="jeu-noeuds">
              {noeuds.data?.map((n) => (
                <option key={n.id} value={n.id} />
              ))}
            </datalist>
          </Field>
        )}
        {article.famille === "capteur" && (
          <>
            <Field label="Matériel (boîtier)">
              <Input value={f.materiel} onChange={set("materiel")} placeholder={`sht41-${zone}`} />
            </Field>
            <Field label="Modèle">
              <Input value={f.modele} onChange={set("modele")} placeholder="SHT41, DFRobot pH…" />
            </Field>
            {article.type === "humidite_sol" && (
              <Field label="Emplacement sondé">
                <Select value={f.emplacement} onChange={set("emplacement")} required>
                  <option value="">—</option>
                  {emplacements.map((e) => (
                    <option key={e}>{e}</option>
                  ))}
                </Select>
              </Field>
            )}
          </>
        )}
        {article.famille === "actionneur" && (
          <>
            <Field label="Commande">
              <Select value={f.commande} onChange={set("commande")}>
                <option value="on_off">on / off</option>
                <option value="pwm">pwm</option>
              </Select>
            </Field>
            <Field label="Puissance (W)">
              <Input value={f.puissance_w} onChange={set("puissance_w")} inputMode="decimal" />
            </Field>
          </>
        )}
        {erreur && (
          <div className="col-span-2">
            <ErrorBox error={erreur} />
          </div>
        )}
        <Button type="submit" className="col-span-2 justify-self-end" disabled={enCours}>
          Poser
        </Button>
      </form>
    </Dialog>
  );
}
