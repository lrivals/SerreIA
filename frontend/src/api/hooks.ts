// TanStack Query hooks, one per resource (docs/12 §3). Query keys start with the resource
// name so that the live relay (live/LiveProvider) can invalidate them by kind.
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Actionneur,
  Alerte,
  Camera,
  Capteur,
  Coherence,
  ConfigDiff,
  Consommation,
  Contenant,
  Conversation,
  Cuve,
  ConversationDetail,
  DecisionRecord,
  DecisionSummary,
  Emplacement,
  Historique,
  Mesures,
  Noeud,
  Plante,
  Publication,
  Recette,
  Schemas,
  Serre,
  Tableau,
  TreeNode,
  VisionRow,
  Zone,
  ZonePlan,
} from "./types";

type Params = Record<string, unknown>;

export const useSerres = () => useQuery({ queryKey: ["serres"], queryFn: () => api<Serre[]>("/serres") });
export const useZones = () => useQuery({ queryKey: ["zones"], queryFn: () => api<Zone[]>("/zones") });
export const useRecettes = () =>
  useQuery({ queryKey: ["recettes"], queryFn: () => api<Recette[]>("/recettes") });
export const useCuves = () => useQuery({ queryKey: ["cuves"], queryFn: () => api<Cuve[]>("/cuves") });
export const useContenants = () =>
  useQuery({ queryKey: ["contenants"], queryFn: () => api<Contenant[]>("/contenants") });

export const usePlan = (zone?: string) =>
  useQuery({
    queryKey: ["plan", zone],
    queryFn: () => api<ZonePlan>(`/zones/${zone}/plan`),
    enabled: !!zone,
  });

export const usePlantes = (params: Params = {}) =>
  useQuery({ queryKey: ["plantes", params], queryFn: () => api<Plante[]>("/plantes", { params }) });

export const useHistorique = (plante?: string) =>
  useQuery({
    queryKey: ["plantes", "historique", plante],
    queryFn: () => api<Historique>(`/plantes/${plante}/historique`),
    enabled: !!plante,
  });

export const useCapteurs = (zone?: string) =>
  useQuery({ queryKey: ["capteurs", zone], queryFn: () => api<Capteur[]>("/capteurs", { params: { zone } }) });
export const useActionneurs = (zone?: string) =>
  useQuery({
    queryKey: ["actionneurs", zone],
    queryFn: () => api<Actionneur[]>("/actionneurs", { params: { zone } }),
  });
export const useCameras = (zone?: string) =>
  useQuery({ queryKey: ["cameras", zone], queryFn: () => api<Camera[]>("/cameras", { params: { zone } }) });
export const useNoeuds = () => useQuery({ queryKey: ["noeuds"], queryFn: () => api<Noeud[]>("/noeuds") });

export const useCoherence = () =>
  useQuery({ queryKey: ["config", "coherence"], queryFn: () => api<Coherence>("/config/coherence") });
export const useConfigDiff = (enabled: boolean) =>
  useQuery({ queryKey: ["config", "diff"], queryFn: () => api<ConfigDiff>("/config/diff"), enabled });

export const useTableau = (zone?: string) =>
  useQuery({
    queryKey: ["tableau", zone],
    queryFn: () => api<Tableau>(`/zones/${zone}/tableau`),
    enabled: !!zone,
    refetchInterval: 60_000,
  });

export const useMesures = (params: Params, enabled = true) =>
  useQuery({
    queryKey: ["mesures", params],
    queryFn: () => api<Mesures>("/mesures", { params }),
    enabled,
  });

export const useVision = (params: Params, enabled = true) =>
  useQuery({ queryKey: ["vision", params], queryFn: () => api<VisionRow[]>("/vision", { params }), enabled });

export const useConsommation = (params: Params) =>
  useQuery({ queryKey: ["consommation", params], queryFn: () => api<Consommation>("/consommation", { params }) });

export const useAlertes = (params: Params = {}) =>
  useQuery({ queryKey: ["alertes", params], queryFn: () => api<Alerte[]>("/alertes", { params }) });

export const useDecisions = (params: Params) =>
  useQuery({ queryKey: ["decisions", params], queryFn: () => api<DecisionSummary[]>("/decisions", { params }) });

export const useDecision = (id?: string) =>
  useQuery({
    queryKey: ["decisions", "fiche", id],
    queryFn: () => api<DecisionRecord>(`/decisions/${id}`),
    enabled: !!id,
  });

export const useArbre = (params: Params, enabled = true) =>
  useQuery({ queryKey: ["arbre", params], queryFn: () => api<TreeNode>("/actions/arbre", { params }), enabled });

export const useConversations = () =>
  useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<Conversation[]>("/agent/conversations"),
    retry: false,
  });
export const useAgentStatut = () =>
  useQuery({
    queryKey: ["agent", "statut"],
    queryFn: () => api<{ disponible: boolean; modele: string | null }>("/agent/statut"),
    refetchInterval: 60_000,
  });
export const useConversation = (id?: string | null) =>
  useQuery({
    queryKey: ["conversations", id],
    queryFn: () => api<ConversationDetail>(`/agent/conversations/${id}`),
    enabled: !!id,
  });

export const useAuth = () =>
  useQuery({
    queryKey: ["auth"],
    queryFn: () => api<{ requise: boolean; utilisateur: string | null }>("/auth"),
    staleTime: Infinity,
  });

// --- mutations ----------------------------------------------------------------------

