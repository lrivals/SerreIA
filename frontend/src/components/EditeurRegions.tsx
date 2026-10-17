// Camera region editor (docs/12 §2.1): on the last image of the camera, draw the rectangle
// of each emplacement it sees. Coordinates are normalised to [0, 1] (`camera_region.bbox`).
import { useRef, useState, type PointerEvent } from "react";
import { imageUrl } from "@/api/client";
import { useSetRegions } from "@/api/hooks";
import type { Camera, EmplacementPlan } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ErrorBox } from "./common";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";

type Box = [number, number, number, number];
const COLORS = ["#16a34a", "#2563eb", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];
const clamp = (v: number) => Math.min(1, Math.max(0, v));

export function EditeurRegions({
  camera,
  emplacements,
  open,
  onOpenChange,
}: {
  camera: Camera;
  emplacements: EmplacementPlan[];
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [regions, setRegions] = useState<Record<string, Box | null>>(() =>
    Object.fromEntries(camera.regions.map((r) => [r.emplacement_id, r.bbox])),
  );
  const [active, setActive] = useState<string | null>(emplacements[0]?.id ?? null);
  const [draft, setDraft] = useState<{ x0: number; y0: number; box: Box } | null>(null);
  const [imgFailed, setImgFailed] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const save = useSetRegions();

  const point = (ev: PointerEvent) => {
    const r = area.current!.getBoundingClientRect();
    return [clamp((ev.clientX - r.left) / r.width), clamp((ev.clientY - r.top) / r.height)];
  };
  const down = (ev: PointerEvent) => {
    if (!active) return;
    (ev.target as Element).setPointerCapture?.(ev.pointerId);
    const [x, y] = point(ev);
    setDraft({ x0: x, y0: y, box: [x, y, 0, 0] });
  };
  const move = (ev: PointerEvent) => {
    if (!draft) return;
    const [x, y] = point(ev);
    setDraft({ ...draft, box: [Math.min(x, draft.x0), Math.min(y, draft.y0), Math.abs(x - draft.x0), Math.abs(y - draft.y0)] });
  };
  const up = () => {
    if (draft && active && draft.box[2] > 0.01 && draft.box[3] > 0.01) {
      const box = draft.box.map((v) => Math.round(v * 1000) / 1000) as Box;
      setRegions((r) => ({ ...r, [active]: box }));
    }
    setDraft(null);
  };

  const color = (id: string) => COLORS[emplacements.findIndex((e) => e.id === id) % COLORS.length];
  const shown = Object.entries(regions).filter(([, b]) => b) as [string, Box][];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Régions de ${camera.id}`}
      description="Choisir un emplacement puis tracer son rectangle sur l'image. « Visible » sans région : résultats non rattachés si la caméra voit plusieurs emplacements."
      className="w-[min(960px,calc(100vw-32px))]"
    >
      <div className="grid gap-4 md:grid-cols-[1fr_240px]">
        <div>
          <div
            ref={area}
            className="relative cursor-crosshair touch-none overflow-hidden rounded-md border bg-muted select-none"
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            data-testid="zone-dessin"
          >
            {camera.derniere_image && !imgFailed ? (
              <img
                src={imageUrl(camera.derniere_image.image_id)}
                alt="dernière image"
                className="pointer-events-none block w-full"
                draggable={false}
                onError={() => setImgFailed(true)}
              />
            ) : (
              <div className="flex aspect-[4/3] items-center justify-center text-sm text-muted-foreground">
                pas d'image : tracer sur le cadre vide
              </div>
            )}
            {[...shown, ...(draft && active ? [[active, draft.box] as [string, Box]] : [])].map(([id, [x, y, w, h]], i) => (
              <div
                key={`${id}-${i}`}
                className="pointer-events-none absolute border-2"
                style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%`, borderColor: color(id) }}
              >
                <span className="absolute top-0 left-0 px-1 text-[10px] text-white" style={{ background: color(id) }}>
                  {id}
                </span>
              </div>
            ))}
          </div>
          {camera.derniere_image && (
            <p className="mt-1 text-xs text-muted-foreground">image du {fmtDateTime(camera.derniere_image.ts)}</p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          {emplacements.map((e) => {
            const visible = e.id in regions;
            return (
              <div
                key={e.id}
                className={cn("flex items-center gap-2 rounded-md border px-2 py-1 text-sm", active === e.id && "border-primary bg-primary/5")}
              >
                <input
                  type="checkbox"
                  checked={visible}
                  aria-label={`${e.id} visible`}
                  onChange={(ev) =>
                    setRegions((r) => {
                      const next = { ...r };
                      if (ev.target.checked) next[e.id] = null;
                      else delete next[e.id];
                      return next;
                    })
                  }
                />
                <button className="flex flex-1 cursor-pointer items-center gap-1.5 text-left" onClick={() => setActive(e.id)}>
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color(e.id) }} />
                  <span className="font-mono">{e.id}</span>
                </button>
                <span className="text-xs text-muted-foreground">{regions[e.id] ? "région ✓" : visible ? "visible" : ""}</span>
              </div>
            );
          })}
          {save.error && <ErrorBox error={save.error} />}
          <Button
            className="mt-2"
            disabled={save.isPending}
            onClick={() =>
              save.mutate(
                {
                  camera: camera.id,
                  regions: Object.entries(regions).map(([emplacement_id, bbox]) => ({ emplacement_id, bbox })),
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Enregistrer
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
