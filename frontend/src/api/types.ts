// Response shapes of the API (docs/12 §3). Request bodies come from the generated schema
// (`schema.d.ts`, `npm run gen:api`); the routes return plain dicts, typed here.
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Range = [number, number];

export interface Serre {
  id: string;
  nom: string;
  fuseau: string;
  tarif_kwh: number | null;
  lux_vers_ppfd: number;
  config_version: number;
}

export interface Zone {
  id: string;
  serre_id: string;
  nom: string;
  cuve_id: string | null;
  jour_debut: string;
  presence_autorisee: { debut: string; fin: string }[] | null;
  n_emplacements?: number;
}

export interface Contenant {
  id: number;
  type: string;
  volume_l: number | null;
  materiau: string | null;
  drainage: boolean | null;
}

export interface Plante {
  id: string;
  espece: string;
  variete: string | null;
  date_semis: string | null;
  date_plantation: string | null;
  stade: string;
  recette_id: string | null;
  etat_sante: string;
  prioritaire: boolean;
  notes: string | null;
  emplacement?: string | null;
  depuis?: string;
}

export interface VisionRow {
  ts: string;
  image_id: string;
  camera: string;
  espece: string;
  espece_conf: number;
  sante: string;
  sante_conf: number;
  classe: string;
  classe_conf: number;
  bbox: [number, number, number, number] | null;
  emplacement?: string | null;
  zone?: string;
  score_anomalie?: number;
}

export interface Emplacement {
  id: string;
  zone_id: string;
  code: string;
  mode_culture: string;
  rangee: number | null;
  colonne: number | null;
  contenant_id: number | null;
}

export interface EmplacementPlan extends Emplacement {
  contenant: Contenant | null;
  plante: Plante | null;
  capteurs: string[];
  cameras: { id: string; region: number[] | null }[];
  vision: VisionRow | null;
}

export interface ZonePlan {
  zone: Zone;
  emplacements: EmplacementPlan[];
  cameras: { id: string; emplacements: string[] }[];
}

export interface Recette {
  id: string;
  espece: string;
  stades: Record<string, Record<string, unknown>>;
}

export interface Capteur {
  id: string;
  materiel: string | null;
  noeud: string;
  zone: string;
  type: string;
  emplacement: string | null;
  modele: string | null;
  cuve_id: string | null;
  etalonnage: { date?: string; methode?: string } | null;
  plage_min: number | null;
  plage_max: number | null;
  emplacements_couverts: string[];
  derniere_mesure: { ts: string; valeur: number } | null;
  etalonnage_echeance: string | null;
  etalonnage_en_retard: boolean;
}

export interface EtatActionneur {
  ts: string;
  action: string;
  valeur: number | null;
}

export interface Actionneur {
  id: string;
  zone_id: string;
  type: string;
  noeud: string;
  commande: string;
  puissance_w: number | null;
  debit_l_h: number | null;
  debit_ml_min: number | null;
  ppfd_max: number | null;
  duree_max_s: number | null;
  etat: EtatActionneur | null;
}

export interface Camera {
  id: string;
  zone_id: string;
  regions: { emplacement_id: string; bbox: [number, number, number, number] | null }[];
  derniere_image: { image_id: string; ts: string } | null;
}

export interface Noeud {
  id: string;
  status: "online" | "offline" | null;
  status_ts: string | null;
  derniere_mesure: string | null;
  zones: string[];
}

export interface Serie {
  type: string;
  emplacement: string | null;
  unite: string;
  n_mesures: number;
  min: number;
  max: number;
  moyenne: number;
  points: [string, number][];
}

export interface Mesures {
  zone: string;
  debut: string;
  fin: string;
  agregat: string;
  series: Serie[];
}

export interface Tuile {
  type: string;
  emplacement: string | null;
  valeur: number;
  unite: string;
  qualite: string;
  ts: string;
  plage: Range | null;
  statut: "ok" | "attention" | "alerte" | "inconnu";
  points: [string, number][];
}

export interface Alerte {
  id: string;
  ts: string;
  zone?: string;
  niveau: "info" | "warning" | "critique";
  message: string;
  source: string;
  acquittee?: boolean;
}

export interface DecisionSummary {
  id: string;
  ts: string;
  zone: string;
  emplacements: string[];
  niveau: string;
  origine: string;
  regle: { id: string; version: number };
  type: string;
  statut: string;
  explication: string;
  actions: string[];
  expire: string | null;
}

