// Builder inventory (docs/13 §4): objects by family, dragged onto a free tile of the game.
// Sensors and actuators are filtered by the growing mode of the chosen zone (docs/09 §3).
import { useState } from "react";
import { useRecettes } from "@/api/hooks";
import type { Zone, ZonePlan } from "@/api/types";
import { ACTUATOR_LABELS, SENSOR_LABELS } from "@/lib/format";
import { CATALOGUE } from "../catalogue";
import { familleCapteur, spriteCamera, spriteCapteur, spriteContenant, spritePlante, animActionneur } from "../mapping";
import { SpriteIcone } from "./SpriteIcone";

export const DND_JEU = "application/x-serreia-jeu";

export type Article =
  | { famille: "contenant"; type: string; mode: string }
  | { famille: "plante"; espece: string }
  | { famille: "capteur"; type: string }
  | { famille: "actionneur"; type: string }
  | { famille: "camera" };

const CONTENANTS: { type: string; mode: string; label: string }[] = [
  { type: "pot", mode: "substrat", label: "pot" },
  { type: "jardiniere", mode: "substrat", label: "jardinière" },
  { type: "sac_de_culture", mode: "substrat", label: "sac" },
  { type: "godet", mode: "substrat", label: "godet" },
  { type: "pleine_terre", mode: "terre", label: "pleine terre" },
  { type: "canal_NFT", mode: "hydro_nft", label: "canal NFT" },
  { type: "bac_DWC", mode: "hydro_dwc", label: "bac DWC" },
];
const CAPTEURS_HYDRO = ["ph", "ec", "temp_eau", "niveau_cuve"];
const CAPTEURS = ["temperature", "humidite", "co2", "lux", "pression", "presence", "humidite_sol", ...CAPTEURS_HYDRO];
const ACTIONNEURS_HYDRO = ["pompe_nutri", "pompe_ph_down", "pompe_nutri_a", "pompe_nutri_b"];
const ACTIONNEURS = ["ventilo", "led", "chauffage", "brumisateur", ...ACTIONNEURS_HYDRO];

export function Inventaire({
  zones,
  plans,
  zone,
  onZone,
  onGlisser,
}: {
  zones: Zone[];
  plans: ZonePlan[];
  zone: string | null;
  onZone: (z: string) => void;
  onGlisser: (a: Article | null) => void;
}) {
  const { data: recettes } = useRecettes();
  const [famille, setFamille] = useState<"structure" | "contenant" | "plante" | "capteur" | "actionneur">("contenant");
  const hydro = (plans.find((p) => p.zone.id === zone)?.emplacements ?? []).some((e) => e.mode_culture !== "terre" && e.mode_culture !== "substrat");
  const especes = [...new Set([...Object.keys(CATALOGUE.plantes.especes), ...(recettes ?? []).map((r) => r.espece)])].sort();

  const items: { article: Article; frame: string | null; label: string }[] =
    famille === "contenant"
      ? CONTENANTS.map((c) => ({
          article: { famille: "contenant", type: c.type, mode: c.mode },
          frame: spriteContenant({ type: c.type, materiau: null }, c.mode),
          label: c.label,
        }))
      : famille === "plante"
        ? especes.map((e) => ({ article: { famille: "plante", espece: e }, frame: spritePlante({ espece: e, stade: "croissance", etat_sante: "sain" }).frame, label: e }))
        : famille === "capteur"
          ? CAPTEURS.filter((t) => hydro || !CAPTEURS_HYDRO.includes(t)).map((t) => ({
              article: { famille: "capteur", type: t },
              frame: spriteCapteur(familleCapteur(t), true).frame,
              label: SENSOR_LABELS[t] ?? t,
            }))
          : famille === "actionneur"
            ? ACTIONNEURS.filter((t) => hydro || !ACTIONNEURS_HYDRO.includes(t)).map((t) => ({
                article: { famille: "actionneur", type: t },
                frame: animActionneur({ type: t, etat: null })?.frames[0] ?? null,
                label: ACTUATOR_LABELS[t] ?? t,
              }))
            : [{ article: { famille: "camera" }, frame: spriteCamera(), label: "caméra" }];

  return (
    <aside className="px-panel px-font flex w-[230px] flex-col gap-2 p-2 text-[9px]" aria-label="Inventaire">
      <div className="flex items-center justify-between gap-2 text-[10px]">
        <span>Inventaire</span>
        <select className="border-2 border-[var(--px-outline)] bg-[var(--px-cream)] px-1 text-[9px]" value={zone ?? ""} onChange={(e) => onZone(e.target.value)} aria-label="Zone">
          {zones.map((z) => (
            <option key={z.id} value={z.id}>
              {z.id}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap gap-1" role="tablist">
        {(
          [
            ["structure", "Structure"],
            ["contenant", "Contenants"],
            ["plante", "Plantes"],
            ["capteur", "Capteurs"],
            ["actionneur", "Actionn."],
          ] as const
        ).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={famille === k} aria-pressed={famille === k} className="px-btn !px-1.5 !py-1 !text-[8px]" onClick={() => setFamille(k)}>
            {l}
          </button>
        ))}
      </div>
      {famille === "structure" && <p className="opacity-80">Outil « Zone » : tracer un rectangle sur une partie libre. Caméra : glisser l'icône.</p>}
      {!hydro && (famille === "capteur" || famille === "actionneur") && (
        <p className="opacity-70">zone sans hydroponie : capteurs et pompes hydro masqués</p>
      )}
      <ul className="grid max-h-[50vh] grid-cols-3 gap-1 overflow-y-auto">
        {items.map((it) => (
          <li key={JSON.stringify(it.article)}>
            <div
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(DND_JEU, JSON.stringify(it.article));
                e.dataTransfer.effectAllowed = "copy";
                onGlisser(it.article);
              }}
              onDragEnd={() => onGlisser(null)}
              className="flex cursor-grab flex-col items-center gap-1 border-2 border-transparent p-1 text-center hover:border-[var(--px-soil)]"
              title={`Glisser sur une case libre : ${it.label}`}
            >
              <SpriteIcone frame={it.frame} className="max-h-12" />
              <span className="line-clamp-2 break-all">{it.label}</span>
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
