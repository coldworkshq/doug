"use client";

import {
  Cell,
  ReferenceLine,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer } from "@/components/ui/chart";

interface Point {
  score: number;
  band: "cleared" | "flagged";
}

/** Strip plot: every open PR as a specimen pin on the 0–1 risk axis,
 *  with the routing threshold drawn as the cut line. */
export function ScoreStrip({
  points,
  threshold,
}: {
  points: Point[];
  threshold: number;
}) {
  const binCounts = new Map<number, number>();
  const data = points.map((p) => {
    const bin = Math.round(p.score * 20);
    const stack = binCounts.get(bin) ?? 0;
    binCounts.set(bin, stack + 1);
    return { x: p.score, y: stack + 1, band: p.band };
  });
  const maxStack = Math.max(...data.map((d) => d.y), 3);

  return (
    <ChartContainer config={{}} className="h-32 w-full">
      <ScatterChart margin={{ top: 24, right: 48, bottom: 0, left: 12 }}>
        <XAxis
          type="number"
          dataKey="x"
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          tick={{ fontSize: 10, fontFamily: "var(--font-geist-mono)" }}
        />
        <YAxis type="number" dataKey="y" domain={[0, maxStack + 1]} hide />
        <ReferenceLine
          x={threshold}
          stroke="var(--sheen)"
          strokeDasharray="4 3"
          label={{
            value: `threshold ${threshold}`,
            position: "top",
            fontSize: 10,
            fontFamily: "var(--font-geist-mono)",
            fill: "var(--sheen)",
          }}
        />
        <Scatter data={data} isAnimationActive={false}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={d.band === "flagged" ? "var(--flag)" : "var(--clear)"}
              fillOpacity={d.band === "flagged" ? 1 : 0.55}
            />
          ))}
        </Scatter>
      </ScatterChart>
    </ChartContainer>
  );
}
