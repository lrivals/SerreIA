// Manual command (docs/12 §2.2): a `manuelle` decision born `validee`, run by the
// controller through safety.py like any other (docs/10 §1: no command without a decision).
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { useActionManuelle } from "@/api/hooks";
import type { Actionneur } from "@/api/types";
import { ACTUATOR_LABELS } from "@/lib/format";
import { ErrorBox } from "./common";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Field, Input, Select } from "./ui/input";

const schema = z
  .object({
    action: z.enum(["on", "off", "pwm"]),
    valeur: z.union([z.coerce.number().min(0).max(100), z.literal("")]).optional(),
    duree_s: z.union([z.coerce.number().positive("durée > 0"), z.literal("")]).optional(),
    justification: z.string().trim().min(1, "justification obligatoire"),
  })
  .refine((f) => f.action !== "pwm" || (f.valeur !== "" && f.valeur !== undefined), {
    message: "valeur PWM (0–100 %) requise",
    path: ["valeur"],
  });
type Form = z.input<typeof schema>;

export function CommandeManuelle({ actionneur, onClose }: { actionneur: Actionneur; onClose: () => void }) {
  const send = useActionManuelle();
  const { register, handleSubmit, watch, formState } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: { action: "on", valeur: "", duree_s: actionneur.duree_max_s ? String(Math.min(600, actionneur.duree_max_s)) as never : "600" as never, justification: "" },
  });
  const action = watch("action");
  const done = send.data as { id: string } | undefined;

  const submit = (raw: Form) => {
    const f = schema.parse(raw);
    send.mutate({
      zone: actionneur.zone_id,
      actionneur: actionneur.type as never,
      action: f.action,
      valeur: f.action === "pwm" && f.valeur !== "" ? (f.valeur ?? null) : null,
      duree_s: f.action !== "off" && f.duree_s !== "" ? (f.duree_s ?? null) : null,
      justification: f.justification,
    });
  };

  return (
    <Dialog
      open
      onOpenChange={onClose}
      title={`Commande manuelle · ${ACTUATOR_LABELS[actionneur.type] ?? actionneur.type} ${actionneur.zone_id}`}
      description="Crée une décision « manuelle » que le contrôleur exécute après les contrôles de sécurité."
    >
      {done ? (
        <div className="flex flex-col gap-3 text-sm">
          <p className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-ok" /> Décision envoyée au contrôleur :
          </p>
          <Link className="font-mono text-primary hover:underline" to={`/decisions/${done.id}`} onClick={onClose}>
            {done.id}
          </Link>
          <Button className="self-end" onClick={onClose}>
            Fermer
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit(submit)} className="grid grid-cols-2 gap-3">
          <Field label="Action">
            <Select {...register("action")}>
              <option value="on">marche</option>
              <option value="off">arrêt</option>
              {actionneur.commande === "pwm" && <option value="pwm">PWM</option>}
            </Select>
          </Field>
          {action === "pwm" && (
            <Field label="Valeur (%)" error={formState.errors.valeur?.message}>
              <Input {...register("valeur")} inputMode="decimal" />
            </Field>
          )}
          {action !== "off" && (
            <Field
              label={`Durée (s)${actionneur.duree_max_s ? `, max ${actionneur.duree_max_s}` : ""}`}
              error={formState.errors.duree_s?.message}
            >
              <Input {...register("duree_s")} inputMode="numeric" />
            </Field>
          )}
          <Field label="Justification" error={formState.errors.justification?.message} className="col-span-2">
            <Input {...register("justification")} placeholder="ex. test après remplacement du ventilateur" />
          </Field>
          {send.error && (
            <div className="col-span-2">
              <ErrorBox error={send.error} />
            </div>
          )}
          <Button type="submit" className="col-span-2 justify-self-end" disabled={send.isPending}>
            Envoyer
          </Button>
        </form>
      )}
    </Dialog>
  );
}
