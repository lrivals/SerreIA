// Task queue of the gardener (docs/13 §5): live events → tasks by priority. The object
// changes state as soon as the message arrives (world rebuilt from the data); the task only
// illustrates the event afterwards, it never delays it. Pure, the clock is injected.
import type { LiveEvent } from "@/live/LiveProvider";
import type { Bulle } from "../mapping";
import type { Ref } from "../monde";

export type ActionJardinier =
  | "courir"
  | "ventiler"
  | "doser"
  | "arroser"
  | "inspecter"
  | "noter"
  | "tapoter"
  | "attendre";

export interface Tache {
  cle: string; // same key = same task, counted "×n"
  priorite: 1 | 2 | 3 | 4 | 5;
  action: ActionJardinier;
  zone: string | null;
  cible: Ref | null;
  bulle: Bulle | null;
  texte: string;
  cree: number; // ms
  compteur: number;
  /** Alerts and decisions waiting for a validation are never dropped. */
  persistante: boolean;
}

export const PEREMPTION_MS = 2 * 60_000;

/** What the queue needs to know of the greenhouse to aim at an object. */
export interface Contexte {
  actionneur: (zone: string, type: string) => string | null; // actuator id
  emplacementsCamera: (camera: string) => string[];
  capteurNoeud: (noeud: string) => string | null; // sensor box of a node
}

const ACTION_ACTIONNEUR: Record<string, ActionJardinier> = {
  ventilo: "ventiler",
  led: "ventiler",
  chauffage: "ventiler",
  brumisateur: "ventiler",
  pompe_nutri: "arroser",
  pompe_ph_down: "doser",
  pompe_nutri_a: "doser",
  pompe_nutri_b: "doser",
};

type P = Record<string, unknown>;

function tache(
  t: Omit<Tache, "cle" | "compteur" | "cree" | "persistante" | "bulle" | "texte"> &
    Partial<Pick<Tache, "persistante" | "bulle" | "texte">>,
  now: number,
): Tache {
  const cle = `${t.action}|${t.zone ?? ""}|${t.cible ? `${t.cible.genre}:${t.cible.id}` : ""}`;
  return { bulle: null, texte: "", persistante: false, ...t, cle, compteur: 1, cree: now };
}

/** Tasks of one live event (none for the routine ones the objects already show). */
export function tachesDe(e: LiveEvent, ctx: Contexte, now: number): Tache[] {
  const p = (e.payload ?? {}) as P;
  const zone = e.zone;
  switch (e.kind) {
    case "alerte": {
      if (p.niveau === "critique")
        return [tache({ priorite: 1, action: "courir", zone, cible: null, bulle: "alert", texte: String(p.message ?? ""), persistante: true }, now)];
      if (p.niveau === "warning")
        return [tache({ priorite: 3, action: "noter", zone, cible: null, bulle: "alert", texte: String(p.message ?? "") }, now)];
      return [];
    }
    case "decision": {
      const type = p.type as string;
      const statut = p.statut as string;
      const regle = (p.regle as P | undefined)?.id as string | undefined;
      const ordres = (p.ordres as { cible: string; action: string }[] | undefined) ?? [];
      const emps = (p.emplacements as string[] | undefined) ?? [];
      if (statut === "proposee") {
        const act = ordres.map((o) => o.cible.split(":")).find(([g]) => g === "actionneur");
        const id = act && zone ? ctx.actionneur(zone, act[1]) : null;
        const cible: Ref | null = id ? { genre: "actionneur", id } : emps[0] ? { genre: "emplacement", id: emps[0] } : null;
        return [
          tache(
            { priorite: 3, action: "noter", zone, cible, bulle: "thinking", texte: `à valider : ${String(p.explication ?? regle ?? "")}`, persistante: true },
            now,
          ),
        ];
      }
      if (type !== "exceptionnelle" && type !== "securite" && type !== "manuelle") return [];
      const out: Tache[] = [];
      for (const o of ordres) {
        const [genre, sujet] = o.cible.split(":");
        if (genre === "actionneur" && zone) {
          const id = ctx.actionneur(zone, sujet);
          out.push(
            tache(
              { priorite: 2, action: ACTION_ACTIONNEUR[sujet] ?? "ventiler", zone, cible: id ? { genre: "actionneur", id } : null, bulle: "alert", texte: regle ?? "" },
              now,
            ),
          );
        } else if (genre === "plante")
          out.push(tache({ priorite: 2, action: "inspecter", zone, cible: { genre: "emplacement", id: sujet }, bulle: "question", texte: regle ?? "" }, now));
      }
      if (out.length === 0 && emps[0])
        out.push(tache({ priorite: 2, action: "inspecter", zone, cible: { genre: "emplacement", id: emps[0] }, bulle: "question", texte: regle ?? "" }, now));
      return out;
    }
    case "vision": {
      const dets = (p.detections as { sante: string; classe: string; classe_conf: number }[] | undefined) ?? [];
      const anormales = dets.filter((d) => d.sante === "anormal");
      if (anormales.length === 0 || !e.subject) return [];
      const camera = String(p.camera ?? e.subject);
      const texte = anormales.map((d) => `${d.classe} ${d.classe_conf.toFixed(2)}`).join(", ");
      return ctx
        .emplacementsCamera(camera)
        .slice(0, 3)
        .map((id) => tache({ priorite: 2, action: "inspecter", zone, cible: { genre: "emplacement", id }, bulle: "question", texte }, now));
    }
    case "etat": {
      const on = p.action === "on" || (p.action === "pwm" && Number(p.valeur ?? 0) > 0);
      if (!on || !zone || !e.subject) return [];
      const id = ctx.actionneur(zone, e.subject);
      if (!id) return [];
      const action = e.subject === "pompe_nutri" ? "arroser" : "attendre";
      return [tache({ priorite: 4, action, zone, cible: { genre: "actionneur", id }, texte: `${e.subject} en marche` }, now)];
    }
    case "status": {
      if (e.payload !== "offline" || !e.subject) return [];
      const id = ctx.capteurNoeud(e.subject);
      return [
        tache({ priorite: 3, action: "tapoter", zone: null, cible: id ? { genre: "capteur", id } : null, bulle: "alert", texte: `nœud ${e.subject} hors ligne` }, now),
      ];
    }
    default:
      return [];
  }
}

export class FileTaches {
  private taches: Tache[] = [];

  ajouter(t: Tache): void {
    const meme = this.taches.find((x) => x.cle === t.cle);
    if (meme) {
      meme.compteur += t.compteur;
      meme.texte = t.texte || meme.texte;
      meme.priorite = Math.min(meme.priorite, t.priorite) as Tache["priorite"];
      return;
    }
    this.taches.push({ ...t });
  }

  /** Next task to play: highest priority then oldest; stale ones dropped first. */
  suivante(now: number): Tache | null {
    this.purger(now);
    if (this.taches.length === 0) return null;
    const best = this.taches.reduce((a, b) => (b.priorite < a.priorite || (b.priorite === a.priorite && b.cree < a.cree) ? b : a));
    this.taches = this.taches.filter((x) => x !== best);
    return best;
  }

  purger(now: number): void {
    this.taches = this.taches.filter((t) => t.persistante || now - t.cree <= PEREMPTION_MS);
  }

  /** A decision validated or rejected: its "à valider" task is no longer needed. */
  retirer(pred: (t: Tache) => boolean): void {
    this.taches = this.taches.filter((t) => !pred(t));
  }

  get taille(): number {
    return this.taches.length;
  }

  apercu(): readonly Tache[] {
    return [...this.taches].sort((a, b) => a.priorite - b.priorite || a.cree - b.cree);
  }
}
