// Builder gestures → existing CRUD calls (docs/13 §4), with a local undo / redo stack.
// Nothing reaches the Pi before "Publier la configuration", but objects are saved in the
// database as they are placed.
import { useCallback, useState } from "react";
import { api } from "@/api/client";
import {
  useDeleteActionneur,
  useDeleteCamera,
  useDeleteCapteur,
  useDeleteEmplacement,
  useDeplacerPlante,
  useUpdateActionneur,
  useUpdateCamera,
  useUpdateCapteur,
  useUpdateCuve,
  useUpdateEmplacement,
} from "@/api/hooks";
import type { Disposition, Schemas } from "@/api/types";
import { gridCode } from "@/lib/especes";
import { useQueryClient } from "@tanstack/react-query";
import type { Article } from "./ui/Inventaire";
import { caseLibre, entiteA, groupeCapteurs, type Donnees, type Monde, type Ref, type ZoneMonde } from "./monde";

export type Dialogue =
  | { kind: "emplacement"; zone: string; code: string; rangee: number; colonne: number; contenant: string; mode: string; disposition: Disposition }
  | { kind: "plante"; emplacement: string; espece: string }
  | { kind: "equipement"; article: Extract<Article, { famille: "capteur" | "actionneur" | "camera" }>; zone: string; disposition: Disposition }
  | { kind: "zone"; disposition: Disposition }
  | { kind: "confirmer"; texte: string; executer: () => Promise<void> }
  | null;

interface Operation {
  libelle: string;
  defaire: () => Promise<unknown>;
  refaire?: () => Promise<unknown>;
}

/** Grid code of a tile from the default layout of the zone (columns every 2 tiles, rows
 * every 3), so that the classic plan shows the emplacement at the same place. */
export function codeCase(z: Pick<ZoneMonde, "x" | "y">, x: number, y: number) {
  const rangee = Math.max(1, Math.round((y - z.y - 3) / 3) + 1);
  const colonne = Math.max(1, Math.round((x - z.x - 1) / 2) + 1);
  return { code: gridCode(rangee, colonne), rangee, colonne };
}

