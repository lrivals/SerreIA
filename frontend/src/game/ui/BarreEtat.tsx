// Status bar of the game view (docs/13 §1): greenhouse, local time, air of each zone,
// energy and water of the day ("(estimé)" without a wattmeter), decisions to validate.
import type { Consommation } from "@/api/types";
import { fmtNum } from "@/lib/format";
import type { Donnees } from "../monde";
import type { Tache } from "../tasks/fileTaches";

export function BarreEtat({
  donnees,
  conso,
  heure,
  rejeu,
  tache,
  connecte,
  onPropositions,
  onPhone,
}: {
  donnees: Donnees;
  conso?: Consommation;
  heure: string;
  rejeu?: string | null;
  tache: Tache | null;
  connecte: boolean;
  onPropositions: () => void;
  onPhone: () => void;
}) {
  const n = donnees.propositions.length;
  const critiques = donnees.alertes.filter((a) => !a.acquittee && a.niveau === "critique").length;
  return (
    <div className="px-bar px-font flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-[9px]" role="status">
      <span className="text-[10px]">Serre « {donnees.serre?.nom ?? "—"} »</span>
      <span title={rejeu ? "heure du rejeu" : "heure locale de la serre"}>
        {rejeu ? `⏪ ${rejeu}` : `🕑 ${heure}`}
        {!rejeu && !connecte && <span className="ml-1 text-[var(--px-yellow)]">(hors ligne)</span>}
      </span>
      {donnees.zones.map((z) => {
        const t = donnees.tableaux[z.id];
        const temp = t?.mesures.find((m) => m.type === "temperature" && !m.emplacement);
        const hr = t?.mesures.find((m) => m.type === "humidite" && !m.emplacement);
        if (!temp && !hr) return null;
        return (
          <span key={z.id}>
            {z.id} {t?.jour === false ? "☾" : "☀"} {temp ? `${fmtNum(temp.valeur)} °C` : ""} {hr ? `HR ${fmtNum(hr.valeur, 0)} %` : ""}
            {hr?.statut === "alerte" || temp?.statut === "alerte" ? " ⚠" : ""}
          </span>
        );
      })}
      {conso && (
        <span title={conso.note}>
          ⚡ {fmtNum(conso.totaux.kwh, 2)} kWh · 💧 {fmtNum(conso.totaux.litres)} L{conso.estime ? " (estimé)" : ""}
        </span>
      )}
      {tache && (
        <span className="opacity-80" aria-live="polite">
          ☺ {libelleTache(tache)}
          {tache.compteur > 1 ? ` ×${tache.compteur}` : ""}
        </span>
      )}
      <span className="ml-auto flex items-center gap-2">
        {critiques > 0 && <span className="animate-pulse text-[var(--px-red)] motion-reduce:animate-none">! {critiques} alerte(s)</span>}
        {n > 0 && (
          <button className="px-btn" onClick={onPropositions}>
            ⚠ {n} décision{n > 1 ? "s" : ""} à valider
          </button>
        )}
        <button className="px-btn" onClick={onPhone} aria-haspopup="dialog">
          📱 SerrePhone
        </button>
      </span>
    </div>
  );
}

const VERBES: Record<Tache["action"], string> = {
  courir: "accourt",
  ventiler: "actionne",
  doser: "dose",
  arroser: "arrose",
  inspecter: "inspecte",
  noter: "note",
  tapoter: "vérifie",
  attendre: "surveille",
};

export const libelleTache = (t: Tache) => `${VERBES[t.action]}${t.cible ? ` ${t.cible.id}` : t.zone ? ` ${t.zone}` : ""}`;
