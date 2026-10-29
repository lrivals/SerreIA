// Printed-parts configurator (docs/21): scale, families, environment and measured dimensions
// -> parts with material and settings, measurements and test pieces, safety, exports.
// Computed in the browser (src/impression/plan.ts); state kept in localStorage.
import { AlertTriangle, Download, ExternalLink, Info, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PageTitle } from "@/components/common";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  COTE,
  COTES,
  ECHELLES,
  FAMILLES,
  FILAMENTS,
  PRIORITES,
  REGLAGES,
  type Echelle,
  type Famille,
  type Materiau,
  type Priorite,
} from "@/impression/catalogue";
import {
  CONTRAINTES_DEFAUT,
  fmt,
  libelleMateriau,
  planifier,
  versJson,
  versMarkdown,
  versToml,
  type Alerte,
  type Contraintes,
  type Cotes,
} from "@/impression/plan";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

const CLE = "serreia.impression";

interface Etat {
  contraintes: Contraintes;
  cotes: Cotes;
}

function charger(): Etat {
  try {
    const brut = localStorage.getItem(CLE);
    if (brut) {
      const e = JSON.parse(brut) as Partial<Etat>;
      return { contraintes: { ...CONTRAINTES_DEFAUT, ...e.contraintes }, cotes: e.cotes ?? {} };
    }
  } catch {
    // private window, blocked storage: start from the defaults
  }
  return { contraintes: CONTRAINTES_DEFAUT, cotes: {} };
}