export function useConstruction(monde: Monde | null, donnees: Donnees | null) {
  const qc = useQueryClient();
  const [dialogue, setDialogue] = useState<Dialogue>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [passe, setPasse] = useState<Operation[]>([]);
  const [futur, setFutur] = useState<Operation[]>([]);
  const majEmp = useUpdateEmplacement();
  const supEmp = useDeleteEmplacement();
  const deplacer = useDeplacerPlante();
  const majAct = useUpdateActionneur();
  const supAct = useDeleteActionneur();
  const majCapt = useUpdateCapteur();
  const supCapt = useDeleteCapteur();
  const majCam = useUpdateCamera();
  const supCam = useDeleteCamera();
  const majCuve = useUpdateCuve();

  const enregistrer = useCallback((op: Operation) => {
    setPasse((p) => [...p.slice(-49), op]);
    setFutur([]);
  }, []);

  const tout = () => {
    for (const k of ["plan", "plantes", "capteurs", "actionneurs", "cameras", "cuves", "zones", "config"]) qc.invalidateQueries({ queryKey: [k] });
  };

  const annuler = async () => {
    const op = passe[passe.length - 1];
    if (!op) return;
    setPasse((p) => p.slice(0, -1));
    try {
      await op.defaire();
      if (op.refaire) setFutur((f) => [...f, op]);
      setMessage(`annulé : ${op.libelle}`);
    } catch (e) {
      setMessage(`impossible d'annuler « ${op.libelle} » : ${String((e as Error).message ?? e)}`);
    }
    tout();
  };

  const retablir = async () => {
    const op = futur[futur.length - 1];
    if (!op?.refaire) return;
    setFutur((f) => f.slice(0, -1));
    await op.refaire();
    setPasse((p) => [...p, op]);
    tout();
  };

  /** Inventory item dropped on a tile. */
  const depot = (article: Article, x: number, y: number) => {
    if (!monde) return;
    setMessage(null);
    const cible = entiteA(monde, x, y);
    if (article.famille === "plante") {
      if (cible?.ref.genre !== "emplacement") return setMessage("Posez d'abord un contenant, puis la plante dessus.");
      const e = donnees?.plans.flatMap((p) => p.emplacements).find((x) => x.id === cible.ref.id);
      if (e?.plante) return setMessage(`${e.id} a déjà une plante (${e.plante.espece}).`);
      return setDialogue({ kind: "plante", emplacement: cible.ref.id, espece: article.espece });
    }
    const libre = caseLibre(monde, x, y);
    if (!libre.ok || !libre.zone) return setMessage(`Case interdite : ${libre.raison}.`);
    const disposition = { x, y };
    if (article.famille === "contenant") {
      const c = codeCase(libre.zone, x, y);
      return setDialogue({ kind: "emplacement", zone: libre.zone.id, ...c, contenant: article.type, mode: article.mode, disposition });
    }
    setDialogue({ kind: "equipement", article, zone: libre.zone.id, disposition });
  };

  /** Object dragged to another tile: a plant onto an empty container is moved
   * (`POST /plantes/{id}/deplacer`), any other object only changes its `disposition`. */
  const deplace = async (ref: Ref, x: number, y: number) => {
    if (!monde || !donnees) return;
    setMessage(null);
    const source = monde.entites.find((e) => e.ref.genre === ref.genre && e.ref.id === ref.id);
    if (!source) return;
    const cible = entiteA(monde, x, y);
    const emps = donnees.plans.flatMap((p) => p.emplacements);
    if (ref.genre === "emplacement" && cible?.ref.genre === "emplacement") {
      const de = emps.find((e) => e.id === ref.id);
      const vers = emps.find((e) => e.id === cible.ref.id);
      if (!de?.plante) return setMessage(`${ref.id} est vide : rien à déplacer.`);
      if (vers?.plante) return setMessage(`${vers.id} a déjà une plante.`);
      const plante = de.plante.id;
      await deplacer.mutateAsync({ id: plante, emplacement: cible.ref.id });
      return enregistrer({
        libelle: `déplacer ${plante} vers ${cible.ref.id}`,
        defaire: () => deplacer.mutateAsync({ id: plante, emplacement: ref.id }),
        refaire: () => deplacer.mutateAsync({ id: plante, emplacement: cible.ref.id }),
      });
    }
    const libre = caseLibre(monde, x, y, ref);
    if (!libre.ok) return setMessage(`Case interdite : ${libre.raison}.`);
    if (libre.zone?.id !== source.zone && ref.genre !== "capteur")
      return setMessage("Un objet ne change pas de zone ici : supprimez-le et reposez-le dans l'autre zone.");
    const avant = ancienneDisposition(donnees, ref);
    const apres: Disposition = { ...(avant ?? {}), x, y };
    const poser = (d: Disposition | null) => patchDisposition(ref, d);
    await poser(apres);
    enregistrer({ libelle: `déplacer ${ref.id}`, defaire: () => poser(avant ?? null), refaire: () => poser(apres) });
  };

  const patchDisposition = async (ref: Ref, disposition: Disposition | null) => {
    if (ref.genre === "emplacement") return majEmp.mutateAsync({ id: ref.id, disposition });
    if (ref.genre === "actionneur") return majAct.mutateAsync({ id: ref.id, disposition });
    if (ref.genre === "camera") return majCam.mutateAsync({ id: ref.id, disposition });
    if (ref.genre === "cuve") return majCuve.mutateAsync({ id: ref.id, disposition });
    const g = groupeCapteurs(donnees?.capteurs ?? []).find((x) => x.id === ref.id);
    for (const c of g?.canaux ?? []) await majCapt.mutateAsync({ id: c.id, disposition });
  };

  /** Eraser: confirmation, then removal (undoable by re-creating the object). */
  const gomme = (ref: Ref) => {
    if (!donnees) return;
    setMessage(null);
    const emps = donnees.plans.flatMap((p) => p.emplacements);
    if (ref.genre === "emplacement") {
      const e = emps.find((x) => x.id === ref.id);
      if (!e) return;
      if (e.plante) {
        const plante = e.plante.id;
        return setDialogue({
          kind: "confirmer",
          texte: `Retirer la plante ${e.plante.espece} (${plante}) de ${e.id} ? Elle reste dans l'historique.`,
          executer: async () => {
            await deplacer.mutateAsync({ id: plante, emplacement: null });
            enregistrer({
              libelle: `retirer ${plante}`,
              defaire: () => deplacer.mutateAsync({ id: plante, emplacement: e.id }),
              refaire: () => deplacer.mutateAsync({ id: plante, emplacement: null }),
            });
          },
        });
      }
      const corps: Schemas["EmplacementIn"] = {
        zone_id: e.zone_id,
        code: e.code,
        mode_culture: e.mode_culture as Schemas["EmplacementIn"]["mode_culture"],
        rangee: e.rangee,
        colonne: e.colonne,
        contenant: e.contenant ? { type: e.contenant.type, volume_l: e.contenant.volume_l, materiau: e.contenant.materiau, drainage: e.contenant.drainage } : null,
        disposition: e.disposition ?? null,
      };
      return setDialogue({
        kind: "confirmer",
        texte: `Supprimer l'emplacement ${e.id} ?`,
        executer: async () => {
          await supEmp.mutateAsync(e.id);
          enregistrer({ libelle: `supprimer ${e.id}`, defaire: () => api("/emplacements", { body: corps }) });
        },
      });
    }
    if (ref.genre === "actionneur") {
      const a = donnees.actionneurs.find((x) => x.id === ref.id);
      if (!a) return;
      const corps = {
        id: a.id,
        zone_id: a.zone_id,
        type: a.type,
        noeud: a.noeud,
        commande: a.commande,
        puissance_w: a.puissance_w,
        debit_l_h: a.debit_l_h,
        debit_ml_min: a.debit_ml_min,
        ppfd_max: a.ppfd_max,
        duree_max_s: a.duree_max_s,
        disposition: a.disposition ?? null,
      };
      return setDialogue({
        kind: "confirmer",
        texte: `Supprimer l'actionneur ${a.id} (${a.type}) ? Le contrôleur le garde jusqu'à la prochaine publication.`,
        executer: async () => {
          await supAct.mutateAsync(a.id);
          enregistrer({ libelle: `supprimer ${a.id}`, defaire: () => api("/actionneurs", { body: corps }) });
        },
      });
    }
    if (ref.genre === "capteur") {
      const g = groupeCapteurs(donnees.capteurs).find((x) => x.id === ref.id);
      if (!g) return;
      return setDialogue({
        kind: "confirmer",
        texte: `Supprimer le capteur ${g.id} (${g.canaux.map((c) => c.type).join(", ")}) ? Ses mesures restent.`,
        executer: async () => {
          for (const c of g.canaux) await supCapt.mutateAsync(c.id);
          enregistrer({
            libelle: `supprimer ${g.id}`,
            defaire: async () => {
              for (const c of g.canaux)
                await api("/capteurs", {
                  body: {
                    noeud: c.noeud,
                    zone: c.zone,
                    type: c.type,
                    emplacement: c.emplacement,
                    materiel: c.materiel,
                    modele: c.modele,
                    etalonnage: c.etalonnage,
                    plage_min: c.plage_min,
                    plage_max: c.plage_max,
                    emplacements_couverts: c.emplacement ? null : c.emplacements_couverts,
                    disposition: c.disposition ?? null,
                  },
                });
            },
          });
        },
      });
    }
    if (ref.genre === "camera") {
      const c = donnees.cameras.find((x) => x.id === ref.id);
      if (!c) return;
      return setDialogue({
        kind: "confirmer",
        texte: `Supprimer la caméra ${c.id} et ses ${c.regions.length} région(s) ?`,
        executer: async () => {
          await supCam.mutateAsync(c.id);
          enregistrer({
            libelle: `supprimer ${c.id} (sans ses régions)`,
            defaire: () => api("/cameras", { body: { id: c.id, zone_id: c.zone_id, disposition: c.disposition ?? null } }),
          });
        },
      });
    }
    setMessage("La cuve est liée à une zone : elle se gère dans le constructeur classique.");
  };

  /** A zone created from the game: its rectangle is kept as its disposition. */
  const zoneCreee = (id: string, d: Disposition) =>
    enregistrer({ libelle: `créer la zone ${id}`, defaire: () => api(`/zones/${id}`, { method: "DELETE" }), refaire: () => api("/zones", { body: { id, disposition: d } }) });

  const cree = (libelle: string, chemin: string) => enregistrer({ libelle, defaire: () => api(chemin, { method: "DELETE" }) });
  const planteCreee = (id: string, emplacement: string) =>
    enregistrer({
      libelle: `planter ${id}`,
      defaire: () => deplacer.mutateAsync({ id, emplacement: null }),
      refaire: () => deplacer.mutateAsync({ id, emplacement }),
    });

  return {
    dialogue,
    setDialogue,
    message,
    setMessage,
    depot,
    deplace: (ref: Ref, x: number, y: number) => deplace(ref, x, y).catch((e) => setMessage(String((e as Error).message ?? e))),
    gomme,
    zoneCreee,
    cree,
    planteCreee,
    annuler,
    retablir,
    peutAnnuler: passe.length > 0,
    peutRetablir: futur.length > 0,
    dernier: passe[passe.length - 1]?.libelle,
  };
}

function ancienneDisposition(d: Donnees, ref: Ref): Disposition | null | undefined {
  switch (ref.genre) {
    case "emplacement":
      return d.plans.flatMap((p) => p.emplacements).find((e) => e.id === ref.id)?.disposition;
    case "actionneur":
      return d.actionneurs.find((x) => x.id === ref.id)?.disposition;
    case "camera":
      return d.cameras.find((x) => x.id === ref.id)?.disposition;
    case "cuve":
      return d.cuves.find((x) => x.id === ref.id)?.disposition;
    case "capteur":
      return groupeCapteurs(d.capteurs).find((x) => x.id === ref.id)?.disposition;
  }
}
