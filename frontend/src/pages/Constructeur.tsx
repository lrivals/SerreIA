// Greenhouse builder (docs/12 §2.1): zones, emplacements on a grid, plants dropped from the
// palette, record of an emplacement, camera regions, consistency, publication.
import { zodResolver } from "@hookform/resolvers/zod";
import { Camera as CameraIcon, Gamepad2, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";
import {
  useCameras,
  useCreateEmplacement,
  useCreatePlante,
  useCreateZone,
  useDeplacerPlante,
  usePlan,
  useRecettes,
} from "@/api/hooks";
import type { Disposition, Emplacement, Plante } from "@/api/types";
import { BandeauCoherence, BoutonPublier } from "@/components/ConfigPublication";
import { ErrorBox, Loading, PageTitle } from "@/components/common";
import { EditeurRegions } from "@/components/EditeurRegions";
import { FicheEmplacement } from "@/components/FicheEmplacement";
import { DND_ESPECE, PlanSerre } from "@/components/PlanSerre";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useZoneParam, ZoneTabs } from "@/components/ZoneTabs";
import { especeIcon } from "@/lib/especes";
import { MODES_CULTURE } from "@/lib/format";

type Pending =
  | { kind: "plante"; emplacement: string; espece: string }
  | { kind: "emplacement"; code: string; rangee?: number; colonne?: number }
  | { kind: "zone" }
  | { kind: "regions"; camera: string }
  | null;

