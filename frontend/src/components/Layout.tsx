import { useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Cpu,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  LogIn,
  LogOut,
  Menu,
  PencilRuler,
  Sprout,
  Zap,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api, ApiError, getToken, setToken } from "@/api/client";
import { useAuth } from "@/api/hooks";
import { useLive } from "@/live/LiveProvider";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Field, Input } from "./ui/input";

const NAV = [
  { to: "/tableau", label: "Tableau de bord", icon: LayoutDashboard },
  { to: "/constructeur", label: "Constructeur", icon: PencilRuler },
  { to: "/equipements", label: "Équipements", icon: Cpu },
  { to: "/consommation", label: "Consommation", icon: Zap },
  { to: "/decisions", label: "Décisions", icon: ListChecks },
  { to: "/arbre", label: "Arbre des actions", icon: GitBranch },
  { to: "/agent", label: "Agent", icon: Bot },
];

export function Layout({ children }: { children: ReactNode }) {
  const [menu, setMenu] = useState(false);
  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 w-56 border-r bg-card p-3 transition-transform md:static md:translate-x-0",
          menu ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="mb-5 flex items-center gap-2 px-2 pt-1 text-lg font-semibold">
          <Sprout className="h-5 w-5 text-primary" /> SerreIA
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setMenu(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted",
                  isActive && "bg-muted font-medium text-primary",
                )
              }
            >
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      {menu && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setMenu(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between gap-2 border-b bg-card px-4">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMenu(true)} aria-label="Menu">
            <Menu className="h-4 w-4" />
          </Button>
          <div className="ml-auto flex items-center gap-3">
            <LiveStatus />
            <AuthButton />
          </div>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

function LiveStatus() {
  const { connected } = useLive();
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground" title="Relais MQTT → WebSocket">
      <span className={cn("h-2 w-2 rounded-full", connected ? "bg-ok" : "bg-muted-foreground/40")} />
      {connected ? "temps réel" : "hors ligne"}
    </span>
  );
}

function AuthButton() {
  const { data: auth } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [token, setTok] = useState(getToken());

  useEffect(() => {
    const onLogin = () => setOpen(true);
    const onAuth = () => {
      setTok(getToken());
      qc.invalidateQueries({ queryKey: ["auth"] });
    };
    window.addEventListener("serreia:login", onLogin);
    window.addEventListener("serreia:auth", onAuth);
    return () => {
      window.removeEventListener("serreia:login", onLogin);
      window.removeEventListener("serreia:auth", onAuth);
    };
  }, [qc]);

  if (!auth?.requise) return null;
  if (token && auth.utilisateur)
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => api("/auth/logout", { method: "POST" }).finally(() => setToken(null))}
      >
        <LogOut className="h-3.5 w-3.5" /> {auth.utilisateur}
      </Button>
    );
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <LogIn className="h-3.5 w-3.5" /> Se connecter
      </Button>
      <LoginDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

function LoginDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [user, setUser] = useState("ui");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ jeton: string }>("/auth/login", {
        body: { mot_de_passe: password, utilisateur: user },
      });
      setToken(r.jeton);
      setPassword("");
      setError(null);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Connexion"
      description="Les actions sur la serre et les modifications de configuration demandent une session."
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label="Utilisateur">
          <Input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" />
        </Field>
        <Field label="Mot de passe" error={error ?? undefined}>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            autoFocus
          />
        </Field>
        <Button type="submit" className="self-end">
          Se connecter
        </Button>
      </form>
    </Dialog>
  );
}
