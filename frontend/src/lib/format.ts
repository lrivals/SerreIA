// Display formats (French, local time of the browser).

const dt = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });
const hm = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });

export const fmtDateTime = (iso?: string | null) => (iso ? dt.format(new Date(iso)) : "—");
export const fmtTime = (iso?: string | null) => (iso ? hm.format(new Date(iso)) : "—");
export const fmtDay = (iso?: string | null) => (iso ? day.format(new Date(iso)) : "—");

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function fmtDuration(seconds?: number | null): string {
  if (!seconds) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${fmtNum(seconds / 3600, 1)} h`;
}

export const SENSOR_LABELS: Record<string, string> = {
  temperature: "T° air",
  humidite: "Humidité",
  co2: "CO₂",
  lux: "Lumière",
  ph: "pH",
  ec: "EC",
  temp_eau: "T° eau",
  niveau_cuve: "Niveau cuve",
  pression: "Pression",
  presence: "Présence",
  humidite_sol: "Humidité sol",
};

export const ACTUATOR_LABELS: Record<string, string> = {
  ventilo: "Ventilation",
  chauffage: "Chauffage",
  brumisateur: "Brumisateur",
  led: "LED",
  pompe_nutri: "Pompe arrosage",
  pompe_ph_down: "Pompe pH−",
  pompe_nutri_a: "Pompe nutriment A",
  pompe_nutri_b: "Pompe nutriment B",
};

export const MODES_CULTURE = [
  "terre",
  "substrat",
  "hydro_nft",
  "hydro_dwc",
  "ebb_flow",
  "aeroponie",
] as const;

export const ETATS_SANTE = ["sain", "a_surveiller", "malade", "isolee", "retiree"] as const;
