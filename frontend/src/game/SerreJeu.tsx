// Game view in pixel art (docs/13): the same greenhouse as the classic UI, built tile by
// tile and brought to life by a gardener who replays the real events. Phaser draws, React
// owns the data (TanStack Query), the overlays and every API call. `/jeu?demo=1`: offline
// demonstration from public/demo/serre-demo.json; `/jeu?demo=journee`: the frozen history
// of a simulated scenario (docs/16, `make scenario-figer NOM=journee`).
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { Actionneur, Disposition, EmplacementPlan, Tableau, Tuile } from "@/api/types";
import { ChatAgent } from "@/components/ChatAgent";
import { CommandeManuelle } from "@/components/CommandeManuelle";
import { BandeauCoherence, BoutonPublier } from "@/components/ConfigPublication";
import { ErrorBox, Loading } from "@/components/common";
import { FicheEmplacement } from "@/components/FicheEmplacement";
import { Dialog } from "@/components/ui/dialog";
import { useLive, type LiveEvent } from "@/live/LiveProvider";
import { NouvelEmplacement, NouvellePlante, NouvelleZone } from "@/pages/Constructeur";
import { creerBus, type Outil } from "./bus";
import { useDonneesApi, useDonneesDemo, type Source } from "./donnees";
import { portraitJardinier } from "./mapping";
import { construireMonde, groupeCapteurs, type Donnees, type Ref } from "./monde";
import { PhaserVue, type PhaserApi } from "./PhaserVue";
import { FileTaches, tachesDe, type Contexte, type Tache } from "./tasks/fileTaches";
import { BarreEtat } from "./ui/BarreEtat";
import { BulleDialogue } from "./ui/BulleDialogue";
import { FormulaireEquipement } from "./ui/FormulaireEquipement";
import { DND_JEU, Inventaire, type Article } from "./ui/Inventaire";
import { SerrePhone } from "./ui/SerrePhone";
import { SpriteIcone } from "./ui/SpriteIcone";
import "./ui/pixel.css";
import { useConstruction } from "./useConstruction";
import { useRejeu } from "./useRejeu";

export default function SerreJeu() {
  const [params] = useSearchParams();
  const demo = params.get("demo");
  return demo ? <JeuDemo nom={demo} /> : <JeuApi />;
}

function JeuApi() {
  const [construction, setConstruction] = useState(false);
  const source = useDonneesApi(construction);
  return <Jeu source={source} setConstruction={setConstruction} />;
}

function JeuDemo({ nom }: { nom: string }) {
  const source = useDonneesDemo(nom);
  return <Jeu source={source} setConstruction={() => undefined} demo={source.evenements} />;
}

type Mode = "vivant" | "construction" | "rejeu";

