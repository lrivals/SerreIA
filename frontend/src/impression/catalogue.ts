// Printed parts of the greenhouse (docs/20) as data for the configurator (docs/21):
// materials, print settings, dimensions to measure and the catalogue A1–E6.
// Dimensions flagged `params: true` mirror hardware/params.py (same name, same nominal value,
// checked by tests/test_impression_ui.py) and are exported to hardware/mesures.toml.

export type Famille = "A" | "B" | "C" | "D" | "E";
export type Echelle = "petite" | "tunnel" | "grande";
export type Priorite = "P0" | "P1" | "P2" | "Evolution";
export type Pertinence = "oui" | "partiel" | "non";
export type Materiau = "PLA" | "PETG" | "ASA" | "ABS" | "PETG-CF" | "ASA-CF" | "TPU";
export type Usage = "structure" | "etanche" | "support";

export const FAMILLES: Record<Famille, string> = {
  A: "Hydroponie",
  B: "Structure et bâche",
  C: "Éclairage réglable",
  D: "Électronique et capteurs",
  E: "Culture",
};

export const ECHELLES: Record<Echelle, string> = {
  petite: "Petite intérieure (< 1 m²)",
  tunnel: "Tunnel jardin (1–6 m²)",
  grande: "Grande (> 6 m²)",
};

export const PRIORITES: Priorite[] = ["P0", "P1", "P2", "Evolution"];

// docs/20 §2.2. PLA is listed for reference only: never proposed.
export const MATERIAUX: Record<Materiau, { temperature: string; uv: string; usage: string }> = {
  PLA: { temperature: "~55 °C", uv: "faible", usage: "exclu (gabarits, éprouvettes seulement)" },
  PETG: { temperature: "~75 °C", uv: "moyen", usage: "humide et ombragé : hydroponie, sondes, boîtiers" },
  ASA: { temperature: "~95 °C", uv: "très bon", usage: "tout ce qui voit le soleil" },
  ABS: { temperature: "~95 °C", uv: "faible", usage: "pièces chaudes à l'abri des UV" },
  "PETG-CF": { temperature: "~75 °C", uv: "moyen", usage: "pièces rigides à l'ombre" },
  "ASA-CF": { temperature: "~95 °C", uv: "très bon", usage: "pièces rigides au soleil ou au chaud" },
  TPU: { temperature: "~60 °C", uv: "moyen", usage: "joints, patins, colliers souples" },
};

export const FILAMENTS: Materiau[] = ["PETG", "ASA", "ABS", "PETG-CF", "ASA-CF", "TPU"];

// docs/20 §2.3
export const REGLAGES: Record<Usage, { parois: string; remplissage: string; remarque: string }> = {
  structure: {
    parois: "4–6",
    remplissage: "40–60 % gyroïde",
    remarque: "couches perpendiculaires à l'effort principal",
  },
  etanche: { parois: "4+", remplissage: "100 % ou parois épaisses", remarque: "ou époxy alimentaire à l'intérieur" },
  support: { parois: "3", remplissage: "20 %", remarque: "" },
};

export interface Cote {
  cle: string;
  libelle: string;
  unite: string;
  nominal: number;
  min: number;
  max: number;
  outil: string;
  params?: boolean; // field of hardware/params.py (exported to mesures.toml)
}

