// Replay of a period (docs/13 §5): the action tree (`GET /actions/arbre`) and the
// measurements (`GET /mesures`) become timed events fed to the same task queue, with a
// replay clock. Routines are aggregated in the tree: only exceptional, safety and manual
// decisions are replayed one by one, with their actions (actuator on from start to end).
import type { Mesures, TreeNode } from "@/api/types";
import type { LiveEvent } from "@/live/LiveProvider";

export interface EvenementDate {
  ts: number;
  evenement: LiveEvent;
}

export interface PeriodeOn {
  zone: string;
  type: string;
  debut: number;
  fin: number;
}

export interface Chronologie {
  debut: number;
  fin: number;
  evenements: EvenementDate[];
  actions: PeriodeOn[];
  /** Zone → series of air humidity and temperature [ts ms, value]. */
  series: Record<string, { humidite?: [number, number][]; temperature?: [number, number][] }>;
}

const t = (iso?: string | null) => (iso ? new Date(iso).getTime() : NaN);

export function chronologie(arbre: TreeNode, mesures: Mesures[] = []): Chronologie {
  const evenements: EvenementDate[] = [];
  const actions: PeriodeOn[] = [];
  const debut = t(arbre.debut as string | undefined);
  const fin = t(arbre.fin as string | undefined);
  for (const zone of arbre.children ?? []) {
    for (const groupe of zone.children ?? []) {
      const type = groupe.id.split("/")[1];
      if (type === "routine") continue;
      for (const d of groupe.children ?? []) {
        if (d.type !== "decision" || !d.ts) continue;
        const enfants = d.children ?? [];
        evenements.push({
          ts: t(d.ts),
          evenement: {
            kind: "decision",
            zone: zone.id,
            subject: d.id,
            payload: {
              id: d.id,
              type,
              statut: d.statut === "proposee" ? "proposee" : "executee",
              regle: { id: d.regle },
              explication: d.resume,
              emplacements: enfants.filter((a) => a.cible?.startsWith("plante:")).map((a) => a.cible!.split(":")[1]),
              ordres: enfants.filter((a) => a.cible).map((a) => ({ cible: a.cible!, action: "on" })),
            },
          },
        });
        for (const a of enfants) {
          if (!a.cible?.startsWith("actionneur:") || !a.ts_debut) continue;
          const type = a.cible.split(":")[1];
          const d0 = t(a.ts_debut);
          const d1 = a.ts_fin ? t(a.ts_fin) : d0 + 60_000;
          actions.push({ zone: zone.id, type, debut: d0, fin: d1 });
          evenements.push({ ts: d0, evenement: { kind: "etat", zone: zone.id, subject: type, payload: { action: "on" } } });
          evenements.push({ ts: d1, evenement: { kind: "etat", zone: zone.id, subject: type, payload: { action: "off" } } });
        }
      }
    }
  }
  const series: Chronologie["series"] = {};
  for (const m of mesures)
    for (const s of m.series) {
      if (s.emplacement || (s.type !== "humidite" && s.type !== "temperature")) continue;
      (series[m.zone] ??= {})[s.type] = s.points.map(([ts, v]) => [t(ts), v]);
    }
  evenements.sort((a, b) => a.ts - b.ts);
  return { debut, fin, evenements, actions, series };
}

/** Actuators on at time `ts` ("zone:type"). */
export function actifsA(c: Chronologie, ts: number): Set<string> {
  return new Set(c.actions.filter((a) => a.debut <= ts && ts < a.fin).map((a) => `${a.zone}:${a.type}`));
}

/** Last value of a series at time `ts` (null before the first point). */
export function valeurA(points: [number, number][] | undefined, ts: number): number | null {
  if (!points?.length || ts < points[0][0]) return null;
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (points[mid][0] <= ts) lo = mid;
    else hi = mid - 1;
  }
  return points[lo][1];
}

/** Events of (from, to]: what the replay clock passed over since the last frame. */
export function entre(c: Chronologie, de: number, a: number): EvenementDate[] {
  return c.evenements.filter((e) => e.ts > de && e.ts <= a);
}
