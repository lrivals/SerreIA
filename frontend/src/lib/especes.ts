const ICONS: Record<string, string> = {
  tomate: "🍅",
  fraisier: "🍓",
  fraise: "🍓",
  poivron: "🫑",
  piment: "🌶️",
  basilic: "🌿",
  laitue: "🥬",
  salade: "🥬",
  concombre: "🥒",
  courgette: "🥒",
  aubergine: "🍆",
  menthe: "🌿",
};

export const especeIcon = (espece: string) => ICONS[espece.toLowerCase()] ?? "🌱";

export const HEALTH_MARK: Record<string, { mark: string; label: string; className: string }> = {
  sain: { mark: "●", label: "sain", className: "text-ok" },
  a_surveiller: { mark: "▲", label: "à surveiller", className: "text-warn" },
  malade: { mark: "✖", label: "malade", className: "text-bad" },
  isolee: { mark: "✖", label: "isolée", className: "text-bad" },
  retiree: { mark: "○", label: "retirée", className: "text-muted-foreground" },
};

/** Code of a grid position: row 1 → A, column 3 → "A3". */
export const gridCode = (rangee: number, colonne: number) =>
  `${String.fromCharCode(64 + rangee)}${colonne}`;
