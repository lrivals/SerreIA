// Small shared pieces: loading / error states, status badges, clickable references.
import { AlertTriangle, Loader2 } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError, imageUrl } from "@/api/client";
import { Badge, type Tone } from "./ui/badge";

export function Loading({ label = "Chargement…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {msg}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="p-4 text-sm text-muted-foreground">{children}</p>;
}

const STATUT_TONES: Record<string, Tone> = {
  proposee: "info",
  validee: "info",
  executee: "ok",
  terminee: "ok",
  confirmee: "ok",
  creee: "neutral",
  rejetee: "neutral",
  expiree: "neutral",
  annulee: "neutral",
  bloquee_securite: "bad",
  bloquee: "bad",
  echec: "bad",
  non_confirmee: "warn",
  en_attente: "warn",
};

const STATUT_LABELS: Record<string, string> = {
  proposee: "proposée",
  validee: "validée",
  executee: "exécutée",
  terminee: "terminée",
  confirmee: "confirmée",
  creee: "créée",
  rejetee: "rejetée",
  expiree: "expirée",
  annulee: "annulée",
  bloquee_securite: "bloquée (sécurité)",
  bloquee: "bloquée",
  echec: "échec",
  non_confirmee: "non confirmée",
  en_attente: "en attente",
};

export function StatutBadge({ statut }: { statut: string }) {
  return <Badge tone={STATUT_TONES[statut] ?? "neutral"}>{STATUT_LABELS[statut] ?? statut}</Badge>;
}

export const SANTE_TONES: Record<string, Tone> = {
  sain: "ok",
  a_surveiller: "warn",
  malade: "bad",
  isolee: "bad",
  retiree: "neutral",
};

export function SanteBadge({ etat }: { etat: string }) {
  return <Badge tone={SANTE_TONES[etat] ?? "neutral"}>{etat.replace("_", " ")}</Badge>;
}

export function NiveauBadge({ niveau }: { niveau: string }) {
  const tone: Tone = niveau === "0" ? "bad" : niveau === "agent" ? "info" : "neutral";
  const label = /^\d$/.test(niveau) ? `niveau ${niveau}` : niveau;
  return <Badge tone={tone}>{label}</Badge>;
}

// dec-…, z1-A1, image ids (camera + timestamp): links to the matching screens (docs/12 §2.7).
const REF = /(dec-[0-9]{8}-[0-9]{4}-z\d+-[\w]+|\bz\d+-[A-Z]\d+\b|\b[\w-]+-\d{8}T\d{6}\b)/g;

export function RefText({ text }: { text: string }) {
  const parts = text.split(REF);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return <Fragment key={i}>{p}</Fragment>;
        if (p.startsWith("dec-"))
          return (
            <Link key={i} to={`/decisions/${p}`} className="font-mono text-primary underline-offset-2 hover:underline">
              {p}
            </Link>
          );
        if (/^z\d+-[A-Z]\d+$/.test(p))
          return (
            <Link
              key={i}
              to={`/constructeur?zone=${p.split("-")[0]}&emplacement=${p}`}
              className="font-mono text-primary underline-offset-2 hover:underline"
            >
              {p}
            </Link>
          );
        return (
          <a key={i} href={imageUrl(p)} target="_blank" rel="noreferrer" className="font-mono text-primary hover:underline">
            {p}
          </a>
        );
      })}
    </>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}
