// "⏪ Rejouer 24 h / 7 j" (docs/13 §5): the decisions and states of the period, played in
// fast motion (×60, ×600) through the same task queue; the day and night follow the replay
// clock and the actuators show their state at that time.
import { useQueries } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api/client";
import { useArbre } from "@/api/hooks";
import type { Mesures } from "@/api/types";
import { actifsA, chronologie, entre, valeurA, type Chronologie } from "./rejeu";

export type Periode = "24h" | "7j";

export interface Rejeu {
  actif: boolean;
  periode: Periode;
  vitesse: 60 | 600;
  lecture: boolean;
  t: number;
  chrono: Chronologie | null;
  chargement: boolean;
}

export function useRejeu(zones: string[], surEvenements: (e: ReturnType<typeof entre>) => void) {
  const [actif, setActif] = useState(false);
  const [periode, setPeriode] = useState<Periode>("24h");
  const [vitesse, setVitesse] = useState<60 | 600>(60);
  const [lecture, setLecture] = useState(true);
  const [t, setTState] = useState(0);
  const tRef = useRef(0);
  const setT = (v: number) => {
    tRef.current = v;
    setTState(v);
  };
  const bornes = useMemo(() => {
    const fin = new Date();
    fin.setSeconds(0, 0);
    const debut = new Date(fin.getTime() - (periode === "24h" ? 24 : 24 * 7) * 3600_000);
    return { debut: debut.toISOString(), fin: fin.toISOString() };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periode, actif]);
  const arbre = useArbre(bornes, actif);
  const mesures = useQueries({
    queries: zones.map((zone) => ({
      queryKey: ["mesures", { zone, ...bornes, type: ["humidite", "temperature"], agregat: "moy_15min" }],
      queryFn: () => api<Mesures>("/mesures", { params: { zone, ...bornes, type: ["humidite", "temperature"], agregat: "moy_15min" } }),
      enabled: actif,
    })),
  });
  const chrono = useMemo(
    () => (arbre.data ? chronologie(arbre.data, mesures.map((m) => m.data).filter((m): m is Mesures => !!m)) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [arbre.data, ...mesures.map((m) => m.data)],
  );

  // restart from the beginning of the period
  useEffect(() => {
    if (chrono) setT(chrono.debut);
  }, [chrono]);

  const rappel = useRef(surEvenements);
  rappel.current = surEvenements;
  useEffect(() => {
    if (!actif || !lecture || !chrono) return;
    let precedent = performance.now();
    let id = 0;
    const tick = (now: number) => {
      const dt = (now - precedent) * vitesse;
      precedent = now;
      const t0 = tRef.current;
      const t1 = Math.min(chrono.fin, t0 + dt);
      tRef.current = t1;
      setT(t1);
      const evts = entre(chrono, t0, t1);
      if (evts.length) rappel.current(evts);
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [actif, lecture, chrono, vitesse]);

  const etat: Rejeu = {
    actif,
    periode,
    vitesse,
    lecture,
    t,
    chrono,
    chargement: actif && (arbre.isLoading || mesures.some((m) => m.isLoading)),
  };
  return {
    etat,
    setActif,
    setPeriode,
    setVitesse,
    setLecture,
    aller: setT,
    actifs: chrono && actif ? actifsA(chrono, t) : null,
    valeur: (zone: string, type: "humidite" | "temperature") => (chrono && actif ? valeurA(chrono.series[zone]?.[type], t) : null),
  };
}