function telecharger(nom: string, contenu: string, type: string) {
  const url = URL.createObjectURL(new Blob([contenu], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nom;
  a.click();
  URL.revokeObjectURL(url);
}

const toggle = <T,>(liste: T[], v: T) => (liste.includes(v) ? liste.filter((x) => x !== v) : [...liste, v]);

const PRIO_TONES: Record<Priorite, Tone> = { P0: "bad", P1: "warn", P2: "info", Evolution: "neutral" };
const ALERTE_TONES: Record<Alerte["niveau"], string> = {
  erreur: "border-bad/40 bg-bad/10 text-bad",
  avertissement: "border-warn/40 bg-warn/10",
  info: "border-info/40 bg-info/10",
};

export default function Impression() {
  const [etat, setEtat] = useState<Etat>(charger);
  const [toutes, setToutes] = useState(false);
  const { contraintes: c, cotes } = etat;
  const plan = useMemo(() => planifier(c, cotes), [c, cotes]);
  const date = new Date().toISOString().slice(0, 10);
  const toml = useMemo(() => versToml(plan, date), [plan, date]);

  useEffect(() => {
    try {
      localStorage.setItem(CLE, JSON.stringify(etat));
    } catch {
      // not persisted: the page still works
    }
  }, [etat]);

  const setC = (patch: Partial<Contraintes>) => setEtat((e) => ({ ...e, contraintes: { ...e.contraintes, ...patch } }));
  const setCote = (cle: string, v: string) =>
    setEtat((e) => ({ ...e, cotes: { ...e.cotes, [cle]: v.trim() === "" ? null : Number(v.replace(",", ".")) } }));

  const requises = new Set(plan.lignes.flatMap((l) => [...l.piece.cotes, ...(l.piece.serre ? ["jeu"] : [])]));
  const affichees = COTES.filter((k) => toutes || requises.has(k.cle));

  return (
    <>
      <PageTitle title="Impression 3D">
        <Button variant="outline" size="sm" onClick={() => setEtat({ contraintes: CONTRAINTES_DEFAUT, cotes: {} })}>
          <RotateCcw className="h-3.5 w-3.5" /> Réinitialiser
        </Button>
      </PageTitle>
      <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader title="Contraintes" />
            <CardBody className="flex flex-col gap-3 text-sm">
              <Field label="Échelle de la serre">
                <div className="flex flex-col gap-1">
                  {(Object.keys(ECHELLES) as Echelle[]).map((e) => (
                    <label key={e} className="flex items-center gap-2 text-sm font-normal text-foreground">
                      <input type="radio" name="echelle" checked={c.echelle === e} onChange={() => setC({ echelle: e })} />
                      {ECHELLES[e]}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="Familles">
                <div className="flex flex-col gap-1">
                  {(Object.keys(FAMILLES) as Famille[]).map((f) => (
                    <label key={f} className="flex items-center gap-2 text-sm font-normal text-foreground">
                      <input
                        type="checkbox"
                        checked={c.familles.includes(f)}
                        onChange={() => setC({ familles: toggle(c.familles, f) })}
                      />
                      {f} — {FAMILLES[f]}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="Priorité maximale">
                <Select value={c.prioriteMax} onChange={(e) => setC({ prioriteMax: e.target.value as Priorite })}>
                  {PRIORITES.map((p) => (
                    <option key={p} value={p}>
                      {p === "Evolution" ? "Évolution (tout)" : p}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Environnement">
                <div className="flex flex-col gap-1">
                  <Coche checked={c.exterieur} onChange={(v) => setC({ exterieur: v })}>
                    Serre en extérieur (vent, UV)
                  </Coche>
                  <Coche checked={c.driverProche} onChange={(v) => setC({ driverProche: v })}>
                    Pièces de lampe à &lt; 5 cm d'un driver LED
                  </Coche>
                  <Coche checked={c.canvas} onChange={(v) => setC({ canvas: v })}>
                    Multicouleur CANVAS
                  </Coche>
                </div>
              </Field>
              <Field label="Filaments disponibles">
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {FILAMENTS.map((m: Materiau) => (
                    <Coche key={m} checked={c.filaments.includes(m)} onChange={() => setC({ filaments: toggle(c.filaments, m) })}>
                      {m}
                    </Coche>
                  ))}
                </div>
              </Field>
            </CardBody>
          </Card>
          <Card>
            <CardHeader
              title="Cotes mesurées"
              action={
                <Button variant="ghost" size="sm" onClick={() => setToutes((t) => !t)}>
                  {toutes ? "Utiles seulement" : `Toutes (${COTES.length})`}
                </Button>
              }
            />
            <CardBody className="flex flex-col gap-2.5">
              {affichees.length === 0 && <p className="text-sm text-muted-foreground">Aucune cote pour cette sélection.</p>}
              {affichees.map((k) => {
                const v = cotes[k.cle];
                const msgs = plan.controles.filter((x) => x.cle === k.cle);
                return (
                  <Field
                    key={k.cle}
                    label={k.libelle}
                    className={cn(!requises.has(k.cle) && "opacity-70")}
                  >
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        step="any"
                        inputMode="decimal"
                        aria-label={k.cle}
                        className="w-28"
                        value={typeof v === "number" ? v : ""}
                        placeholder={fmt(k.nominal)}
                        onChange={(e) => setCote(k.cle, e.target.value)}
                      />
                      <span className="text-muted-foreground">{k.unite}</span>
                      <code className="ml-auto text-[11px] text-muted-foreground">{k.cle}</code>
                      {typeof v !== "number" && requises.has(k.cle) && <Badge tone="warn">à mesurer</Badge>}
                    </div>
                    {msgs.map((m) => (
                      <span key={m.message} className={m.niveau === "erreur" ? "text-bad" : "text-warn"}>
                        {m.message}
                      </span>
                    ))}
                  </Field>
                );
              })}
            </CardBody>
          </Card>
        </div>

        <Tabs defaultValue="pieces" className="min-w-0">
          <TabsList className="mb-3">
            <TabsTrigger value="pieces">Pièces ({plan.lignes.length})</TabsTrigger>
            <TabsTrigger value="mesures">
              Mesures ({plan.mesures.length + plan.eprouvettes.length})
            </TabsTrigger>
            <TabsTrigger value="securite">
              Sécurité ({plan.alertes.length + plan.controles.length})
            </TabsTrigger>
            <TabsTrigger value="export">Export</TabsTrigger>
          </TabsList>

          <TabsContent value="pieces">
            <Card>
              {plan.lignes.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">Aucune pièce : cocher au moins une famille.</p>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th>Id</Th>
                      <Th>Pièce</Th>
                      <Th>Matériau</Th>
                      <Th>Réglages</Th>
                      <Th>Cotes</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.lignes.map(({ piece, pertinence, choix }) => {
                      const r = REGLAGES[piece.usage];
                      const ds = plan.derivees.filter((d) => d.pieces.includes(piece.id));
                      return (
                        <tr key={piece.id}>
                          <Td className="font-mono">
                            <div className="flex flex-col items-start gap-1">
                              {piece.id}
                              <Badge tone={PRIO_TONES[piece.priorite]}>{piece.priorite}</Badge>
                            </div>
                          </Td>
                          <Td className="min-w-64">
                            <div className="font-medium">{piece.titre}</div>
                            {pertinence === "partiel" && (
                              <div className="text-xs text-warn">partiel : {piece.partiel}</div>
                            )}
                            {piece.note && <div className="text-xs text-muted-foreground">{piece.note}</div>}
                            {piece.id === "E4" && (
                              <div className="text-xs text-muted-foreground">
                                {c.canvas ? "relief bicolore (CANVAS)" : "relief simple monochrome (pas de CANVAS)"}
                              </div>
                            )}
                            {piece.nePasImprimer && (
                              <div className="text-xs text-bad">ne pas imprimer : {piece.nePasImprimer}</div>
                            )}
                            {piece.logiciel && (
                              <div className="text-xs text-muted-foreground">logiciel : {piece.logiciel}</div>
                            )}
                            {piece.modeles.length > 0 && (
                              <ul className="mt-1 flex flex-col gap-0.5 text-xs">
                                {piece.modeles.map((m) => (
                                  <li key={m.url}>
                                    <a
                                      href={m.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="inline-flex items-center gap-1 text-primary hover:underline"
                                    >
                                      {m.nom} <ExternalLink className="h-3 w-3 shrink-0" />
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </Td>
                          <Td className="whitespace-nowrap">
                            {libelleMateriau(choix)}
                            {choix.manquant && (
                              <div>
                                <Badge tone="bad">filament manquant</Badge>
                              </div>
                            )}
                          </Td>
                          <Td className="text-xs">
                            <div>parois {r.parois}</div>
                            <div>{r.remplissage}</div>
                            {r.remarque && <div className="text-muted-foreground">{r.remarque}</div>}
                          </Td>
                          <Td className="text-xs">
                            {piece.cotes.map((k) => (
                              <div key={k} className="whitespace-nowrap">
                                {k} :{" "}
                                {typeof cotes[k] === "number" ? (
                                  `${fmtNum(cotes[k] as number, 2)} ${COTE[k].unite}`
                                ) : (
                                  <span className="text-warn">à mesurer</span>
                                )}
                              </div>
                            ))}
                            {ds.map((d) => (
                              <div key={d.cle} className="whitespace-nowrap text-muted-foreground">
                                {d.libelle} : {fmtNum(d.valeur, 2)} mm{d.nominale && " *"}
                              </div>
                            ))}
                          </Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              )}
              <p className="px-4 py-2 text-xs text-muted-foreground">* calculée avec au moins une valeur nominale.</p>
            </Card>
          </TabsContent>

          <TabsContent value="mesures" className="flex flex-col gap-4">
            <Card>
              <CardHeader title="Cotes à mesurer" />
              <CardBody>
                {plan.mesures.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Toutes les cotes utiles sont saisies.</p>
                ) : (
                  <ul className="flex flex-col gap-1.5 text-sm">
                    {plan.mesures.map((m) => (
                      <li key={m.cle}>
                        <span className="font-medium">{COTE[m.cle].libelle}</span>{" "}
                        <span className="text-muted-foreground">
                          ({COTE[m.cle].outil}) — bloque {m.pieces.join(", ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Éprouvettes à imprimer d'abord" />
              <CardBody>
                {plan.eprouvettes.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Aucune pièce à ajustement serré.</p>
                ) : (
                  <ol className="list-decimal pl-5 text-sm">
                    {plan.eprouvettes.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ol>
                )}
              </CardBody>
            </Card>
          </TabsContent>

          <TabsContent value="securite" className="flex flex-col gap-2">
            {plan.controles.map((k) => (
              <Bandeau key={k.message} niveau={k.niveau}>
                <code className="mr-1">{k.cle}</code> {k.message}
              </Bandeau>
            ))}
            {plan.alertes.map((a) => (
              <Bandeau key={a.texte} niveau={a.niveau}>
                {a.texte}
              </Bandeau>
            ))}
          </TabsContent>

          <TabsContent value="export">
            <Card>
              <CardHeader
                title="hardware/mesures.toml"
                action={
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => telecharger("mesures.toml", toml, "application/toml")}>
                      <Download className="h-3.5 w-3.5" /> mesures.toml
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => telecharger(`plan-impression-${date}.md`, versMarkdown(plan, date), "text/markdown")}
                    >
                      <Download className="h-3.5 w-3.5" /> .md
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => telecharger(`plan-impression-${date}.json`, versJson(plan, date), "application/json")}
                    >
                      <Download className="h-3.5 w-3.5" /> .json
                    </Button>
                  </div>
                }
              />
              <CardBody>
                <p className="mb-2 text-xs text-muted-foreground">
                  Remplace hardware/mesures.toml du dépôt ; les cotes non mesurées restent en commentaire et gardent leur
                  valeur nominale de hardware/params.py.
                </p>
                <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 text-xs">{toml}</pre>
              </CardBody>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

function Coche({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 text-sm font-normal text-foreground">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

function Bandeau({ niveau, children }: { niveau: Alerte["niveau"]; children: React.ReactNode }) {
  const Icon = niveau === "info" ? Info : AlertTriangle;
  return (
    <div role={niveau === "erreur" ? "alert" : undefined} className={cn("flex items-start gap-2 rounded-md border p-3 text-sm", ALERTE_TONES[niveau])}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{children}</div>
    </div>
  );
}
