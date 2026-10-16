// Decision log (docs/12 §2.5): filterable list; a row opens the decision record.
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDecisions } from "@/api/hooks";
import { Empty, ErrorBox, Loading, NiveauBadge, PageTitle, StatutBadge } from "@/components/common";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { ZoneTabs } from "@/components/ZoneTabs";
import { fmtDateTime } from "@/lib/format";

const TYPES = ["routine", "exceptionnelle", "securite", "manuelle"];
const STATUTS = ["proposee", "validee", "executee", "terminee", "rejetee", "expiree", "bloquee_securite", "creee"];
const NIVEAUX = ["0", "1", "2", "3", "agent", "manuel"];
const PERIODES: Record<string, number> = { "24 h": 24, "7 j": 168, "30 j": 720 };

export function Decisions() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const set = (k: string, v?: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const periode = get("periode") || "7 j";
  const debut = useMemo(() => new Date(Date.now() - PERIODES[periode] * 3600_000).toISOString(), [periode]);
  const { data, isLoading, error } = useDecisions({
    zone: get("zone") || undefined,
    type: get("type") || undefined,
    statut: get("statut") || undefined,
    debut,
    limit: 1000,
  });
  const rows = (data ?? []).filter(
    (d) =>
      (!get("emplacement") || d.emplacements.includes(get("emplacement"))) &&
      (!get("niveau") || d.niveau === get("niveau")) &&
      (!get("regle") || d.regle.id.includes(get("regle"))),
  );

  return (
    <>
      <PageTitle title="Journal des décisions">
        <ZoneTabs all value={get("zone") || undefined} onChange={(z) => set("zone", z)} />
      </PageTitle>
      <div className="mb-3 flex flex-wrap gap-2">
        <Select className="w-auto" value={get("type")} onChange={(e) => set("type", e.target.value)} aria-label="Type">
          <option value="">tous types</option>
          {TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
        <Select className="w-auto" value={get("niveau")} onChange={(e) => set("niveau", e.target.value)} aria-label="Niveau">
          <option value="">tous niveaux</option>
          {NIVEAUX.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
        <Select className="w-auto" value={get("statut")} onChange={(e) => set("statut", e.target.value)} aria-label="Statut">
          <option value="">tous statuts</option>
          {STATUTS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
        <Input className="w-36" placeholder="emplacement" value={get("emplacement")} onChange={(e) => set("emplacement", e.target.value)} />
        <Input className="w-48" placeholder="règle" value={get("regle")} onChange={(e) => set("regle", e.target.value)} />
        <Select className="w-auto" value={periode} onChange={(e) => set("periode", e.target.value)} aria-label="Période">
          {Object.keys(PERIODES).map((p) => (
            <option key={p}>{p}</option>
          ))}
        </Select>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Heure</Th>
                <Th>Zone</Th>
                <Th>Niveau</Th>
                <Th>Type</Th>
                <Th>Règle</Th>
                <Th>Explication</Th>
                <Th>Statut</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id} className="hover:bg-muted/50">
                  <Td className="whitespace-nowrap">
                    <Link to={`/decisions/${d.id}`} className="text-primary hover:underline">
                      {fmtDateTime(d.ts)}
                    </Link>
                  </Td>
                  <Td>{d.zone}</Td>
                  <Td>
                    <NiveauBadge niveau={d.niveau} />
                  </Td>
                  <Td>{d.type}</Td>
                  <Td className="font-mono text-xs">{d.regle.id}</Td>
                  <Td className="max-w-xl">
                    <Link to={`/decisions/${d.id}`} className="line-clamp-2 hover:underline">
                      {d.explication}
                    </Link>
                  </Td>
                  <Td>
                    <StatutBadge statut={d.statut} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {rows.length === 0 && <Empty>Aucune décision pour ces filtres.</Empty>}
        </Card>
      )}
    </>
  );
}
