// Time series charts (Recharts): the dashboard sparklines and the curves of the decision
// record, centred on the decision with the window used by the rule highlighted.
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Range } from "@/api/types";
import { fmtDateTime, fmtNum, fmtTime } from "@/lib/format";

const toPoints = (points: [string, number][]) => points.map(([t, v]) => ({ t: Date.parse(t), v }));

export function MiniCourbe({
  points,
  plage,
  color = "var(--primary)",
}: {
  points: [string, number][];
  plage?: Range | null;
  color?: string;
}) {
  const data = toPoints(points);
  if (data.length < 2) return <div className="h-10" />;
  return (
    <div className="h-10" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
          <YAxis hide domain={["auto", "auto"]} />
          {plage && <ReferenceArea y1={plage[0]} y2={plage[1]} fill="var(--ok)" fillOpacity={0.1} />}
          <Line dataKey="v" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Y domain that keeps the threshold and the setpoint range in view (with a margin). */
export function yDomain(values: number[], extra: (number | null | undefined)[]): [number, number] | undefined {
  const all = [...values, ...extra.filter((v): v is number => v !== null && v !== undefined)];
  if (all.length === 0) return undefined;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.08, Math.abs(hi) * 0.01, 0.1);
  return [Math.floor((lo - pad) * 10) / 10, Math.ceil((hi + pad) * 10) / 10];
}

export function Courbe({
  points,
  unite,
  instant,
  fenetre,
  seuil,
  plage,
  height = 160,
}: {
  points: [string, number][];
  unite: string;
  instant?: string; // vertical line (decision)
  fenetre?: [number, number] | null; // ms: window used by the rule
  seuil?: number | null;
  plage?: Range | null;
  height?: number;
}) {
  const data = toPoints(points);
  const domain = yDomain(data.map((d) => d.v), [seuil, plage?.[0], plage?.[1]]);
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) => fmtTime(new Date(t).toISOString())}
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            stroke="var(--border)"
          />
          <YAxis
            width={44}
            domain={domain ?? ["auto", "auto"]}
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            stroke="var(--border)"
          />
          <Tooltip
            labelFormatter={(t) => fmtDateTime(new Date(Number(t)).toISOString())}
            formatter={(v) => [`${fmtNum(Number(v), 2)} ${unite}`, ""]}
            contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", fontSize: 12 }}
          />
          {plage && <ReferenceArea y1={plage[0]} y2={plage[1]} fill="var(--ok)" fillOpacity={0.08} />}
          {fenetre && (
            <ReferenceArea x1={fenetre[0]} x2={fenetre[1]} fill="var(--warn)" fillOpacity={0.15} />
          )}
          {seuil !== undefined && seuil !== null && (
            <ReferenceLine y={seuil} stroke="var(--bad)" strokeDasharray="4 3" />
          )}
          {instant && <ReferenceLine x={Date.parse(instant)} stroke="var(--foreground)" strokeWidth={1.5} />}
          <Line dataKey="v" stroke="var(--primary)" strokeWidth={1.75} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
