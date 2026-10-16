// Consumption (docs/12 §2.4, docs/09 §5): energy (kWh, €), water (L), light (DLI vs
// target), inputs (mL) per day, stacked per actuator type. Estimated from the actuator
// states as long as no power meter is declared.
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useConsommation } from "@/api/hooks";
import type { Consommation as Conso } from "@/api/types";
import { ErrorBox, Loading, PageTitle } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { ZoneTabs } from "@/components/ZoneTabs";
import { ACTUATOR_LABELS, fmtDay, fmtNum } from "@/lib/format";

// Fixed order: a type keeps its color whatever the filter (color follows the entity).
const TYPES = ["led", "chauffage", "ventilo", "pompe_nutri", "brumisateur", "pompe_ph_down", "pompe_nutri_a", "pompe_nutri_b"];
const color = (type: string) => `var(--series-${(TYPES.indexOf(type) % 8) + 1})`;

type Measure = "kwh" | "litres" | "ml";

function perDay(data: Conso, measure: Measure) {
  const types = new Set<string>();
  const rows = data.par_jour.map((d) => {
    const row: Record<string, number | string> = { jour: d.jour };
    for (const a of Object.values(d.actionneurs)) {
      const v = a[measure];
      if (v) {
        row[a.type] = ((row[a.type] as number) ?? 0) + v;
        types.add(a.type);
      }
    }
    return row;
  });
  return { rows, types: TYPES.filter((t) => types.has(t)) };
}

const axis = { tick: { fontSize: 11, fill: "var(--muted-foreground)" }, stroke: "var(--border)" };
const tooltip = { contentStyle: { background: "var(--card)", border: "1px solid var(--border)", fontSize: 12 } };

function Empile({ data, measure, unite }: { data: Conso; measure: Measure; unite: string }) {
  const { rows, types } = perDay(data, measure);
  if (types.length === 0) return <p className="p-4 text-sm text-muted-foreground">Rien sur la période.</p>;
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="jour" tickFormatter={fmtDay} {...axis} />
          <YAxis width={48} {...axis} />
          <Tooltip
            {...tooltip}
            cursor={{ fill: "var(--muted)" }}
            labelFormatter={(j) => fmtDay(String(j))}
            formatter={(v, name) => [`${fmtNum(Number(v), 2)} ${unite}`, ACTUATOR_LABELS[String(name)] ?? name]}
          />
          <Legend formatter={(name) => <span className="text-xs text-foreground">{ACTUATOR_LABELS[name] ?? name}</span>} />
          {types.map((t, i) => (
            <Bar
              key={t}
              dataKey={t}
              stackId="s"
              fill={color(t)}
              stroke="var(--card)"
              strokeWidth={1}
              maxBarSize={40}
              radius={i === types.length - 1 ? [4, 4, 0, 0] : 0}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Lumiere({ data, zone }: { data: Conso; zone: string }) {
  const rows = data.lumiere
    .filter((l) => l.zone === zone)
    .map((l) => ({ jour: l.jour, led: l.dli_led, naturel: l.dli_naturel ?? 0, mesure: l.dli_total !== null }));
  const cible = data.dli_cible[zone];
  const top = Math.max(cible ?? 0, ...rows.map((r) => r.led + r.naturel));
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="jour" tickFormatter={fmtDay} {...axis} />
          <YAxis width={40} domain={[0, Math.ceil(top * 1.1) || 1]} {...axis} />
          <Tooltip
            {...tooltip}
            cursor={{ fill: "var(--muted)" }}
            labelFormatter={(j) => fmtDay(String(j))}
            formatter={(v, name) => [`${fmtNum(Number(v), 1)} mol/m²/j`, name === "led" ? "LED" : "naturel"]}
          />
          <Legend formatter={(n) => <span className="text-xs text-foreground">{n === "led" ? "LED" : "naturel (mesuré − LED)"}</span>} />
          <Bar dataKey="naturel" stackId="d" fill="var(--series-4)" stroke="var(--card)" strokeWidth={1} maxBarSize={40} isAnimationActive={false} />
          <Bar dataKey="led" stackId="d" fill="var(--series-7)" stroke="var(--card)" strokeWidth={1} maxBarSize={40} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          {cible ? (
            <ReferenceLine y={cible} stroke="var(--foreground)" strokeDasharray="4 3" label={{ value: `cible ${cible}`, fontSize: 11, fill: "var(--muted-foreground)", position: "insideTopRight" }} />
          ) : null}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span>}
      </div>
    </Card>
  );
}

export function Consommation() {
  const [zone, setZone] = useState<string | undefined>();
  const [periode, setPeriode] = useState("semaine");
  const { data, isLoading, error } = useConsommation({ zone, periode });
  const zones = data ? Object.keys(data.dli_cible) : [];

  return (
    <>
      <PageTitle title="Consommation">
        <ZoneTabs all value={zone} onChange={setZone} />
        <Select className="w-32" value={periode} onChange={(e) => setPeriode(e.target.value)} aria-label="Période">
          <option value="jour">jour</option>
          <option value="semaine">semaine</option>
          <option value="mois">mois</option>
        </Select>
      </PageTitle>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <div className="flex flex-col gap-4">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            {data.estime && <Badge tone="warn">estimé</Badge>}
            du {fmtDay(data.du)} au {fmtDay(data.au)}
            {data.jour_en_cours && " (jour en cours inclus)"} · {data.note}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Énergie" value={fmtNum(data.totaux.kwh, 2)} unit="kWh" />
            <Stat label="Coût" value={data.totaux.cout !== null ? fmtNum(data.totaux.cout, 2) : "—"} unit={data.totaux.cout !== null ? "€" : undefined} />
            <Stat label="Eau" value={fmtNum(data.totaux.litres, 1)} unit="L" />
            <Stat label="Intrants" value={fmtNum(data.totaux.ml, 0)} unit="mL" />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Énergie par jour (kWh)" />
              <CardBody>
                <Empile data={data} measure="kwh" unite="kWh" />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Eau par jour (L)" />
              <CardBody>
                <Empile data={data} measure="litres" unite="L" />
              </CardBody>
            </Card>
            {zones.map((z) => (
              <Card key={z}>
                <CardHeader title={`Lumière ${z} : DLI obtenu vs cible`} />
                <CardBody>
                  <Lumiere data={data} zone={z} />
                </CardBody>
              </Card>
            ))}
            <Card>
              <CardHeader title="Intrants par jour (mL)" />
              <CardBody>
                <Empile data={data} measure="ml" unite="mL" />
              </CardBody>
            </Card>
          </div>
          <Card>
            <CardHeader title="Par actionneur" />
            <Table>
              <thead>
                <tr>
                  <Th>Actionneur</Th>
                  <Th>Zone</Th>
                  <Th className="text-right">Heures</Th>
                  <Th className="text-right">kWh</Th>
                  <Th className="text-right">€</Th>
                  <Th className="text-right">L</Th>
                  <Th className="text-right">mL</Th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.actionneurs).map(([id, a]) => (
                  <tr key={id}>
                    <Td>
                      <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color(a.type) }} />
                      {id}
                    </Td>
                    <Td>{a.zone}</Td>
                    <Td className="text-right">{fmtNum(a.heures_on, 1)}</Td>
                    <Td className="text-right">{fmtNum(a.kwh, 3)}</Td>
                    <Td className="text-right">{fmtNum(a.cout, 2)}</Td>
                    <Td className="text-right">{fmtNum(a.litres, 1)}</Td>
                    <Td className="text-right">{fmtNum(a.ml, 0)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      )}
    </>
  );
}
