// A capture with the boxes and classes of its detections (dashboard, decision record).
import { ImageOff } from "lucide-react";
import { useState } from "react";
import { imageUrl } from "@/api/client";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface Annotation {
  bbox: [number, number, number, number] | null;
  label: string;
  sain: boolean;
}

export function ImageAnnotee({
  imageId,
  annotations = [],
  gradcam = false,
  className,
}: {
  imageId: string;
  annotations?: Annotation[];
  gradcam?: boolean;
  className?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = imageUrl(imageId, gradcam);
  return (
    <div className={cn("relative overflow-hidden rounded-md border bg-muted", className)}>
      {failed === src ? (
        <div className="flex aspect-[5/2] flex-col items-center justify-center gap-1 text-xs text-muted-foreground">
          <ImageOff className="h-5 w-5" />
          {gradcam ? "Grad-CAM indisponible" : "image non reçue par le serveur"}
          <span className="font-mono">{imageId}</span>
        </div>
      ) : (
        <img src={src} alt={`capture ${imageId}`} className="block w-full" onError={() => setFailed(src)} />
      )}
      {failed !== src &&
        annotations
          .filter((a) => a.bbox)
          .map((a, i) => {
            const [x, y, w, h] = a.bbox!;
            return (
              <div
                key={i}
                className={cn("absolute border-2", a.sain ? "border-ok" : "border-bad")}
                style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}
              >
                <span
                  className={cn(
                    "absolute -top-0.5 left-0 -translate-y-full rounded-sm px-1 text-[10px] text-white",
                    a.sain ? "bg-ok" : "bg-bad",
                  )}
                >
                  {a.label}
                </span>
              </div>
            );
          })}
    </div>
  );
}

export const visionLabel = (v: { emplacement?: string | null; classe: string; classe_conf: number }) =>
  `${v.emplacement ? `${v.emplacement} · ` : ""}${v.classe.split("/").slice(1).join("/") || v.classe} ${fmtNum(v.classe_conf, 2)}`;
