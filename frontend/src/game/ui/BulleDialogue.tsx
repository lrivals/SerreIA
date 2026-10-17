// Inspection bubble (docs/13 §6): stats of a plant, a hydro station, an actuator, a sensor
// or a camera, in a pixel dialog whose title types itself like in a game. Gauges compare the
// current value with the setpoint range; an icon (✔ ⚠ ✖) doubles the colour.
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Consommation, EmplacementPlan, Tuile } from "@/api/types";
import { ACTUATOR_LABELS, fmtDateTime, fmtDuration, fmtNum, SENSOR_LABELS } from "@/lib/format";
import { coeurs, spritePlante } from "../mapping";
import { groupeCapteurs, type Donnees, type Ref } from "../monde";
import { SpriteIcone } from "./SpriteIcone";

const ICONE: Record<Tuile["statut"], { mark: string; couleur: string; label: string }> = {
  ok: { mark: "✔", couleur: "var(--px-green)", label: "dans la plage" },
  attention: { mark: "⚠", couleur: "#c9922a", label: "hors plage" },
  alerte: { mark: "✖", couleur: "var(--px-red)", label: "alerte" },
  inconnu: { mark: "·", couleur: "#8a7a66", label: "pas de consigne" },
};

export function Jauge({ t }: { t: Pick<Tuile, "type" | "valeur" | "unite" | "plage" | "statut"> }) {
  const i = ICONE[t.statut];
  const [lo, hi] = t.plage ?? [t.valeur * 0.5, t.valeur * 1.5 || 1];
  const marge = (hi - lo) * 0.5 || 1;
  const frac = Math.max(0.03, Math.min(1, (t.valeur - (lo - marge)) / (hi + marge - (lo - marge))));
  return (
    <div className="grid grid-cols-[6.5rem_1fr_auto_1.2rem] items-center gap-2 text-[9px]" data-testid={`jauge-${t.type}`}>
      <span>{SENSOR_LABELS[t.type] ?? t.type}</span>
      <div className="px-gauge" role="meter" aria-valuenow={t.valeur} aria-valuemin={lo - marge} aria-valuemax={hi + marge} aria-label={SENSOR_LABELS[t.type] ?? t.type}>
        <span style={{ width: `${frac * 100}%`, background: i.couleur }} />
      </div>
      <span className="whitespace-nowrap">
        {fmtNum(t.valeur, t.type === "ph" || t.type === "ec" ? 2 : 1)} {t.unite}
        {t.plage && <span className="opacity-70"> ({fmtNum(t.plage[0])}–{fmtNum(t.plage[1])})</span>}
      </span>
      <span style={{ color: i.couleur }} title={i.label} aria-label={i.label}>
        {i.mark}
      </span>
    </div>
  );
}

function TexteDefilant({ texte, reduire }: { texte: string; reduire: boolean }) {
  const [n, setN] = useState(reduire ? texte.length : 0);
  useEffect(() => {
    if (reduire) return void setN(texte.length);
    setN(0);
    const id = window.setInterval(() => setN((k) => (k >= texte.length ? (window.clearInterval(id), k) : k + 1)), 18);
    return () => window.clearInterval(id);
  }, [texte, reduire]);
  return (
    <span aria-label={texte}>
      <span aria-hidden>{texte.slice(0, n)}</span>
    </span>
  );
}

export interface ActionsBulle {
  onFermer: () => void;
  onFiche?: (e: EmplacementPlan) => void;
  onAgent?: (message: string) => void;
  onCommande?: (actionneurId: string) => void;
  reduire?: boolean;
  lectureSeule?: boolean;
}

export function BulleDialogue({
  cible,
  donnees,
  conso,
  ...actions
}: { cible: Ref; donnees: Donnees; conso?: Consommation } & ActionsBulle) {
  const contenu = contenuBulle(cible, donnees, conso, actions);
  if (!contenu) return null;
  return (
    <div role="dialog" aria-label={contenu.titre} className="px-panel px-font px-pop w-[min(560px,calc(100vw-24px))] p-2 text-[10px]">
      <div className="flex items-start gap-3">
        {contenu.icone}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-[11px]">
              <TexteDefilant texte={contenu.titre} reduire={!!actions.reduire} />
            </h2>
            {contenu.coeurs != null && <Coeurs n={contenu.coeurs} />}
          </div>
          {contenu.sousTitre && <p className="mt-1 opacity-80">{contenu.sousTitre}</p>}
        </div>
      </div>
      <hr className="my-2 border-t-2 border-dashed border-[var(--px-soil)] opacity-50" />
      <div className="flex flex-col gap-1.5">{contenu.corps}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {contenu.boutons}
        <button className="px-btn" onClick={actions.onFermer}>
          Fermer
        </button>
      </div>
    </div>
  );
}

