// A proposal waiting for the user (docs/12 §2.7): what, why, evidence, estimated cost,
// Validate / Reject. Validation publishes the decision; the controller runs it through
// safety.py (docs/10 §4).
import { Check, Clock, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useRepondre } from "@/api/hooks";
import type { DecisionRecord, DecisionSummary } from "@/api/types";
import { fmtNum, fmtTime } from "@/lib/format";
import { ErrorBox, NiveauBadge, RefText, StatutBadge } from "./common";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export function CarteProposition({
  decision,
  statut,
}: {
  decision: DecisionSummary | DecisionRecord;
  statut?: string | null; // current status when known better than `decision.statut`
}) {
  const repondre = useRepondre();
  const [rejet, setRejet] = useState(false);
  const [motif, setMotif] = useState("");
  const current = statut ?? decision.statut;
  const proposals = decision.actions.filter((a) => a.startsWith("proposee:")).map((a) => a.slice(9));
  const estimation = "estimation" in decision ? decision.estimation : undefined;
  const [why, what] = decision.explication.split(" → ");

  return (
    <div className="rounded-lg border border-info/40 bg-info/5 p-3 text-sm" data-testid="proposition">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <NiveauBadge niveau={decision.niveau} />
        <StatutBadge statut={current} />
        <Link to={`/decisions/${decision.id}`} className="font-mono text-xs text-muted-foreground hover:underline">
          {decision.id}
        </Link>
        {decision.expire && current === "proposee" && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" /> expire {fmtTime(decision.expire)}
          </span>
        )}
      </div>
      <p className="font-medium">
        {proposals.length ? proposals.join(" · ") : what}
      </p>
      <p className="mt-1 text-muted-foreground">
        <RefText text={why} />
      </p>
      {estimation && Object.keys(estimation).length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          Estimation : {estimation.kwh !== undefined && `${fmtNum(estimation.kwh, 3)} kWh `}
          {estimation.litres !== undefined && `${fmtNum(estimation.litres)} L `}
          {estimation.ml !== undefined && `${fmtNum(estimation.ml)} mL`}
        </p>
      )}
      {current === "proposee" && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="ok"
            disabled={repondre.isPending}
            onClick={() => repondre.mutate({ id: decision.id, verbe: "valider" })}
          >
            <Check className="h-3.5 w-3.5" /> Valider
          </Button>
          {rejet ? (
            <>
              <Input
                className="h-7 w-48 py-0.5 text-xs"
                placeholder="motif (optionnel)"
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                autoFocus
              />
              <Button
                size="sm"
                variant="danger"
                disabled={repondre.isPending}
                onClick={() => repondre.mutate({ id: decision.id, verbe: "rejeter", commentaire: motif })}
              >
                Confirmer le rejet
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setRejet(true)}>
              <X className="h-3.5 w-3.5" /> Rejeter
            </Button>
          )}
        </div>
      )}
      {repondre.isError && (
        <div className="mt-2">
          <ErrorBox error={repondre.error} />
        </div>
      )}
    </div>
  );
}