// docs/20 §5.2; one per line (parsed by tests/test_impression_ui.py).
export const COTES: Cote[] = [
  { cle: "jeu", libelle: "Jeu d'ajustement de la CC2", unite: "mm", nominal: 0.3, min: 0.1, max: 0.5, outil: "anneaux de jeu 0,1–0,5 mm, le plus serré qui coulisse", params: true },
  { cle: "tube_d", libelle: "Ø extérieur du tube de structure", unite: "mm", nominal: 20.0, min: 10, max: 50, outil: "pied à coulisse, 3 endroits, garder le plus grand", params: true },
  { cle: "tube_faitage_d", libelle: "Ø du tube de faîtage", unite: "mm", nominal: 20.0, min: 10, max: 50, outil: "pied à coulisse", params: true },
  { cle: "film_ep", libelle: "Épaisseur du film (0,2 = 200 µm)", unite: "mm", nominal: 0.2, min: 0.1, max: 0.3, outil: "fiche du film", params: true },
  { cle: "cuve_hauteur", libelle: "Hauteur intérieure de la cuve", unite: "mm", nominal: 420.0, min: 100, max: 1000, outil: "mètre", params: true },
  { cle: "cuve_niveau_max", libelle: "Niveau d'eau le plus haut (trop-plein)", unite: "mm", nominal: 160.0, min: 20, max: 900, outil: "mètre", params: true },
  { cle: "sonde_ph_d", libelle: "Ø de la sonde pH", unite: "mm", nominal: 12.0, min: 8, max: 16, outil: "pied à coulisse", params: true },
  { cle: "sonde_ec_d", libelle: "Ø de la sonde EC", unite: "mm", nominal: 12.0, min: 8, max: 16, outil: "pied à coulisse", params: true },
  { cle: "ds18b20_d", libelle: "Ø du fourreau DS18B20", unite: "mm", nominal: 6.0, min: 4, max: 8, outil: "pied à coulisse", params: true },
  { cle: "jsn_d", libelle: "Ø de la tête JSN-SR04T", unite: "mm", nominal: 22.0, min: 15, max: 30, outil: "pied à coulisse", params: true },
  { cle: "carte_l", libelle: "Longueur de la carte du nœud (connecteurs compris)", unite: "mm", nominal: 50.0, min: 5, max: 120, outil: "pied à coulisse", params: true },
  { cle: "carte_w", libelle: "Largeur de la carte du nœud", unite: "mm", nominal: 30.0, min: 5, max: 120, outil: "pied à coulisse", params: true },
  { cle: "carte_h", libelle: "Hauteur du plus haut composant", unite: "mm", nominal: 15.0, min: 2, max: 40, outil: "pied à coulisse", params: true },
  { cle: "cable_d", libelle: "Ø des câbles de capteurs", unite: "mm", nominal: 5.0, min: 2, max: 12, outil: "pied à coulisse", params: true },
  { cle: "profile_cote", libelle: "Côté du montant de lampe (profilé 2020 ou tube)", unite: "mm", nominal: 20.0, min: 15, max: 40, outil: "pied à coulisse", params: true },
  { cle: "canal_nft_d", libelle: "Ø du canal NFT", unite: "mm", nominal: 100, min: 75, max: 110, outil: "pied à coulisse" },
  { cle: "pente_nft", libelle: "Pente des canaux NFT", unite: "%", nominal: 2, min: 1, max: 4, outil: "niveau, dénivelé / longueur" },
  { cle: "netpot_d", libelle: "Ø des net-pots", unite: "mm", nominal: 50, min: 25, max: 80, outil: "pied à coulisse (sous la collerette)" },
  { cle: "seau_d", libelle: "Ø du seau ou du bac DWC", unite: "mm", nominal: 300, min: 150, max: 600, outil: "mètre" },
  { cle: "hauteur_max", libelle: "Course de réglage de la lampe", unite: "mm", nominal: 600, min: 100, max: 1500, outil: "mètre" },
  { cle: "lampe_masse", libelle: "Masse de la lampe", unite: "kg", nominal: 1.5, min: 0.1, max: 10, outil: "balance" },
  { cle: "tuteur_d", libelle: "Ø du tuteur", unite: "mm", nominal: 10, min: 6, max: 16, outil: "pied à coulisse" },
  { cle: "goutte_d", libelle: "Ø du tube goutte-à-goutte", unite: "mm", nominal: 4.6, min: 4, max: 16, outil: "pied à coulisse" },
];

export const COTE: Record<string, Cote> = Object.fromEntries(COTES.map((c) => [c.cle, c]));

export interface Modele {
  nom: string;
  url: string;
}