export interface PreuveCapteur {
  topic: string;
  agregat: string;
  valeur: number;
  unite: string;
  qualite: string;
  seuil: number | null;
  emplacement: string | null;
}

export interface PreuveVision {
  camera: string;
  image_id: string;
  modele: string;
  classe: string;
  classe_conf: number;
  sante: string;
  sante_conf: number;
  espece: string | null;
  espece_conf: number | null;
  bbox: [number, number, number, number] | null;
  emplacement: string | null;
  confirmations: number;
}

export interface ActionDetail {
  id: string;
  cible: string;
  label: string;
  resultat: string;
  commande: Record<string, unknown> | null;
  ts_debut: string;
  ts_fin: string | null;
}

export interface DecisionRecord extends DecisionSummary {
  config_version: number | null;
  preuves: {
    vision: PreuveVision[];
    capteurs: PreuveCapteur[];
    prevision: { grandeur: string; horizon: string; valeur: number; modele: string }[];
    consignes: Record<string, unknown>;
  };
  ordres: { cible: string; action: string; valeur?: number | null; duree_s?: number | null }[];
  actions_detail: ActionDetail[];
  commandes: {
    ts: string;
    actionneur: string;
    action: string;
    valeur: number | null;
    duree_s: number | null;
    source: string;
    raison: string | null;
  }[];
  estimation?: { kwh?: number; litres?: number; ml?: number };
}

export interface Tableau {
  zone: { id: string; nom: string };
  jour: boolean;
  consignes: Record<string, unknown> | null;
  mesures: Tuile[];
  actionneurs: Actionneur[];
  image: { image_id: string; ts: string; camera: string; detections: VisionRow[] } | null;
  alertes: Alerte[];
  propositions: DecisionSummary[];
}

export interface TreeNode {
  id: string;
  type: "serre" | "zone" | "groupe" | "decision" | "routine" | "action";
  label?: string;
  children?: TreeNode[];
  // decision
  ts?: string;
  niveau?: string;
  statut?: string;
  regle?: string;
  resume?: string;
  // action
  cible?: string;
  resultat?: string;
  ts_debut?: string;
  ts_fin?: string | null;
  // routine aggregate
  cycles?: number;
  [key: string]: unknown;
}

export interface ConsoActionneur {
  zone: string;
  type: string;
  heures_on: number;
  kwh?: number | null;
  litres?: number | null;
  ml?: number | null;
  cout?: number | null;
  dli?: number | null;
}

export interface Consommation {
  periode: string;
  du: string;
  au: string;
  jour_en_cours: boolean;
  totaux: { kwh: number; litres: number; ml: number; cout: number | null };
  tarif_kwh: number | null;
  actionneurs: Record<string, ConsoActionneur>;
  par_jour: {
    jour: string;
    totaux: { kwh: number; litres: number; ml: number; cout: number };
    actionneurs: Record<string, ConsoActionneur>;
  }[];
  lumiere: {
    jour: string;
    zone: string;
    dli_total: number | null;
    dli_led: number;
    dli_naturel: number | null;
    couverture: number;
  }[];
  dli_cible: Record<string, number | null>;
  estime: boolean;
  note: string;
}

export interface Coherence {
  valide: boolean;
  erreurs: string[];
  avertissements: string[];
}

export interface ConfigDiff {
  de: string;
  a: string;
  identique: boolean;
  diff: string;
}

export interface Publication {
  config_version: number;
  nouvelle: boolean;
  avertissements: string[];
  fichier: string;
}

export interface Conversation {
  id: string;
  titre: string;
  utilisateur: string;
  modele: string;
  ts_debut: string;
  ts_maj: string;
  tokens?: number;
}

export interface ConversationDetail extends Conversation {
  messages: { role: "user" | "assistant"; content: string | ContentBlock[] }[];
  propositions: { decision_id: string; outil: string; statut: string | null }[];
}

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: unknown }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean }
  | { type: "thinking"; thinking: string }
  | { type: string; [k: string]: unknown };

export interface Historique {
  plante: Plante;
  affectations: { emplacement: string; debut: string; fin: string | null }[];
  actions: { ts: string; label: string; resultat: string; decision_id: string }[];
  vision: VisionRow[];
}
