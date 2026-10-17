// A frame of the atlas as an HTML icon (inventory, dialogs, portrait): CSS background of
// atlas.png at the position given by atlas.json, integer zoom, pixelated.
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

interface AtlasJson {
  frames: Record<string, { frame: { x: number; y: number; w: number; h: number } }>;
  meta: { size: { w: number; h: number } };
}

const BASE = import.meta.env.BASE_URL ?? "/";

export const useAtlas = () =>
  useQuery({
    queryKey: ["jeu", "atlas"],
    queryFn: async () => (await (await fetch(`${BASE}sprites/atlas.json`)).json()) as AtlasJson,
    staleTime: Infinity,
  });

export function SpriteIcone({
  frame,
  zoom = 1,
  className,
  label,
}: {
  frame: string | null | undefined;
  zoom?: number;
  className?: string;
  label?: string;
}) {
  const { data } = useAtlas();
  const f = frame ? data?.frames[frame]?.frame : undefined;
  if (!f || !data) return <span className={cn("inline-block h-8 w-8", className)} aria-label={label} role={label ? "img" : undefined} />;
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("px-sprite inline-block shrink-0", className)}
      style={{
        width: f.w * zoom,
        height: f.h * zoom,
        backgroundImage: `url(${BASE}sprites/atlas.png)`,
        backgroundPosition: `-${f.x * zoom}px -${f.y * zoom}px`,
        backgroundSize: `${data.meta.size.w * zoom}px ${data.meta.size.h * zoom}px`,
        backgroundRepeat: "no-repeat",
      }}
    />
  );
}