export interface Piece {
  id: string;
  famille: Famille;
  titre: string;
  priorite: Priorite;
  echelles: Record<Echelle, Pertinence>;
  partiel?: string; // why the part is only partly relevant at some scale
  materiaux: Materiau[]; // candidates, preferred first (docs/20 §4)
  usage: Usage;
  eau?: boolean; // touches water or nutrient solution: opaque, never porous
  joint?: boolean; // TPU gasket
  chaleur?: boolean; // may sit near an LED driver
  serre?: boolean; // tight fit: print a test piece first (docs/20 §1)
  cotes: string[];
  modeles: Modele[];
  nePasImprimer?: string;
  note?: string;
  logiciel?: string;
}

const PARTOUT: Record<Echelle, Pertinence> = { petite: "oui", tunnel: "oui", grande: "oui" };

export const PIECES: Piece[] = [
  // A. Hydroponics
  {
    id: "A1",
    famille: "A",
    titre: "Tour hydroponique verticale",
    priorite: "P1",
    echelles: { petite: "oui", tunnel: "oui", grande: "partiel" },
    partiel: "grande serre : accessoires seulement (embouts, supports)",
    materiaux: ["PETG", "ASA"],
    usage: "etanche",
    eau: true,
    serre: true,
    cotes: ["netpot_d"],
    modeles: [
      { nom: "Modular Hydroponic Tower (Printables)", url: "https://www.printables.com/model/720081-modular-hydroponic-tower" },
      { nom: "Modular Hydroponic Tower – Vertical Growing System (MakerWorld)", url: "https://makerworld.com/en/models/2415282-modular-hydroponic-tower-vertical-growing-system" },
      { nom: "Modular Hydroponic Tower, baïonnette (MakerWorld)", url: "https://makerworld.com/en/models/1382834-modular-hydroponic-tower" },
      { nom: "Threaded Bucket Lid Adapter (Printables)", url: "https://www.printables.com/model/582197-modular-hydroponics-tower-threaded-bucket-lid-adap" },
    ],
    note: "4 parois minimum sur les cuvettes ; nombre d'étages selon la hauteur sous lampe",
    logiciel: "zone hydro_nft ou ebb_flow, un emplacement par trou",
  },
  {
    id: "A2",
    famille: "A",
    titre: "NFT : embouts de canaux, net-pots, adaptateurs",
    priorite: "P1",
    echelles: { petite: "oui", tunnel: "oui", grande: "oui" },
    materiaux: ["PETG", "ASA"],
    usage: "etanche",
    eau: true,
    joint: true,
    serre: true,
    cotes: ["canal_nft_d", "netpot_d", "pente_nft"],
    modeles: [
      { nom: "Parametric Net Pot (OpenSCAD)", url: "https://www.printables.com/model/50326-parametric-net-pot-remix-with-closed-bottom" },
      { nom: "2\" Net Pot Adapter to 2.5\" hole", url: "https://www.printables.com/model/1197209-2-net-pot-adapter-to-25-hole" },
      { nom: "2x3 Channel Cap (MakerWorld)", url: "https://www.makerworld.com/en/models/1416620" },
      { nom: "Parametric Pipe Adapter (OpenSCAD)", url: "https://www.printables.com/model/132932-parametric-pipe-adapter-openscad" },
    ],
    logiciel: "contenant.type: canal_NFT, un emplacement par trou",
  },
  {
    id: "A3",
    famille: "A",
    titre: "DWC : couvercles de seau et bocaux",
    priorite: "P1",
    echelles: PARTOUT,
    materiaux: ["PETG", "ASA"],
    usage: "etanche",
    eau: true,
    cotes: ["seau_d", "netpot_d"],
    modeles: [
      { nom: "6-pod 2\" net cup (Printables)", url: "https://www.printables.com/model/1186373-modified-6pod-2inch-net-cup-hydroponic-modular-tow" },
      { nom: "5-gallon modular bucket lid (MakerWorld)", url: "https://www.makerworld.com/en/models/1443063" },
    ],
    note: "passage du tuyau du bulleur et d'une sonde",
    logiciel: "contenant.type: bac_DWC, mode hydro_dwc",
  },
  {
    id: "A4",
    famille: "A",
    titre: "Couvercle de cuve et supports de sondes",
    priorite: "P0",
    echelles: PARTOUT,
    materiaux: ["PETG", "ASA"],
    usage: "etanche",
    eau: true,
    joint: true,
    serre: true,
    cotes: ["cuve_hauteur", "cuve_niveau_max", "sonde_ph_d", "sonde_ec_d", "ds18b20_d", "jsn_d"],
    modeles: [],
    note: "à concevoir (hardware/pieces/couvercle_cuve) : pH et EC écartées ≥ 50 mm, JSN-SR04T ≥ 25 cm au-dessus de l'eau",
    logiciel: "capteurs cuve: true de la zone",
  },
  // B. Structure and film
  {
    id: "B1",
    famille: "B",
    titre: "Raccords de tubes (arceaux, cadre, faîtage)",
    priorite: "P1",
    echelles: { petite: "partiel", tunnel: "oui", grande: "partiel" },
    partiel: "petite : cadre en tube 16–20 mm tout en raccords ; grande : la structure est achetée",
    materiaux: ["ASA-CF", "ASA"],
    usage: "structure",
    serre: true,
    cotes: ["tube_d"],
    modeles: [
      { nom: "Parametric dowel and tube joiners (OpenSCAD)", url: "https://makerworld.com/models/2933746" },
      { nom: "Universal Modular Pipe Connector", url: "https://makerworld.com/en/models/2662089-universal-modular-pipe-connector" },
      { nom: "Parametric n-way pipe fitting", url: "https://www.printables.com/model/638480-parametric-n-way-0-6-way-pipe-fitting" },
      { nom: "Pipe connector for small DIY Greenhouse hoop", url: "https://www.printables.com/model/1011234-pipe-connector-for-small-diy-greenhouse-hoop" },
    ],
    note: "5–6 parois ; pieds imprimés sur piquet ou tige filetée : c'est le piquet qui tient au vent",
  },
  {
    id: "B2",
    famille: "B",
    titre: "Clips de bâche",
    priorite: "P1",
    echelles: { petite: "partiel", tunnel: "oui", grande: "oui" },
    partiel: "petite : seulement si le cadre est bâché",
    materiaux: ["ASA"],
    usage: "structure",
    serre: true,
    cotes: ["tube_d", "film_ep"],
    modeles: [
      { nom: "Greenhouse plastic clamp", url: "https://www.printables.com/model/154773-greenhouse-plastic-clamp" },
      { nom: "C-Clips for PEHD pipe DN16/20/25/32", url: "https://www.printables.com/model/1555068-c-clips-for-pehd-flexible-pipe-dn16202532" },
    ],
    nePasImprimer: "profilé + fil zigzag (wiggle wire) : alu et acier ; imprimer seulement embouts et patins TPU",
    note: "enveloppement 200–220°, largeur 40–60 mm, arêtes R ≥ 1 mm ; un clip tous les 50–60 cm, plus serré aux angles",
  },
  {
    id: "B3",
    famille: "B",
    titre: "Porte, ouvrants et grilles d'aération",
    priorite: "P2",
    echelles: { petite: "non", tunnel: "oui", grande: "oui" },
    materiaux: ["ASA"],
    usage: "structure",
    cotes: ["tube_d"],
    modeles: [{ nom: "DIY GREENHOUSE by KMS (ouvrant de toit)", url: "https://www.printables.com/model/62627-diy-greenhouse-by-kms" }],
    nePasImprimer: "vérin d'ouvrant : ouvre-fenêtre à cire du commerce ; imprimer seulement ses supports",
    logiciel: "ouvrant motorisé = actionneur ; ouvrant à cire noté dans la description de la zone",
  },
  {
    id: "B4",
    famille: "B",
    titre: "Gouttières de condensation",
    priorite: "P2",
    echelles: { petite: "partiel", tunnel: "oui", grande: "oui" },
    partiel: "petite : seulement au-dessus de l'électronique",
    materiaux: ["ASA"],
    usage: "structure",
    cotes: ["tube_d"],
    modeles: [],
    note: "à dessiner : section en L, pince au Ø de la structure",
  },
  // C. Adjustable lighting
  {
    id: "C1",
    famille: "C",
    titre: "Supports et coulisseaux de lampe",
    priorite: "P1",
    echelles: PARTOUT,
    materiaux: ["PETG-CF", "ASA-CF", "ASA"],
    usage: "structure",
    chaleur: true,
    serre: true,
    cotes: ["profile_cote", "hauteur_max", "lampe_masse"],
    modeles: [
      { nom: "Plant box LED holder (adjustable)", url: "https://www.printables.com/model/58670-plant-box-led-holder-adjustable" },
      { nom: "Barrina T8 Plant Grow Light Stand", url: "https://www.printables.com/model/773928-barrina-t8-plant-grow-light-stand" },
      { nom: "LED support (MakerWorld)", url: "https://makerworld.com/en/models/1741488-led-support" },
    ],
    note: "variantes : coulisseau à molette sur montant, écrou papillon sur tige M8, crémaillère à crans",
  },
  {
    id: "C2",
    famille: "C",
    titre: "Crochets de faîtage et palonniers",
    priorite: "P1",
    echelles: PARTOUT,
    materiaux: ["ASA", "ASA-CF"],
    usage: "structure",
    chaleur: true,
    cotes: ["tube_faitage_d", "lampe_masse"],
    modeles: [],
    nePasImprimer: "suspension à cliquet (ratchet hanger) : l'acheter, certifiée pour la charge",
  },
  {
    id: "C3",
    famille: "C",
    titre: "Hauteur de lampe motorisée",
    priorite: "Evolution",
    echelles: PARTOUT,
    materiaux: ["PETG-CF", "ASA-CF"],
    usage: "structure",
    chaleur: true,
    cotes: ["hauteur_max", "profile_cote"],
    modeles: [],
    note: "NEMA 17 + vis T8 ou enrouleur ; prérequis : C1 manuel validé",
    logiciel: "actionneur led_hauteur (consigne en cm) sur esp32-04",
  },
  // D. Electronics and sensors
  {
    id: "D1",
    famille: "D",
    titre: "Abri ventilé (écran de Stevenson)",
    priorite: "P0",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "structure",
    cotes: [],
    modeles: [
      { nom: "Solar Radiation Shield", url: "https://www.printables.com/model/235525-solar-radiation-shield" },
      { nom: "Abri paramétrique Fusion 360 + ESP32", url: "https://hiltsu.codeberg.page/en/posts/stevenson-shield-esp32-lorawan/" },
    ],
    note: "ASA blanc, parois épaisses (le filament laisse passer l'infrarouge)",
  },
  {
    id: "D2",
    famille: "D",
    titre: "Boîtiers des nœuds XIAO ESP32-C6",
    priorite: "P0",
    echelles: PARTOUT,
    materiaux: ["PETG", "ASA"],
    usage: "etanche",
    joint: true,
    serre: true,
    cotes: ["carte_l", "carte_w", "carte_h", "cable_d"],
    modeles: [
      { nom: "Boîtier XIAO couvercle coulissant + antenne", url: "https://www.makerworld.com/en/models/2145189" },
      { nom: "Parameterized Rugged Box (TPU)", url: "https://www.printables.com/model/793850-parameterized-rugged-box-openscad-with-tpu-gasket" },
    ],
    note: "presse-étoupes, sortie antenne U.FL, évent bas contre la condensation",
  },
  {
    id: "D3",
    famille: "D",
    titre: "Support radar HLK-LD2450",
    priorite: "P1",
    echelles: PARTOUT,
    materiaux: ["PETG", "ASA"],
    usage: "support",
    cotes: [],
    modeles: [{ nom: "Boîtier orientable LD2450 + ESP32", url: "https://www.printables.com/model/1514952-mmwave-sensor-ld2450-d1-mini-esp32" }],
    note: "pas de métal ni de face épaisse devant l'antenne",
  },
  {
    id: "D4",
    famille: "D",
    titre: "Supports caméra à angle fixe",
    priorite: "P0",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "structure",
    serre: true,
    cotes: ["tube_d"],
    modeles: [
      { nom: "Support articulé Camera Module 3", url: "https://3dgo.app/models/printables/368788" },
      { nom: "Camera mount for extrusions", url: "https://www.printables.com/model/573073-raspberry-pi-camera-module-mount-for-extrusions" },
    ],
    note: "rotule verrouillable avec repère gradué, visière anti-condensation",
  },
  {
    id: "D5",
    famille: "D",
    titre: "Support de mire (gris neutre / couleurs)",
    priorite: "P0",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "support",
    cotes: [],
    modeles: [],
    note: "ASA mat ; repères d'échelle imprimés (px → cm²)",
  },
  {
    id: "D6",
    famille: "D",
    titre: "Boîtier Pi 5 + Hailo",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "support",
    cotes: [],
    modeles: [{ nom: "Boîtier modulaire Pi 5", url: "https://makerworld.com/models/1020178" }],
    note: "placer le Pi hors de la serre si possible ; ventilateur 40 mm + filtre",
  },
  {
    id: "D7",
    famille: "D",
    titre: "Supports de pompes et ventilateurs",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["PETG"],
    usage: "support",
    cotes: [],
    modeles: [],
    note: "à concevoir : berceau de pompe avec bac de rétention, carénage 120 mm, bride de tuyau",
  },
  {
    id: "D8",
    famille: "D",
    titre: "Goulottes et passe-câbles",
    priorite: "P1",
    echelles: PARTOUT,
    materiaux: ["ASA", "TPU"],
    usage: "support",
    cotes: ["tube_d", "cable_d"],
    modeles: [],
    note: "câbles en goutte (boucle sous le boîtier)",
  },
  // E. Growing
  {
    id: "E1",
    famille: "E",
    titre: "Clips de tuteur et palissage",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["PETG", "TPU"],
    usage: "support",
    cotes: ["tuteur_d"],
    modeles: [{ nom: "Adaptable Plant Clip", url: "https://printables.com/model/221320-adaptable-plant-clip-tomato-clip" }],
  },
  {
    id: "E2",
    famille: "E",
    titre: "Supports de semis",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["PETG"],
    usage: "support",
    cotes: [],
    modeles: [{ nom: "Seedling support with auto-clip", url: "https://www.printables.com/model/64716-seedling-support-with-auto-clip-no-wires-needed" }],
  },
  {
    id: "E3",
    famille: "E",
    titre: "Porte-tubes goutte-à-goutte (zone terre)",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["PETG", "ASA"],
    usage: "support",
    cotes: ["goutte_d"],
    modeles: [{ nom: "Drip irrigation holders 1/2\" et 3/16\"", url: "https://www.printables.com/model/461502-12-and-316-drip-irrigation-holders-for-drip-hoses" }],
    nePasImprimer: "raccords sous pression (fuites signalées en PETG)",
  },
  {
    id: "E4",
    famille: "E",
    titre: "Étiquettes d'emplacement",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "support",
    cotes: [],
    modeles: [],
    note: "code z1-A1 + QR vers la fiche de l'emplacement",
  },
  {
    id: "E5",
    famille: "E",
    titre: "Plateaux de semis et dômes",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["PETG"],
    usage: "etanche",
    eau: true,
    cotes: [],
    modeles: [],
    note: "générateur de bac paramétrique : alvéoles, profondeur, drainage",
  },
  {
    id: "E6",
    famille: "E",
    titre: "Cales de pente et pieds de bacs",
    priorite: "P2",
    echelles: PARTOUT,
    materiaux: ["ASA"],
    usage: "structure",
    cotes: ["pente_nft"],
    modeles: [],
  },
];