function Coeurs({ n }: { n: number }) {
  return (
    <span className="whitespace-nowrap text-[11px] text-[var(--px-red)]" aria-label={`santé ${n} sur 5`} title="score décoratif : le détail est en dessous">
      {"❤".repeat(n)}
      <span className="opacity-40">{"♡".repeat(5 - n)}</span>
    </span>
  );
}

interface Contenu {
  titre: string;
  sousTitre?: string;
  icone?: ReactNode;
  coeurs?: number;
  corps: ReactNode;
  boutons?: ReactNode;
}

const ligne = (k: string, v: ReactNode) => (
  <p key={k}>
    <span className="opacity-70">{k} : </span>
    {v}
  </p>
);

export function contenuBulle(cible: Ref, d: Donnees, conso: Consommation | undefined, a: ActionsBulle): Contenu | null {
  switch (cible.genre) {
    case "emplacement": {
      const plan = d.plans.find((p) => p.emplacements.some((e) => e.id === cible.id));
      const e = plan?.emplacements.find((x) => x.id === cible.id);
      if (!plan || !e) return null;
      const t = d.tableaux[e.zone_id];
      const tuiles = (t?.mesures ?? []).filter(
        (m) => (m.emplacement === e.id || !m.emplacement) && ["temperature", "humidite", "humidite_sol", "lux", "co2"].includes(m.type),
      );
      const p = e.plante;
      const ecarts = tuiles.filter((x) => x.statut === "alerte").length;
      const derniere = d.propositions.find((x) => x.emplacements.includes(e.id));
      const jours = p?.date_plantation ? Math.round((Date.now() - new Date(p.date_plantation).getTime()) / 86_400_000) : null;
      return {
        titre: p ? `${capitale(p.espece)}${p.variete ? ` « ${p.variete} »` : ""} · ${e.id}` : `Emplacement ${e.id}`,
        sousTitre: p
          ? [p.stade, jours != null ? `plantée il y a ${jours} j` : null, p.recette_id ? `recette ${p.recette_id}` : "sans recette", p.etat_sante.replace("_", " ")]
              .filter(Boolean)
              .join(" · ")
          : `${e.mode_culture} · ${e.contenant?.type ?? "sans contenant"} · vide`,
        icone: p ? <SpriteIcone frame={spritePlante(p).frame} zoom={1} label={p.espece} /> : undefined,
        coeurs: p ? coeurs(p.etat_sante, e.vision?.score_anomalie, ecarts) : undefined,
        corps: (
          <>
            {tuiles.length ? tuiles.map((x) => <Jauge key={`${x.type}${x.emplacement}`} t={x} />) : <p className="opacity-70">pas de mesure récente</p>}
            {e.vision && ligne("👁 Vision", `${fmtDateTime(e.vision.ts)} : ${e.vision.classe} ${fmtNum(e.vision.classe_conf, 2)} (${e.vision.sante})`)}
            {derniere && ligne("⚙ À valider", derniere.explication)}
          </>
        ),
        boutons: (
          <>
            {a.onFiche && (
              <button className="px-btn" onClick={() => a.onFiche!(e)}>
                ▶ Fiche
              </button>
            )}
            <Link className="px-btn" to={`/decisions?emplacement=${e.id}&zone=${e.zone_id}`}>
              Décisions
            </Link>
            {a.onAgent && (
              <button className="px-btn" onClick={() => a.onAgent!(`À propos de ${e.id}${p ? ` (${p.espece}, ${p.stade}, ${p.etat_sante})` : ""} : `)}>
                Demander à l'agent
              </button>
            )}
          </>
        ),
      };
    }
    case "cuve": {
      const zone = d.zones.find((z) => z.cuve_id === cible.id);
      const t = zone ? d.tableaux[zone.id] : undefined;
      const tuiles = (t?.mesures ?? []).filter((m) => ["ph", "ec", "temp_eau", "niveau_cuve"].includes(m.type));
      const pompes = d.actionneurs.filter((x) => x.zone_id === zone?.id && x.type.startsWith("pompe"));
      const eau = Object.values(conso?.actionneurs ?? {}).filter((x) => x.zone === zone?.id && x.type.startsWith("pompe"));
      return {
        titre: `Station hydro · ${cible.id}`,
        sousTitre: zone ? `zone ${zone.id}${zone.nom ? ` (${zone.nom})` : ""}` : undefined,
        corps: (
          <>
            {tuiles.map((x) => (
              <Jauge key={x.type} t={x} />
            ))}
            {pompes.map((x) => ligne(ACTUATOR_LABELS[x.type] ?? x.type, `${etatTexte(x.etat?.action, x.etat?.valeur)} depuis ${fmtDateTime(x.etat?.ts)}`))}
            {eau.length > 0 &&
              ligne(
                "Consommé aujourd'hui",
                eau
                  .map((x) => (x.ml ? `${fmtNum(x.ml, 0)} mL (${ACTUATOR_LABELS[x.type] ?? x.type})` : x.litres ? `${fmtNum(x.litres)} L` : null))
                  .filter(Boolean)
                  .join(" · ") || "—",
              )}
          </>
        ),
      };
    }
    case "actionneur": {
      const x = d.actionneurs.find((y) => y.id === cible.id);
      if (!x) return null;
      const c = Object.values(conso?.actionneurs ?? {}).find((y) => y.zone === x.zone_id && y.type === x.type);
      const depuis = x.etat ? (Date.now() - new Date(x.etat.ts).getTime()) / 1000 : null;
      return {
        titre: `${ACTUATOR_LABELS[x.type] ?? x.type} · ${x.id}`,
        sousTitre: `zone ${x.zone_id} · nœud ${x.noeud} · ${x.commande}${x.puissance_w ? ` · ${x.puissance_w} W` : ""}`,
        corps: (
          <>
            {ligne("État", `${etatTexte(x.etat?.action, x.etat?.valeur)}${depuis != null ? ` depuis ${fmtDuration(depuis)}` : ""}`)}
            {c && ligne("Aujourd'hui", [`${fmtNum(c.heures_on)} h en marche`, c.kwh != null && `${fmtNum(c.kwh, 2)} kWh`, c.litres != null && `${fmtNum(c.litres)} L`, c.ml != null && `${fmtNum(c.ml, 0)} mL`].filter(Boolean).join(" · "))}
            {x.duree_max_s && ligne("Durée max", fmtDuration(x.duree_max_s))}
          </>
        ),
        boutons:
          a.onCommande && !a.lectureSeule ? (
            <button className="px-btn" onClick={() => a.onCommande!(x.id)}>
              Commande manuelle
            </button>
          ) : null,
      };
    }
    case "capteur": {
      const g = groupeCapteurs(d.capteurs).find((y) => y.id === cible.id);
      if (!g) return null;
      const noeud = d.noeuds.find((n) => n.id === g.canaux[0].noeud);
      return {
        titre: `Capteur ${g.id}`,
        sousTitre: `nœud ${g.canaux[0].noeud} · ${noeud?.status === "offline" ? "hors ligne" : "en ligne"}${g.canaux[0].modele ? ` · ${g.canaux[0].modele}` : ""}`,
        corps: g.canaux.map((x) => (
          <p key={x.id}>
            <span className="opacity-70">{SENSOR_LABELS[x.type] ?? x.type} : </span>
            {x.derniere_mesure ? `${fmtNum(x.derniere_mesure.valeur, 2)} (${fmtDateTime(x.derniere_mesure.ts)})` : "—"}
            {x.etalonnage?.date && (
              <span style={{ color: x.etalonnage_en_retard ? "#c9922a" : undefined }}>
                {" "}
                · étalonné le {x.etalonnage.date}
                {x.etalonnage_en_retard && " ⚠ à refaire"}
              </span>
            )}
          </p>
        )),
        boutons: (
          <Link className="px-btn" to={`/equipements?zone=${g.canaux[0].zone}`}>
            Équipements
          </Link>
        ),
      };
    }
    case "camera": {
      const c = d.cameras.find((y) => y.id === cible.id);
      if (!c) return null;
      return {
        titre: `Caméra ${c.id}`,
        sousTitre: `zone ${c.zone_id}`,
        corps: (
          <>
            {ligne("Dernière image", c.derniere_image ? fmtDateTime(c.derniere_image.ts) : "—")}
            {ligne("Emplacements visibles", c.regions.map((r) => r.emplacement_id).join(", ") || "aucun")}
          </>
        ),
        boutons: (
          // camera regions are edited on the real image, in the classic view (docs/13 §4)
          <Link className="px-btn" to={`/constructeur?zone=${c.zone_id}&regions=${c.id}`}>
            Éditer les régions
          </Link>
        ),
      };
    }
  }
}

const etatTexte = (action?: string, valeur?: number | null) =>
  !action ? "inconnu" : action === "pwm" ? `pwm ${fmtNum(valeur ?? 0, 0)} %` : action === "on" ? "en marche" : "arrêté";

const capitale = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