/** A mutation that invalidates the given query prefixes on success. */
export function useApiMutation<TVars, TOut = unknown>(
  fn: (vars: TVars) => Promise<TOut>,
  invalidate: QueryKey[],
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}

const STRUCTURE: QueryKey[] = [["plan"], ["zones"], ["plantes"], ["config"], ["emplacements"]];

export const useCreateZone = () =>
  useApiMutation((body: Schemas["ZoneIn"]) => api<Zone>("/zones", { body }), STRUCTURE);
export const useUpdateZone = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["ZonePatch"] & { id: string }) =>
      api<Zone>(`/zones/${id}`, { method: "PATCH", body }),
    STRUCTURE,
  );
export const useDeleteZone = () =>
  useApiMutation((id: string) => api(`/zones/${id}`, { method: "DELETE" }), STRUCTURE);

export const useCreateEmplacement = () =>
  useApiMutation((body: Schemas["EmplacementIn"]) => api<Emplacement>("/emplacements", { body }), STRUCTURE);
export const useUpdateEmplacement = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["EmplacementPatch"] & { id: string }) =>
      api<Emplacement>(`/emplacements/${id}`, { method: "PATCH", body }),
    STRUCTURE,
  );
export const useDeleteEmplacement = () =>
  useApiMutation((id: string) => api(`/emplacements/${id}`, { method: "DELETE" }), STRUCTURE);

export const useCreatePlante = () =>
  useApiMutation((body: Schemas["PlanteIn"]) => api<Plante>("/plantes", { body }), STRUCTURE);
export const useUpdatePlante = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["PlantePatch"] & { id: string }) =>
      api<Plante>(`/plantes/${id}`, { method: "PATCH", body }),
    STRUCTURE,
  );
export const useDeplacerPlante = () =>
  useApiMutation(
    ({ id, emplacement }: { id: string; emplacement: string | null }) =>
      api<Plante>(`/plantes/${id}/deplacer`, { body: { emplacement } }),
    STRUCTURE,
  );

export const usePublier = () =>
  useApiMutation(() => api<Publication>("/config/publier", { method: "POST" }), [["config"], ["serres"]]);

export const useUpdateCapteur = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["CapteurPatch"] & { id: string }) =>
      api<Capteur>(`/capteurs/${encodeURIComponent(id)}`, { method: "PATCH", body }),
    [["capteurs"], ["config"]],
  );
export const useUpdateActionneur = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["ActionneurPatch"] & { id: string }) =>
      api<Actionneur>(`/actionneurs/${id}`, { method: "PATCH", body }),
    [["actionneurs"], ["config"]],
  );
export const useCreateCapteur = () =>
  useApiMutation((body: Schemas["CapteurIn"]) => api<Capteur>("/capteurs", { body }), [["capteurs"], ["config"], ["plan"]]);
export const useDeleteCapteur = () =>
  useApiMutation((id: string) => api(`/capteurs/${encodeURIComponent(id)}`, { method: "DELETE" }), [
    ["capteurs"],
    ["config"],
    ["plan"],
  ]);
export const useCreateActionneur = () =>
  useApiMutation((body: Schemas["ActionneurIn"]) => api<Actionneur>("/actionneurs", { body }), [["actionneurs"], ["config"]]);
export const useDeleteActionneur = () =>
  useApiMutation((id: string) => api(`/actionneurs/${id}`, { method: "DELETE" }), [["actionneurs"], ["config"]]);
export const useCreateCamera = () =>
  useApiMutation((body: Schemas["CameraIn"]) => api<Camera>("/cameras", { body }), [["cameras"], ["config"], ["plan"]]);
export const useUpdateCamera = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["CameraPatch"] & { id: string }) =>
      api<Camera>(`/cameras/${id}`, { method: "PATCH", body }),
    [["cameras"], ["plan"]],
  );
export const useDeleteCamera = () =>
  useApiMutation((id: string) => api(`/cameras/${id}`, { method: "DELETE" }), [["cameras"], ["config"], ["plan"]]);
export const useUpdateCuve = () =>
  useApiMutation(
    ({ id, ...body }: Schemas["CuvePatch"] & { id: string }) => api<Cuve>(`/cuves/${id}`, { method: "PATCH", body }),
    [["cuves"]],
  );

export const useSetRegions = () =>
  useApiMutation(
    ({ camera, regions }: { camera: string; regions: Schemas["Region"][] }) =>
      api<Camera>(`/cameras/${camera}/regions`, { method: "PUT", body: { regions } }),
    [["cameras"], ["plan"], ["config"]],
  );

export const useAcquitter = () =>
  useApiMutation((id: string) => api<Alerte>(`/alertes/${id}/acquitter`, { method: "POST" }), [
    ["alertes"],
    ["tableau"],
  ]);

const DECISIONS: QueryKey[] = [["decisions"], ["tableau"], ["arbre"], ["conversations"]];

export const useRepondre = () =>
  useApiMutation(
    ({ id, verbe, commentaire }: { id: string; verbe: "valider" | "rejeter"; commentaire?: string }) =>
      api<DecisionSummary>(`/decisions/${id}/${verbe}`, { body: { commentaire: commentaire || null } }),
    DECISIONS,
  );

export const useActionManuelle = () =>
  useApiMutation((body: Schemas["Manuelle"]) => api("/actions/manuelle", { body }), [
    ...DECISIONS,
    ["actionneurs"],
  ]);
