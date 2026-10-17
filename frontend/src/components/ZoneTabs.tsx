import { useZones } from "@/api/hooks";
import { cn } from "@/lib/utils";

/** Zone selector shared by the screens; `all`: adds "Toutes". */
export function ZoneTabs({
  value,
  onChange,
  all = false,
}: {
  value: string | undefined;
  onChange: (zone: string | undefined) => void;
  all?: boolean;
}) {
  const { data: zones } = useZones();
  const items = [...(all ? [{ id: undefined as string | undefined, label: "Toutes" }] : []),
    ...(zones ?? []).map((z) => ({ id: z.id as string | undefined, label: z.nom ? `${z.id} · ${z.nom}` : z.id }))];
  return (
    <div role="tablist" className="inline-flex flex-wrap gap-1 rounded-lg bg-muted p-1">
      {items.map((z) => (
        <button
          key={z.id ?? "all"}
          role="tab"
          aria-selected={value === z.id}
          onClick={() => onChange(z.id)}
          className={cn(
            "cursor-pointer rounded-md px-3 py-1 text-sm text-muted-foreground",
            value === z.id && "bg-card text-foreground shadow-sm",
          )}
        >
          {z.label}
        </button>
      ))}
    </div>
  );
}

/** The zone of the URL (`?zone=`), else the first one. */
export function useZoneParam(param: string | null, all = false): string | undefined {
  const { data: zones } = useZones();
  if (param) return param;
  return all ? undefined : zones?.[0]?.id;
}
