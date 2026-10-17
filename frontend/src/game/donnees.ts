// Data of the game view: the same resources as the classic UI, read with TanStack Query
// (docs/13 §1, §7), or a demonstration file without backend (`/jeu?demo=1`, docs/13 §8).
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import {
  useActionneurs,
  useAlertes,
  useCameras,
  useCapteurs,
  useCoherence,
  useConsommation,
  useCuves,
  useDecisions,
  useNoeuds,
  useSerres,
  useZones,
} from "@/api/hooks";
import type { Consommation, Tableau, ZonePlan } from "@/api/types";
import type { LiveEvent } from "@/live/LiveProvider";
import type { Donnees } from "./monde";

export interface Source {
  donnees: Donnees | null;
  conso?: Consommation;
  chargement: boolean;
  erreur: unknown;
  lectureSeule: boolean;
}

export function useDonneesApi(construction: boolean): Source {
  const serres = useSerres();
  const zones = useZones();
  const ids = (zones.data ?? []).map((z) => z.id);
  const plans = useQueries({
    queries: ids.map((id) => ({ queryKey: ["plan", id], queryFn: () => api<ZonePlan>(`/zones/${id}/plan`) })),
  });
  const tableaux = useQueries({
    queries: ids.map((id) => ({ queryKey: ["tableau", id], queryFn: () => api<Tableau>(`/zones/${id}/tableau`), refetchInterval: 60_000 })),
  });
  const actionneurs = useActionneurs();
  const capteurs = useCapteurs();
  const cameras = useCameras();
  const cuves = useCuves();
  const noeuds = useNoeuds();
  const alertes = useAlertes({ actives: true });
  const propositions = useDecisions({ statut: "proposee" });
  const conso = useConsommation({ periode: "jour" });
  const coherence = useCoherence();

  const bases = [serres, zones, actionneurs, capteurs, cameras];
  // first load only: a zone added later must not unmount the game while its plan loads
  const chargement = bases.some((q) => q.isLoading) || (ids.length > 0 && plans.every((q) => !q.data));
  const erreur = bases.find((q) => q.error)?.error ?? null;
  const donnees: Donnees | null =
    chargement || erreur
      ? null
      : {
          serre: serres.data?.[0] ?? null,
          zones: zones.data ?? [],
          plans: plans.map((q) => q.data).filter((p): p is ZonePlan => !!p),
          actionneurs: actionneurs.data ?? [],
          capteurs: capteurs.data ?? [],
          cameras: cameras.data ?? [],
          cuves: cuves.data ?? [],
          noeuds: noeuds.data ?? [],
          tableaux: Object.fromEntries(ids.map((id, i) => [id, tableaux[i]?.data])),
          alertes: alertes.data ?? [],
          propositions: propositions.data ?? [],
          avertissements: construction ? [...(coherence.data?.erreurs ?? []), ...(coherence.data?.avertissements ?? [])] : [],
        };
  return { donnees, conso: conso.data, chargement, erreur, lectureSeule: false };
}

export interface Demo {
  donnees: Donnees;
  conso?: Consommation;
  /** Events replayed in a loop, `t` seconds after the start. */
  evenements: { t: number; evenement: LiveEvent }[];
}

const BASE = import.meta.env.BASE_URL ?? "/";

/** File of an offline demonstration: "1" the hand-made one, a name the frozen history of
 * that scenario (`sim --scenario <nom> --figer`, copied by `make scenario-figer`). */
export function fichierDemo(nom: string): string {
  return nom === "1" || !/^[a-z0-9_-]+$/.test(nom) ? "demo/serre-demo.json" : `demo/scenario-${nom}.json`;
}

export function useDonneesDemo(nom = "1"): Source & { evenements: Demo["evenements"] } {
  const q = useQuery({
    queryKey: ["jeu", "demo", nom],
    queryFn: async () => {
      const r = await fetch(`${BASE}${fichierDemo(nom)}`);
      if (!r.ok) throw new Error(`${fichierDemo(nom)} : ${r.status} (make scenario-figer NOM=${nom})`);
      return (await r.json()) as Demo;
    },
    staleTime: Infinity,
  });
  return {
    donnees: q.data?.donnees ?? null,
    conso: q.data?.conso,
    chargement: q.isLoading,
    erreur: q.error,
    lectureSeule: true,
    evenements: q.data?.evenements ?? [],
  };
}
