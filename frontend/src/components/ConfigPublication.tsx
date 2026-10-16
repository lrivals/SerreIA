// Consistency banner and publication of the configuration (docs/12 §2.1, docs/09 §8).
import { AlertTriangle, CheckCircle2, Upload } from "lucide-react";
import { useState } from "react";
import { useCoherence, useConfigDiff, usePublier } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { ErrorBox, Loading } from "./common";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";

export function BandeauCoherence() {
  const { data } = useCoherence();
  const [open, setOpen] = useState(false);
  if (!data || (data.valide && data.avertissements.length === 0)) return null;
  const items = [...data.erreurs, ...data.avertissements];
  const shown = open ? items : items.slice(0, 2);
  return (
    <div
      role="status"
      className={cn(
        "mb-4 rounded-md border p-3 text-sm",
        data.valide ? "border-warn/50 bg-warn/10" : "border-bad/50 bg-bad/10",
      )}
    >
      <div className="mb-1 flex items-center gap-2 font-medium">
        <AlertTriangle className={cn("h-4 w-4", data.valide ? "text-warn" : "text-bad")} />
        {data.valide
          ? `${data.avertissements.length} avertissement(s) de cohérence`
          : "Configuration invalide : publication impossible"}
      </div>
      <ul className="ml-6 list-disc space-y-0.5">
        {shown.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      {items.length > 2 && (
        <button className="mt-1 ml-6 cursor-pointer text-xs underline" onClick={() => setOpen(!open)}>
          {open ? "réduire" : `voir les ${items.length}`}
        </button>
      )}
    </div>
  );
}

export function BoutonPublier() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Upload className="h-4 w-4" /> Publier la configuration
      </Button>
      {open && <DialoguePublication open={open} onOpenChange={setOpen} />}
    </>
  );
}

function DialoguePublication({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const diff = useConfigDiff(open);
  const publier = usePublier();
  const done = publier.data;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Publier la configuration"
      description="Une nouvelle version de serre.yaml est validée, versionnée puis installée pour le contrôleur, qui la recharge à chaud."
      className="w-[min(820px,calc(100vw-32px))]"
    >
      {diff.isLoading && <Loading label="Calcul des différences…" />}
      {diff.error && <ErrorBox error={diff.error} />}
      {diff.data && !done && (
        <>
          <p className="mb-2 text-sm text-muted-foreground">
            {diff.data.de} → {diff.data.a}
          </p>
          {diff.data.identique ? (
            <p className="mb-3 text-sm">Aucun changement depuis la dernière version publiée.</p>
          ) : (
            <pre className="mb-3 max-h-[50vh] overflow-auto rounded-md border bg-muted p-2 text-xs leading-5">
              {diff.data.diff.split("\n").map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    line.startsWith("+") && !line.startsWith("+++") && "bg-ok/15 text-ok",
                    line.startsWith("-") && !line.startsWith("---") && "bg-bad/15 text-bad",
                    line.startsWith("@@") && "text-info",
                  )}
                >
                  {line || " "}
                </div>
              ))}
            </pre>
          )}
          {publier.error && <ErrorBox error={publier.error} />}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Annuler
            </Button>
            <Button disabled={publier.isPending} onClick={() => publier.mutate(undefined)}>
              {diff.data.identique ? "Republier" : "Publier"}
            </Button>
          </div>
        </>
      )}
      {done && (
        <div className="flex flex-col gap-2 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="h-4 w-4 text-ok" />
            Configuration v{done.config_version} {done.nouvelle ? "publiée" : "inchangée"}
          </p>
          <p className="font-mono text-xs text-muted-foreground">{done.fichier}</p>
          {done.avertissements.length > 0 && (
            <ul className="ml-5 list-disc text-warn">
              {done.avertissements.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <Button className="self-end" onClick={() => onOpenChange(false)}>
            Fermer
          </Button>
        </div>
      )}
    </Dialog>
  );
}