export function Constructeur() {
  const [params, setParams] = useSearchParams();
  const zone = useZoneParam(params.get("zone"));
  const selected = params.get("emplacement");
  const { data: plan, isLoading, error } = usePlan(zone);
  const { data: cameras } = useCameras(zone);
  const { data: recettes } = useRecettes();
  const deplacer = useDeplacerPlante();
  const [pending, setPending] = useState<Pending>(() => (params.get("regions") ? { kind: "regions", camera: params.get("regions")! } : null));
  const [autre, setAutre] = useState("");

  const especes = useMemo(() => [...new Set((recettes ?? []).map((r) => r.espece))].sort(), [recettes]);
  const select = (emplacement: string | null) => {
    const next: Record<string, string> = zone ? { zone } : {};
    if (emplacement) next.emplacement = emplacement;
    setParams(next);
  };
  const current = plan?.emplacements.find((e) => e.id === selected);

  return (
    <>
      <PageTitle title={`Constructeur${plan ? ` · ${plan.zone.nom || plan.zone.id}` : ""}`}>
        <Link to="/jeu">
          <Button variant="outline">
            <Gamepad2 className="h-4 w-4" /> Construire en jeu
          </Button>
        </Link>
        <BoutonPublier />
      </PageTitle>
      <BandeauCoherence />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <ZoneTabs value={zone} onChange={(z) => setParams(z ? { zone: z } : {})} />
        <Button variant="outline" size="sm" onClick={() => setPending({ kind: "zone" })}>
          <Plus className="h-3.5 w-3.5" /> Zone
        </Button>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {deplacer.error && <ErrorBox error={deplacer.error} />}
      {plan && (
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <div className="flex flex-col gap-4">
            <Card>
              <CardBody>
                <PlanSerre
                  emplacements={plan.emplacements}
                  selected={selected}
                  onSelect={select}
                  onDropEspece={(emplacement, espece) => setPending({ kind: "plante", emplacement, espece })}
                  onMovePlante={(plante, emplacement) => deplacer.mutate({ id: plante, emplacement })}
                  onCreateAt={(code, rangee, colonne) => setPending({ kind: "emplacement", code, rangee, colonne })}
                />
                <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
                  <span><span className="text-ok">●</span> sain</span>
                  <span><span className="text-warn">▲</span> à surveiller</span>
                  <span><span className="text-bad">✖</span> malade / isolée</span>
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Palette" />
              <CardBody className="flex flex-wrap items-center gap-2">
                {especes.map((e) => (
                  <span
                    key={e}
                    draggable
                    onDragStart={(ev) => ev.dataTransfer.setData(DND_ESPECE, e)}
                    className="cursor-grab rounded-md border bg-card px-2.5 py-1 text-sm select-none hover:border-primary active:cursor-grabbing"
                    data-testid={`palette-${e}`}
                  >
                    {especeIcon(e)} {e}
                  </span>
                ))}
                <span className="flex items-center gap-1">
                  <Input
                    className="h-8 w-36"
                    placeholder="autre espèce"
                    value={autre}
                    onChange={(ev) => setAutre(ev.target.value.toLowerCase())}
                  />
                  {autre && (
                    <span
                      draggable
                      onDragStart={(ev) => ev.dataTransfer.setData(DND_ESPECE, autre)}
                      className="cursor-grab rounded-md border border-dashed px-2.5 py-1 text-sm"
                    >
                      {especeIcon(autre)} {autre}
                    </span>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">Glisser une espèce sur un emplacement vide ; glisser une plante pour la déplacer.</span>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Caméras de la zone" />
              <CardBody className="flex flex-wrap gap-2">
                {cameras?.length === 0 && <span className="text-sm text-muted-foreground">Aucune caméra.</span>}
                {cameras?.map((c) => (
                  <Button key={c.id} variant="outline" size="sm" onClick={() => setPending({ kind: "regions", camera: c.id })}>
                    <CameraIcon className="h-3.5 w-3.5" /> {c.id} · {c.regions.filter((r) => r.bbox).length}/{c.regions.length} régions
                  </Button>
                ))}
              </CardBody>
            </Card>
          </div>
          {current ? (
            <FicheEmplacement key={current.id} e={current} onClose={() => select(null)} />
          ) : (
            <p className="text-sm text-muted-foreground">Cliquer sur un emplacement pour ouvrir sa fiche.</p>
          )}
        </div>
      )}

      {pending?.kind === "plante" && (
        <NouvellePlante {...pending} onClose={() => setPending(null)} onCreated={() => select(pending.emplacement)} />
      )}
      {pending?.kind === "emplacement" && zone && <NouvelEmplacement {...pending} zone={zone} onClose={() => setPending(null)} />}
      {pending?.kind === "zone" && (
        <NouvelleZone
          onClose={() => setPending(null)}
          onCreated={(id) => {
            setPending(null);
            setParams({ zone: id });
          }}
        />
      )}
      {pending?.kind === "regions" && plan && cameras && (
        <EditeurRegions
          open
          onOpenChange={() => setPending(null)}
          camera={cameras.find((c) => c.id === pending.camera)!}
          emplacements={plan.emplacements}
        />
      )}
    </>
  );
}

// --- dialogs -----------------------------------------------------------------------------

const planteSchema = z.object({
  espece: z.string().min(1, "espèce requise").max(64),
  variete: z.string().max(128).optional(),
  recette_id: z.string().optional(),
  stade: z.string().min(1, "stade requis").max(16),
  date_plantation: z.string().optional(),
  prioritaire: z.boolean(),
});
type PlanteForm = z.infer<typeof planteSchema>;

const STADES = ["semis", "croissance", "floraison", "fructification"];

export function NouvellePlante({
  emplacement,
  espece,
  onClose,
  onCreated,
}: {
  emplacement: string;
  espece: string;
  onClose: () => void;
  onCreated: (p: Plante) => void;
}) {
  const { data: recettes } = useRecettes();
  const create = useCreatePlante();
  const candidates = (recettes ?? []).filter((r) => r.espece === espece);
  const { register, handleSubmit, watch, formState } = useForm<PlanteForm>({
    resolver: zodResolver(planteSchema),
    defaultValues: {
      espece,
      recette_id: candidates[0]?.id ?? "",
      stade: candidates[0] ? Object.keys(candidates[0].stades)[0] : "semis",
      date_plantation: new Date().toISOString().slice(0, 10),
      prioritaire: false,
    },
  });
  const recette = recettes?.find((r) => r.id === watch("recette_id"));
  const stades = recette ? Object.keys(recette.stades) : STADES;

  const submit = (f: PlanteForm) =>
    create.mutate(
      {
        espece: f.espece,
        variete: f.variete || null,
        recette_id: f.recette_id || null,
        stade: f.stade,
        date_plantation: f.date_plantation || null,
        prioritaire: f.prioritaire,
        emplacement,
      },
      {
        onSuccess: (p) => {
          onCreated(p);
          onClose();
        },
      },
    );

  return (
    <Dialog open onOpenChange={onClose} title={`Nouvelle plante sur ${emplacement}`}>
      <form onSubmit={handleSubmit(submit)} className="grid grid-cols-2 gap-3">
        <Field label="Espèce" error={formState.errors.espece?.message}>
          <Input {...register("espece")} />
        </Field>
        <Field label="Variété">
          <Input {...register("variete")} placeholder="Cœur de bœuf" />
        </Field>
        <Field label="Recette">
          <Select {...register("recette_id")}>
            <option value="">— aucune (hors consignes)</option>
            {(recettes ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} ({r.espece})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Stade" error={formState.errors.stade?.message}>
          <Select {...register("stade")}>
            {stades.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </Field>
        <Field label="Date de plantation">
          <Input type="date" {...register("date_plantation")} />
        </Field>
        <label className="flex items-center gap-2 self-end pb-2 text-sm">
          <input type="checkbox" {...register("prioritaire")} /> prioritaire
        </label>
        {create.error && (
          <div className="col-span-2">
            <ErrorBox error={create.error} />
          </div>
        )}
        <Button type="submit" className="col-span-2 justify-self-end" disabled={create.isPending}>
          Planter
        </Button>
      </form>
    </Dialog>
  );
}

const emplacementSchema = z.object({
  code: z.string().regex(/^[A-Za-z0-9]{1,12}$/, "lettres et chiffres, ex. B3"),
  mode_culture: z.enum(MODES_CULTURE),
  contenant_type: z.string().max(32).optional(),
  volume_l: z.union([z.coerce.number().positive("volume > 0"), z.literal("")]).optional(),
  materiau: z.string().max(32).optional(),
});
type EmplacementForm = z.input<typeof emplacementSchema>;

export function NouvelEmplacement({
  zone,
  code,
  rangee,
  colonne,
  contenant = "pot",
  modeCulture = "terre",
  disposition,
  onClose,
  onCreated,
}: {
  zone: string;
  code: string;
  rangee?: number;
  colonne?: number;
  contenant?: string;
  modeCulture?: (typeof MODES_CULTURE)[number];
  disposition?: Disposition;
  onClose: () => void;
  onCreated?: (e: Emplacement) => void;
}) {
  const create = useCreateEmplacement();
  const { register, handleSubmit, formState } = useForm<EmplacementForm>({
    resolver: zodResolver(emplacementSchema),
    defaultValues: { code, mode_culture: modeCulture, contenant_type: contenant, volume_l: "", materiau: "" },
  });
  const submit = (raw: EmplacementForm) => {
    const f = emplacementSchema.parse(raw);
    create.mutate(
      {
        zone_id: zone,
        code: f.code,
        mode_culture: f.mode_culture,
        rangee: rangee ?? null,
        colonne: colonne ?? null,
        contenant: f.contenant_type
          ? { type: f.contenant_type, volume_l: f.volume_l === "" ? null : (f.volume_l ?? null), materiau: f.materiau || null }
          : null,
        disposition: disposition ?? null,
      },
      {
        onSuccess: (e) => {
          onCreated?.(e);
          onClose();
        },
      },
    );
  };
  return (
    <Dialog open onOpenChange={onClose} title={`Nouvel emplacement dans ${zone}`}>
      <form onSubmit={handleSubmit(submit)} className="grid grid-cols-2 gap-3">
        <Field label="Code" error={formState.errors.code?.message}>
          <Input {...register("code")} />
        </Field>
        <Field label="Mode de culture">
          <Select {...register("mode_culture")}>
            {MODES_CULTURE.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </Field>
        <Field label="Contenant">
          <Input {...register("contenant_type")} placeholder="pot, jardinière, canal_NFT…" />
        </Field>
        <Field label="Volume (L)" error={formState.errors.volume_l?.message}>
          <Input {...register("volume_l")} inputMode="decimal" />
        </Field>
        <Field label="Matériau">
          <Input {...register("materiau")} placeholder="plastique, terre cuite…" />
        </Field>
        {create.error && (
          <div className="col-span-2">
            <ErrorBox error={create.error} />
          </div>
        )}
        <Button type="submit" className="col-span-2 justify-self-end" disabled={create.isPending}>
          Créer
        </Button>
      </form>
    </Dialog>
  );
}

const zoneSchema = z.object({
  nom: z.string().max(128),
  jour_debut: z.string().regex(/^\d{2}:\d{2}$/, "HH:MM"),
});

export function NouvelleZone({
  disposition,
  onClose,
  onCreated,
}: {
  disposition?: Disposition;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const create = useCreateZone();
  const { register, handleSubmit, formState } = useForm<z.infer<typeof zoneSchema>>({
    resolver: zodResolver(zoneSchema),
    defaultValues: { nom: "", jour_debut: "06:00" },
  });
  return (
    <Dialog open onOpenChange={onClose} title="Nouvelle zone">
      <form
        onSubmit={handleSubmit((f) => create.mutate({ ...f, disposition: disposition ?? null }, { onSuccess: (z) => onCreated(z.id) }))}
        className="flex flex-col gap-3"
      >
        <Field label="Nom">
          <Input {...register("nom")} placeholder="Semis, Hydro NFT…" />
        </Field>
        <Field label="Début du jour (photopériode)" error={formState.errors.jour_debut?.message}>
          <Input type="time" {...register("jour_debut")} />
        </Field>
        {create.error && <ErrorBox error={create.error} />}
        <Button type="submit" className="self-end" disabled={create.isPending}>
          Créer
        </Button>
      </form>
    </Dialog>
  );
}