function Jeu({
  source,
  setConstruction,
  demo,
}: {
  source: Source;
  setConstruction: (c: boolean) => void;
  demo?: { t: number; evenement: LiveEvent }[];
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const live = useLive();
  const bus = useMemo(creerBus, []);
  const file = useMemo(() => new FileTaches(), []);
  const phaser = useRef<PhaserApi>(null);
  const [mode, setModeState] = useState<Mode>("vivant");
  const [outil, setOutil] = useState<Outil>("poser");
  const [selection, setSelection] = useState<Ref | null>(null);
  const [fiche, setFiche] = useState<EmplacementPlan | null>(null);
  const [commande, setCommande] = useState<Actionneur | null>(null);
  const [phone, setPhone] = useState(false);
  const [jardinier, setJardinier] = useState<{ message: string } | null>(null);
  const [conversation, setConversation] = useState<string | null>(null);
  const [tache, setTache] = useState<Tache | null>(null);
  const [zoneInv, setZoneInv] = useState<string | null>(null);
  const [reduire, setReduire] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  const [etatsLive, setEtatsLive] = useState<Record<string, { action: string; valeur: number | null; ts: string }>>({});
  const [noeudsLive, setNoeudsLive] = useState<Record<string, "online" | "offline">>({});
  const [maintenant, setMaintenant] = useState(() => Date.now());
  const lectureSeule = source.lectureSeule;

  const zones = useMemo(() => (source.donnees?.zones ?? []).map((z) => z.id), [source.donnees?.zones]);
  const rejeu = useRejeu(zones, (evts) => evts.forEach((e) => recevoir(e.evenement, e.ts)));

  const setMode = (m: Mode) => {
    setModeState(m);
    setConstruction(m === "construction");
    rejeu.setActif(m === "rejeu");
    setSelection(null);
  };

  // --- data: live actuator states, replay overrides ----------------------------------
  const donnees: Donnees | null = useMemo(() => {
    const d = source.donnees;
    if (!d) return null;
    const actionneurs = d.actionneurs.map((a) => {
      if (rejeu.actifs) return { ...a, etat: { ts: new Date(rejeu.etat.t).toISOString(), action: rejeu.actifs.has(`${a.zone_id}:${a.type}`) ? "on" : "off", valeur: null } };
      const l = etatsLive[`${a.zone_id}:${a.type}`];
      return l && (!a.etat || l.ts >= a.etat.ts) ? { ...a, etat: l } : a;
    });
    const tableaux = rejeu.etat.actif
      ? Object.fromEntries(Object.entries(d.tableaux).map(([z, t]) => [z, t && rejouerTableau(t, (type) => rejeu.valeur(z, type))]))
      : d.tableaux;
    const noeuds = d.noeuds.map((n) => (noeudsLive[n.id] ? { ...n, status: noeudsLive[n.id] } : n));
    return { ...d, actionneurs, tableaux, noeuds };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.donnees, etatsLive, noeudsLive, rejeu.actifs && [...rejeu.actifs].join(), rejeu.etat.actif && Math.floor(rejeu.etat.t / 900_000)]);

  const monde = useMemo(() => (donnees ? construireMonde(donnees) : null), [donnees]);
  useEffect(() => {
    if (monde) bus.emit("donnees:maj", monde);
  }, [bus, monde]);

  // --- live events → objects at once, gardener's tasks afterwards ----------------------
  const ref = useRef(donnees);
  ref.current = donnees;
  const contexte: Contexte = useMemo(
    () => ({
      actionneur: (zone, type) => ref.current?.actionneurs.find((a) => a.zone_id === zone && a.type === type)?.id ?? null,
      emplacementsCamera: (camera) => ref.current?.cameras.find((c) => c.id === camera)?.regions.map((r) => r.emplacement_id) ?? [],
      capteurNoeud: (noeud) => groupeCapteurs(ref.current?.capteurs ?? []).find((g) => g.canaux.some((c) => c.noeud === noeud))?.id ?? null,
    }),
    [],
  );
  const recevoir = useCallback(
    (e: LiveEvent, ts = Date.now()) => {
      if (e.kind === "etat" && e.zone && e.subject) {
        const p = e.payload as { action: string; valeur?: number | null; ts?: string };
        setEtatsLive((s) => ({ ...s, [`${e.zone}:${e.subject}`]: { action: p.action, valeur: p.valeur ?? null, ts: p.ts ?? new Date(ts).toISOString() } }));
      }
      if (e.kind === "status" && e.subject && (e.payload === "online" || e.payload === "offline"))
        setNoeudsLive((s) => ({ ...s, [e.subject!]: e.payload as "online" | "offline" }));
      for (const t of tachesDe(e, contexte, Date.now())) file.ajouter(t);
      bus.emit("live:evenement", { evenement: e, ts });
    },
    [bus, contexte, file],
  );
  useEffect(() => {
    if (demo || mode === "rejeu") return;
    return live.subscribe((e) => recevoir(e));
  }, [live, recevoir, demo, mode]);
  // demonstration: the events of the file, in a loop
  useEffect(() => {
    if (!demo?.length) return;
    const duree = Math.max(...demo.map((x) => x.t)) + 20;
    const timers: number[] = [];
    const cycle = () => {
      setEtatsLive({});
      setNoeudsLive({});
      for (const x of demo) timers.push(window.setTimeout(() => recevoir(x.evenement), x.t * 1000));
      timers.push(window.setTimeout(cycle, duree * 1000));
    };
    cycle();
    return () => timers.forEach(window.clearTimeout);
  }, [demo, recevoir]);

  // a decision validated or rejected: its "to validate" task is no longer needed
  const propositions = donnees?.propositions.map((p) => p.id).join();
  useEffect(() => {
    if (propositions === undefined) return;
    const restantes = new Set(ref.current?.propositions.map((p) => p.explication));
    file.retirer((t) => t.action === "noter" && t.persistante && ![...restantes].some((x) => t.texte.includes(x)));
  }, [propositions, file]);

  // --- clock: local time of the greenhouse, or the replay clock ------------------------
  useEffect(() => {
    const id = window.setInterval(() => setMaintenant(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const fuseau = donnees?.serre?.fuseau ?? "Europe/Paris";
  const instant = rejeu.etat.actif && rejeu.etat.chrono ? rejeu.etat.t : maintenant;
  const { heure, libelle } = heureLocale(instant, fuseau);
  useEffect(() => {
    bus.emit("horloge:heure", { heure });
  }, [bus, heure]);
  useEffect(() => {
    bus.emit("reduire:animations", reduire);
  }, [bus, reduire]);
  useEffect(() => {
    bus.emit("mode:construction", { actif: mode === "construction", outil });
  }, [bus, mode, outil]);

  // end-to-end tests (browser driven by automation only): the world and the screen point of
  // a tile, to drop the inventory on the canvas
  useEffect(() => {
    if (!navigator.webdriver) return;
    const w = window as unknown as { __serreJeu?: unknown };
    w.__serreJeu = { monde: () => etatScene.current.monde, ecran: (x: number, y: number) => phaser.current?.ecranDeCase(x, y) ?? null };
    return () => void delete w.__serreJeu;
  }, []);

  // the scene may start after these were sent: send them again once it is ready
  const etatScene = useRef({ heure, reduire, mode, outil, monde });
  etatScene.current = { heure, reduire, mode, outil, monde };
  useEffect(() => {
    const pret = () => {
      const e = etatScene.current;
      if (e.monde) bus.emit("donnees:maj", e.monde);
      bus.emit("horloge:heure", { heure: e.heure });
      bus.emit("reduire:animations", e.reduire);
      bus.emit("mode:construction", { actif: e.mode === "construction", outil: e.outil });
    };
    bus.on("scene:prete", pret);
    return () => bus.off("scene:prete", pret);
  }, [bus]);

  // configuration published: the gardener brings the envelope to the Pi
  const version = donnees?.serre?.config_version;
  const versionPrec = useRef(version);
  useEffect(() => {
    if (versionPrec.current !== undefined && version !== undefined && version > versionPrec.current) bus.emit("jardinier:enveloppe");
    versionPrec.current = version;
  }, [bus, version]);

  // --- gestures from Phaser ------------------------------------------------------------
  const constr = useConstruction(monde, donnees);
  const etatJeu = useRef({ mode, outil, constr });
  etatJeu.current = { mode, outil, constr };
  useEffect(() => {
    const clic = (r: Ref) => {
      const { mode, outil, constr } = etatJeu.current;
      if (mode === "construction" && outil === "gomme") constr.gomme(r);
      else setSelection(r);
    };
    const deplace = ({ ref, x, y }: { ref: Ref; x: number; y: number }) => etatJeu.current.constr.deplace(ref, x, y);
    const zone = (d: Disposition) => etatJeu.current.constr.setDialogue({ kind: "zone", disposition: d });
    const parler = () => setJardinier({ message: "" });
    bus.on("objet:clic", clic);
    bus.on("objet:deplace", deplace);
    bus.on("construction:zone", zone);
    bus.on("jardinier:clic", parler);
    bus.on("jardinier:tache", setTache);
    return () => {
      bus.off("objet:clic", clic);
      bus.off("objet:deplace", deplace);
      bus.off("construction:zone", zone);
      bus.off("jardinier:clic", parler);
      bus.off("jardinier:tache", setTache);
    };
  }, [bus]);

  const surDrop = (e: DragEvent) => {
    const brut = e.dataTransfer.getData(DND_JEU);
    bus.emit("construction:survol", null);
    if (!brut) return;
    e.preventDefault();
    const c = phaser.current?.caseEcran(e.clientX, e.clientY);
    if (c) constr.depot(JSON.parse(brut) as Article, c.x, c.y);
  };

  if (source.chargement) return <Loading label="Chargement de la serre…" />;
  if (source.erreur) return <ErrorBox error={source.erreur} />;
  if (!donnees) return null;
  const dialogue = constr.dialogue;
  const fermer = () => constr.setDialogue(null);

  return (
    <div className="jeu -m-4 flex h-[calc(100vh-3rem)] flex-col md:-m-6">
      <BarreEtat
        donnees={donnees}
        conso={source.conso}
        heure={libelle}
        rejeu={rejeu.etat.actif ? `${libelle} · ×${rejeu.etat.vitesse}` : null}
        tache={tache}
        connecte={live.connected || !!demo}
        onPropositions={() => navigate("/decisions?statut=proposee")}
        onPhone={() => setPhone(!phone)}
      />
      <div className="flex min-h-0 flex-1">
      {mode === "construction" && (
        <div className="overflow-y-auto bg-[#2f3b2a] p-2">
          <Inventaire zones={donnees.zones} plans={donnees.plans} zone={zoneInv ?? donnees.zones[0]?.id ?? null} onZone={setZoneInv} onGlisser={() => setOutil("poser")} />
        </div>
      )}
      <div
        className="relative min-w-0 flex-1 overflow-hidden"
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes(DND_JEU)) return;
          e.preventDefault();
          bus.emit("construction:survol", { clientX: e.clientX, clientY: e.clientY });
        }}
        onDragLeave={() => bus.emit("construction:survol", null)}
        onDrop={surDrop}
      >
        <PhaserVue ref={phaser} bus={bus} file={file} monde={monde} reduire={reduire} className="absolute inset-0" />

        {mode === "construction" && (
          <div className="absolute top-2 right-2 w-[min(420px,calc(100%-1rem))] text-sm">
            <BandeauCoherence />
            {constr.message && (
              <div role="alert" className="px-panel px-font mb-2 p-1 text-[9px]">
                {constr.message}
              </div>
            )}
          </div>
        )}
        {phone && (
          <div className="absolute top-2 right-2">
            <SerrePhone
              onFermer={() => setPhone(false)}
              reduire={reduire}
              onReduire={setReduire}
              onJardinier={() => {
                setPhone(false);
                setJardinier({ message: "" });
              }}
            />
          </div>
        )}
        {selection && (
          <div className="absolute bottom-16 left-1/2 -translate-x-1/2">
            <BulleDialogue
              cible={selection}
              donnees={donnees}
              conso={source.conso}
              reduire={reduire}
              lectureSeule={lectureSeule}
              onFermer={() => setSelection(null)}
              onFiche={lectureSeule ? undefined : setFiche}
              onAgent={lectureSeule ? undefined : (message) => setJardinier({ message })}
              onCommande={(id) => setCommande(donnees.actionneurs.find((a) => a.id === id) ?? null)}
            />
          </div>
        )}
        <div className="absolute right-2 bottom-2 flex flex-col gap-1">
          <button className="px-btn" onClick={() => bus.emit("camera:zoom", 1)} aria-label="Zoomer">
            +
          </button>
          <button className="px-btn" onClick={() => bus.emit("camera:zoom", -1)} aria-label="Dézoomer">
            −
          </button>
        </div>
      </div>
      </div>

      <div className="px-bar px-font flex flex-wrap items-center gap-2 px-2 py-2 text-[9px]">
        {!lectureSeule && (
          <button className="px-btn" aria-pressed={mode === "construction"} onClick={() => setMode(mode === "construction" ? "vivant" : "construction")}>
            🔨 Construire
          </button>
        )}
        <button className="px-btn" aria-pressed={mode === "vivant"} onClick={() => setMode("vivant")}>
          ▶ Serre vivante
        </button>
        {!lectureSeule && (
          <button className="px-btn" aria-pressed={mode === "rejeu"} onClick={() => setMode(mode === "rejeu" ? "vivant" : "rejeu")}>
            ⏪ Rejouer
          </button>
        )}
        {mode === "construction" && (
          <>
            <span className="mx-1 opacity-50">|</span>
            {(
              [
                ["poser", "✋ Poser"],
                ["deplacer", "↔ Déplacer"],
                ["gomme", "🧽 Gomme"],
                ["zone", "▦ Zone"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} className="px-btn" aria-pressed={outil === k} onClick={() => setOutil(k)}>
                {l}
              </button>
            ))}
            <button className="px-btn" disabled={!constr.peutAnnuler} onClick={constr.annuler} title={constr.dernier ? `annuler : ${constr.dernier}` : undefined}>
              ↶ Annuler
            </button>
            <button className="px-btn" disabled={!constr.peutRetablir} onClick={constr.retablir}>
              ↷ Rétablir
            </button>
            <span className="ml-auto">
              <BoutonPublier />
            </span>
          </>
        )}
        {mode === "rejeu" && (
          <>
            <span className="mx-1 opacity-50">|</span>
            {(["24h", "7j"] as const).map((p) => (
              <button key={p} className="px-btn" aria-pressed={rejeu.etat.periode === p} onClick={() => rejeu.setPeriode(p)}>
                {p === "24h" ? "24 h" : "7 j"}
              </button>
            ))}
            {([60, 600] as const).map((v) => (
              <button key={v} className="px-btn" aria-pressed={rejeu.etat.vitesse === v} onClick={() => rejeu.setVitesse(v)}>
                ×{v}
              </button>
            ))}
            <button className="px-btn" onClick={() => rejeu.setLecture(!rejeu.etat.lecture)}>
              {rejeu.etat.lecture ? "⏸ Pause" : "▶ Lecture"}
            </button>
            {rejeu.etat.chrono && (
              <input
                type="range"
                className="min-w-40 flex-1"
                min={rejeu.etat.chrono.debut}
                max={rejeu.etat.chrono.fin}
                value={rejeu.etat.t}
                onChange={(e) => rejeu.aller(Number(e.target.value))}
                aria-label="Instant du rejeu"
              />
            )}
            {rejeu.etat.chargement && <span>chargement…</span>}
            {rejeu.etat.chrono && <span>{rejeu.etat.chrono.evenements.filter((e) => e.evenement.kind === "decision").length} décisions</span>}
          </>
        )}
        <Link to="/tableau" className="px-btn ml-auto">
          Vue classique
        </Link>
      </div>

      {/* --- dialogs ------------------------------------------------------------------ */}
      {fiche && (
        <Dialog open onOpenChange={() => setFiche(null)} title={`Fiche ${fiche.id}`} className="w-[min(640px,calc(100vw-32px))]">
          <FicheEmplacement e={donnees.plans.flatMap((p) => p.emplacements).find((e) => e.id === fiche.id) ?? fiche} onClose={() => setFiche(null)} />
        </Dialog>
      )}
      {commande && <CommandeManuelle actionneur={commande} onClose={() => setCommande(null)} />}
      {jardinier && (
        <Dialog
          open
          onOpenChange={() => setJardinier(null)}
          title={
            <span className="flex items-center gap-2">
              <SpriteIcone frame={portraitJardinier()} label="le jardinier" /> Le jardinier
            </span>
          }
          description="Il incarne l'agent : mêmes outils, mêmes garde-fous, il ne fait que proposer."
          className="w-[min(760px,calc(100vw-32px))]"
        >
          <ChatAgent
            key={jardinier.message}
            className="h-[60vh]"
            conversationId={conversation}
            onConversation={setConversation}
            messageInitial={jardinier.message}
          />
        </Dialog>
      )}
      {dialogue?.kind === "emplacement" && (
        <NouvelEmplacement
          zone={dialogue.zone}
          code={dialogue.code}
          rangee={dialogue.rangee}
          colonne={dialogue.colonne}
          contenant={dialogue.contenant}
          modeCulture={dialogue.mode as never}
          disposition={dialogue.disposition}
          onClose={fermer}
          onCreated={(e) => constr.cree(`poser ${e.id}`, `/emplacements/${e.id}`)}
        />
      )}
      {dialogue?.kind === "plante" && (
        <NouvellePlante
          emplacement={dialogue.emplacement}
          espece={dialogue.espece}
          onClose={fermer}
          onCreated={(p) => constr.planteCreee(p.id, dialogue.emplacement)}
        />
      )}
      {dialogue?.kind === "equipement" && (
        <FormulaireEquipement
          article={dialogue.article}
          zone={dialogue.zone}
          disposition={dialogue.disposition}
          emplacements={donnees.plans.find((p) => p.zone.id === dialogue.zone)?.emplacements.map((e) => e.id) ?? []}
          onClose={fermer}
          onCreated={(c) => constr.cree(`poser ${c.id}`, `/${c.genre === "camera" ? "cameras" : c.genre === "capteur" ? "capteurs" : "actionneurs"}/${encodeURIComponent(c.id)}`)}
        />
      )}
      {dialogue?.kind === "zone" && (
        <NouvelleZone
          disposition={dialogue.disposition}
          onClose={fermer}
          onCreated={(id) => {
            constr.zoneCreee(id, dialogue.disposition);
            fermer();
            qc.invalidateQueries({ queryKey: ["zones"] });
          }}
        />
      )}
      {dialogue?.kind === "confirmer" && <Confirmation texte={dialogue.texte} executer={dialogue.executer} onClose={fermer} />}
    </div>
  );
}

function Confirmation({ texte, executer, onClose }: { texte: string; executer: () => Promise<void>; onClose: () => void }) {
  const [erreur, setErreur] = useState<unknown>(null);
  const [enCours, setEnCours] = useState(false);
  return (
    <Dialog open onOpenChange={onClose} title="Confirmer">
      <p className="mb-3 text-sm">{texte}</p>
      {erreur ? <ErrorBox error={erreur} /> : null}
      <div className="mt-3 flex justify-end gap-2">
        <button className="px-btn px-font" onClick={onClose}>
          Annuler
        </button>
        <button
          className="px-btn px-font"
          disabled={enCours}
          onClick={async () => {
            setEnCours(true);
            try {
              await executer();
              onClose();
            } catch (e) {
              setErreur(e);
            } finally {
              setEnCours(false);
            }
          }}
        >
          Confirmer
        </button>
      </div>
    </Dialog>
  );
}

/** Hour (decimal) and label of an instant in the time zone of the greenhouse. */
export function heureLocale(ts: number, fuseau: string): { heure: number; libelle: string } {
  try {
    const parts = new Intl.DateTimeFormat("fr-FR", { timeZone: fuseau, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ts));
    const h = Number(parts.find((p) => p.type === "hour")?.value ?? 12);
    const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
    return { heure: h + m / 60, libelle: `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}` };
  } catch {
    const d = new Date(ts);
    return { heure: d.getHours() + d.getMinutes() / 60, libelle: d.toTimeString().slice(0, 5) };
  }
}

/** Dashboard of a zone at a replay instant: air values from the measured series. */
function rejouerTableau(t: Tableau, valeur: (type: "humidite" | "temperature") => number | null): Tableau {
  return {
    ...t,
    mesures: t.mesures.map((m): Tuile => {
      if ((m.type !== "humidite" && m.type !== "temperature") || m.emplacement) return m;
      const v = valeur(m.type);
      if (v == null) return m;
      const statut = !m.plage ? "inconnu" : v < m.plage[0] || v > m.plage[1] ? "attention" : "ok";
      return { ...m, valeur: v, statut };
    }),
  };
}
