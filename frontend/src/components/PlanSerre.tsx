// Grid plan of a zone (docs/12 §2.1): emplacements by row × column, plants dropped from
// the palette or dragged from one emplacement to another, "+" cells to add emplacements.
import { Camera, Plus } from "lucide-react";
import { useState, type DragEvent } from "react";
import type { EmplacementPlan } from "@/api/types";
import { especeIcon, gridCode, HEALTH_MARK } from "@/lib/especes";
import { cn } from "@/lib/utils";

export const DND_ESPECE = "application/x-serreia-espece";
export const DND_PLANTE = "application/x-serreia-plante";

export interface PlanActions {
  onSelect: (id: string) => void;
  onDropEspece: (emplacement: string, espece: string) => void;
  onMovePlante: (plante: string, emplacement: string) => void;
  onCreateAt: (code: string, rangee: number, colonne: number) => void;
}

export function PlanSerre({
  emplacements,
  selected,
  ...actions
}: { emplacements: EmplacementPlan[]; selected?: string | null } & PlanActions) {
  const grid = emplacements.filter((e) => e.rangee && e.colonne);
  const others = emplacements.filter((e) => !(e.rangee && e.colonne));
  const rows = Math.max(0, ...grid.map((e) => e.rangee!)) + 1;
  const cols = Math.max(1, ...grid.map((e) => e.colonne!)) + 1;
  const at = new Map(grid.map((e) => [`${e.rangee}:${e.colonne}`, e]));

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <div
          className="grid gap-2"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(92px, 1fr))` }}
          role="grid"
          aria-label="Plan de la zone"
        >
          {Array.from({ length: rows * cols }, (_, i) => {
            const r = Math.floor(i / cols) + 1;
            const c = (i % cols) + 1;
            const e = at.get(`${r}:${c}`);
            return e ? (
              <Cellule key={e.id} e={e} selected={selected === e.id} {...actions} />
            ) : (
              <button
                key={`${r}:${c}`}
                onClick={() => actions.onCreateAt(gridCode(r, c), r, c)}
                className="flex min-h-[84px] cursor-pointer items-center justify-center rounded-md border border-dashed text-muted-foreground/60 hover:border-primary hover:text-primary"
                title={`Créer l'emplacement ${gridCode(r, c)}`}
                aria-label={`Créer l'emplacement ${gridCode(r, c)}`}
              >
                <Plus className="h-4 w-4" />
              </button>
            );
          })}
        </div>
      </div>
      {others.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-muted-foreground">Hors grille (étagères, canaux…)</p>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(92px,1fr))] gap-2">
            {others.map((e) => (
              <Cellule key={e.id} e={e} selected={selected === e.id} {...actions} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Cellule({
  e,
  selected,
  onSelect,
  onDropEspece,
  onMovePlante,
}: { e: EmplacementPlan; selected: boolean } & PlanActions) {
  const [over, setOver] = useState(false);
  const p = e.plante;
  const health = p ? HEALTH_MARK[p.etat_sante] ?? HEALTH_MARK.sain : null;
  const accepts = (ev: DragEvent) =>
    !p && (ev.dataTransfer.types.includes(DND_ESPECE) || ev.dataTransfer.types.includes(DND_PLANTE));

  return (
    <div
      role="gridcell"
      tabIndex={0}
      aria-selected={selected}
      data-testid={`emplacement-${e.id}`}
      onClick={() => onSelect(e.id)}
      onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && onSelect(e.id)}
      draggable={!!p}
      onDragStart={(ev) => p && ev.dataTransfer.setData(DND_PLANTE, p.id)}
      onDragOver={(ev) => {
        if (accepts(ev)) {
          ev.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(ev) => {
        ev.preventDefault();
        setOver(false);
        const espece = ev.dataTransfer.getData(DND_ESPECE);
        const plante = ev.dataTransfer.getData(DND_PLANTE);
        if (espece) onDropEspece(e.id, espece);
        else if (plante) onMovePlante(plante, e.id);
      }}
      className={cn(
        "flex min-h-[84px] cursor-pointer flex-col justify-between rounded-md border bg-card p-2 text-left outline-none hover:border-primary/60 focus-visible:ring-2 focus-visible:ring-ring/40",
        selected && "border-primary ring-2 ring-primary/30",
        over && "border-primary bg-primary/10",
      )}
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-mono font-medium">{e.code}</span>
        <span className="flex items-center gap-1 text-muted-foreground">
          {e.cameras.length > 0 && (
            <Camera
              className={cn("h-3 w-3", e.cameras.some((c) => c.region) ? "text-primary" : "")}
              aria-label="vu par une caméra"
            />
          )}
          {e.mode_culture !== "terre" && <span>{e.mode_culture.replace("hydro_", "")}</span>}
        </span>
      </div>
      {p ? (
        <div className="flex items-center gap-1.5">
          <span className="text-2xl leading-none" aria-hidden>
            {especeIcon(p.espece)}
          </span>
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">{p.espece}</div>
            <div className={cn("text-xs", health!.className)} title={health!.label}>
              {health!.mark} <span className="text-muted-foreground">{p.stade}</span>
            </div>
          </div>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">vide</span>
      )}
    </div>
  );
}
