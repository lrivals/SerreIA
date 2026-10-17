// SerrePhone (docs/13 §1, a nod to the NookPhone): the overlay menu that opens the classic
// screens over the game, and the game options.
import { Link } from "react-router-dom";

const ECRANS = [
  { to: "/tableau", icone: "📊", label: "Tableau de bord" },
  { to: "/decisions", icone: "📋", label: "Décisions" },
  { to: "/arbre", icone: "🌳", label: "Arbre des actions" },
  { to: "/consommation", icone: "⚡", label: "Consommation" },
  { to: "/equipements", icone: "🔧", label: "Équipements" },
  { to: "/agent", icone: "💬", label: "Agent" },
  { to: "/constructeur", icone: "📐", label: "Constructeur classique" },
];

export function SerrePhone({
  onFermer,
  reduire,
  onReduire,
  onJardinier,
}: {
  onFermer: () => void;
  reduire: boolean;
  onReduire: (r: boolean) => void;
  onJardinier: () => void;
}) {
  return (
    <div role="dialog" aria-label="SerrePhone" className="px-panel px-font px-pop w-[260px] p-2 text-[9px]">
      <div className="mb-2 flex items-center justify-between text-[10px]">
        <span>📱 SerrePhone</span>
        <button className="px-btn" onClick={onFermer} aria-label="Fermer le SerrePhone">
          ✕
        </button>
      </div>
      <nav className="grid grid-cols-2 gap-2">
        {ECRANS.map((e) => (
          <Link key={e.to} to={e.to} className="px-btn flex-col !gap-1 text-center">
            <span className="text-base" aria-hidden>
              {e.icone}
            </span>
            {e.label}
          </Link>
        ))}
        <button className="px-btn flex-col !gap-1 text-center" onClick={onJardinier}>
          <span className="text-base" aria-hidden>
            ☺
          </span>
          Parler au jardinier
        </button>
      </nav>
      <label className="mt-3 flex items-center gap-2">
        <input type="checkbox" checked={reduire} onChange={(e) => onReduire(e.target.checked)} />
        Réduire les animations
      </label>
    </div>
  );
}
