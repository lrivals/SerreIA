// Record of an emplacement (docs/12 §2.1): its plant (species, stage, recipe, health),
// container, growing mode, sensors and cameras; history, decisions and photos.
import { Camera as CameraIcon, History, Images, ListChecks, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  useDeleteEmplacement,
  useDeplacerPlante,
  useHistorique,
  useRecettes,
  useUpdateEmplacement,
  useUpdatePlante,
  useVision,
} from "@/api/hooks";
import type { EmplacementPlan } from "@/api/types";
import { especeIcon } from "@/lib/especes";
import { ETATS_SANTE, fmtDateTime, MODES_CULTURE } from "@/lib/format";
import { Empty, ErrorBox, Loading, SanteBadge, StatutBadge } from "./common";
import { ImageAnnotee, visionLabel } from "./ImageAnnotee";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Field, Select, Textarea } from "./ui/input";

export function FicheEmplacement({ e, onClose }: { e: EmplacementPlan; onClose: () => void }) {
  const [dialog, setDialog] = useState<"historique" | "photos" | null>(null);
  const p = e.plante;
  const updateEmp = useUpdateEmplacement();
  const deleteEmp = useDeleteEmplacement();
  const retirer = useDeplacerPlante();

  return (
    <aside className="flex flex-col gap-3 rounded-lg border bg-card p-4 text-sm" aria-label={`Emplacement ${e.id}`}>
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Emplacement {e.id}</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Fermer la fiche">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {p ? <FichePlante key={p.id} e={e} /> : <p className="text-muted-foreground">Vide : déposer une espèce de la palette sur la case.</p>}

      <div className="grid grid-cols-2 gap-2 border-t pt-3">
        <Field label="Culture">
          <Select
            value={e.mode_culture}
            onChange={(ev) => updateEmp.mutate({ id: e.id, mode_culture: ev.target.value as never })}
          >
            {MODES_CULTURE.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </Field>
        <Field label="Contenant">
          <span className="py-1.5 text-foreground">
            {e.contenant
              ? [e.contenant.type, e.contenant.volume_l && `${e.contenant.volume_l} L`, e.contenant.materiau].filter(Boolean).join(" ")
              : "—"}
          </span>
        </Field>
      </div>
      {updateEmp.error && <ErrorBox error={updateEmp.error} />}
      <div>
        <span className="text-xs font-medium text-muted-foreground">Capteurs</span>
        <p>{e.capteurs.length ? e.capteurs.join(", ") : "aucun"}</p>
      </div>
      <div>
        <span className="text-xs font-medium text-muted-foreground">Caméras</span>
        <p className="flex flex-wrap gap-2">
          {e.cameras.length
            ? e.cameras.map((c) => (
                <span key={c.id} className="flex items-center gap-1">
                  <CameraIcon className="h-3.5 w-3.5" /> {c.id} {c.region ? "(région ✓)" : "(sans région)"}
                </span>
              ))
            : "aucune"}
        </p>
        {e.vision && (
          <p className="mt-1 text-xs text-muted-foreground">
            dernière classification : {visionLabel(e.vision)} · {fmtDateTime(e.vision.ts)}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2 border-t pt-3">
        <Button size="sm" variant="outline" disabled={!p} onClick={() => setDialog("historique")}>
          <History className="h-3.5 w-3.5" /> Historique
        </Button>
        <Link to={`/decisions?emplacement=${e.id}&zone=${e.zone_id}`}>
          <Button size="sm" variant="outline">
            <ListChecks className="h-3.5 w-3.5" /> Décisions
          </Button>
        </Link>
        <Button size="sm" variant="outline" onClick={() => setDialog("photos")}>
          <Images className="h-3.5 w-3.5" /> Photos
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {p && (
          <Button size="sm" variant="ghost" onClick={() => retirer.mutate({ id: p.id, emplacement: null })}>
            Retirer la plante
          </Button>
        )}
        {!p && (
          <Button size="sm" variant="ghost" className="text-bad" onClick={() => deleteEmp.mutate(e.id, { onSuccess: onClose })}>
            <Trash2 className="h-3.5 w-3.5" /> Supprimer l'emplacement
          </Button>
        )}
      </div>
      {(deleteEmp.error || retirer.error) && <ErrorBox error={deleteEmp.error ?? retirer.error} />}

      {dialog === "historique" && p && (
        <Dialog open onOpenChange={() => setDialog(null)} title={`Historique de ${p.id}`} className="w-[min(720px,calc(100vw-32px))]">
          <HistoriquePlante plante={p.id} />
        </Dialog>
      )}
      {dialog === "photos" && (
        <Dialog open onOpenChange={() => setDialog(null)} title={`Photos de ${e.id}`} className="w-[min(900px,calc(100vw-32px))]">
          <Photos emplacement={e.id} />
        </Dialog>
      )}
    </aside>
  );
}

function FichePlante({ e }: { e: EmplacementPlan }) {
  const p = e.plante!;
  const { data: recettes } = useRecettes();
  const update = useUpdatePlante();
  const [form, setForm] = useState({ stade: p.stade, recette_id: p.recette_id ?? "", etat_sante: p.etat_sante, notes: p.notes ?? "", prioritaire: p.prioritaire });
  useEffect(() => {
    setForm({ stade: p.stade, recette_id: p.recette_id ?? "", etat_sante: p.etat_sante, notes: p.notes ?? "", prioritaire: p.prioritaire });
  }, [p]);
  const recette = recettes?.find((r) => r.id === form.recette_id);
  const dirty =
    form.stade !== p.stade ||
    form.recette_id !== (p.recette_id ?? "") ||
    form.etat_sante !== p.etat_sante ||
    form.notes !== (p.notes ?? "") ||
    form.prioritaire !== p.prioritaire;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-3xl">{especeIcon(p.espece)}</span>
        <div>
          <div className="font-medium">
            {p.espece}
            {p.variete && ` · ${p.variete}`}
          </div>
          <div className="text-xs text-muted-foreground">
            {p.id} · depuis {fmtDateTime(p.depuis)} <SanteBadge etat={p.etat_sante} />
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Recette">
          <Select value={form.recette_id} onChange={(ev) => setForm({ ...form, recette_id: ev.target.value })}>
            <option value="">—</option>
            {recettes?.filter((r) => r.espece === p.espece || r.id === form.recette_id).map((r) => (
              <option key={r.id}>{r.id}</option>
            ))}
          </Select>
        </Field>
        <Field label="Stade">
          <Select value={form.stade} onChange={(ev) => setForm({ ...form, stade: ev.target.value })}>
            {(recette ? Object.keys(recette.stades) : [form.stade]).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </Field>
        <Field label="État">
          <Select value={form.etat_sante} onChange={(ev) => setForm({ ...form, etat_sante: ev.target.value })}>
            {ETATS_SANTE.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 self-end pb-1.5 text-xs">
          <input type="checkbox" checked={form.prioritaire} onChange={(ev) => setForm({ ...form, prioritaire: ev.target.checked })} />
          prioritaire (consignes de la zone)
        </label>
      </div>
      <Field label="Notes">
        <Textarea rows={2} value={form.notes} onChange={(ev) => setForm({ ...form, notes: ev.target.value })} />
      </Field>
      {update.error && <ErrorBox error={update.error} />}
      {dirty && (
        <Button
          size="sm"
          className="self-end"
          disabled={update.isPending}
          onClick={() =>
            update.mutate({
              id: p.id,
              stade: form.stade,
              recette_id: form.recette_id || null,
              etat_sante: form.etat_sante as never,
              notes: form.notes || null,
              prioritaire: form.prioritaire,
            })
          }
        >
          Enregistrer
        </Button>
      )}
    </div>
  );
}

function HistoriquePlante({ plante }: { plante: string }) {
  const { data, isLoading, error } = useHistorique(plante);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <section>
        <h3 className="mb-1 font-medium">Emplacements</h3>
        <ul className="space-y-0.5">
          {data.affectations.map((a) => (
            <li key={a.debut}>
              <span className="font-mono">{a.emplacement}</span> : {fmtDateTime(a.debut)} → {a.fin ? fmtDateTime(a.fin) : "aujourd'hui"}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3 className="mb-1 font-medium">Santé (actions sur la plante)</h3>
        {data.actions.length === 0 ? (
          <Empty>Aucune action.</Empty>
        ) : (
          <ul className="space-y-0.5">
            {data.actions.map((a) => (
              <li key={a.ts + a.label} className="flex flex-wrap items-center gap-2">
                {fmtDateTime(a.ts)} · {a.label} <StatutBadge statut={a.resultat} />
                <Link className="font-mono text-xs text-primary hover:underline" to={`/decisions/${a.decision_id}`}>
                  {a.decision_id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="mb-1 font-medium">Classifications ({data.vision.length})</h3>
        <ul className="space-y-0.5">
          {data.vision.slice(0, 20).map((v) => (
            <li key={v.image_id + v.ts}>
              {fmtDateTime(v.ts)} · {visionLabel(v)} · santé {v.sante} ({v.sante_conf.toFixed(2)})
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Photos({ emplacement }: { emplacement: string }) {
  const { data, isLoading, error } = useVision({ emplacement, limit: 12 });
  const [gradcam, setGradcam] = useState(false);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) return <Empty>Aucune image sur les 72 dernières heures.</Empty>;
  return (
    <>
      <label className="mb-2 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={gradcam} onChange={(ev) => setGradcam(ev.target.checked)} /> Grad-CAM
      </label>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
        {data.map((v) => (
          <figure key={v.image_id + v.ts}>
            <ImageAnnotee
              imageId={v.image_id}
              gradcam={gradcam}
              annotations={[{ bbox: v.bbox, label: visionLabel(v), sain: v.sante === "sain" }]}
            />
            <figcaption className="mt-1 text-xs text-muted-foreground">{fmtDateTime(v.ts)}</figcaption>
          </figure>
        ))}
      </div>
    </>
  );
}

