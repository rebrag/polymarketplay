import { useMemo } from "react";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { Line, LineChart, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";

export type LogPoint = {
  t: number;
  tsMs: number;
  condition_1: string;
  condition_2: string;
  best_bid_1: number | null;
  best_ask_1: number | null;
  best_bid_2: number | null;
  best_ask_2: number | null;
};

export interface LogChartProps {
  data: LogPoint[];
  loading?: boolean;
  error?: string | null;
  emptyMessage?: string;
  startMs?: number | null;
  heightClass?: string;
}

const chartConfig = {
  best_bid_1: { label: "Bid 1", color: "#38bdf8" },
  best_ask_1: { label: "Ask 1", color: "#0ea5e9" },
  best_bid_2: { label: "Bid 2", color: "#22c55e" },
  best_ask_2: { label: "Ask 2", color: "#16a34a" },
} as const;

const formatTick = (value: number) => {
  if (!Number.isFinite(value)) return "";
  if (value >= 3600) return `${Math.round(value / 3600)}h`;
  if (value >= 60) return `${Math.round(value / 60)}m`;
  return `${Math.round(value)}s`;
};

const formatQuote = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "--";
  return value.toFixed(3).replace(/\.?0+$/, "");
};

const formatElapsed = (ms: number): string => {
  if (!Number.isFinite(ms) || ms < 0) return "--";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

interface LogTooltipProps extends TooltipProps<number, string> {
  startMs?: number | null;
}

function LogChartTooltip(props: LogTooltipProps) {
  const payload = (props as { payload?: Array<{ payload?: LogPoint }> }).payload;
  if (!props.active || !payload?.length || !payload[0]?.payload) return null;
  const row = payload[0].payload;
  const elapsed =
    props.startMs && Number.isFinite(props.startMs) && row.tsMs
      ? formatElapsed(row.tsMs - (props.startMs as number))
      : null;
  return (
    <div className="flex items-start gap-2 text-[11px] text-slate-700">
      <div className="rounded-md border border-sky-200 bg-sky-50/95 px-3 py-2 shadow">
        <div className="space-y-0.5">
          <div className="text-[10px] uppercase text-slate-500">
            {row.condition_1 || "Condition 1"}
          </div>
          {elapsed && <div className="text-[10px] text-slate-500">time into game: {elapsed}</div>}
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">ask:</span>
            <span className="font-mono text-slate-900">{formatQuote(row.best_ask_1)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">bid:</span>
            <span className="font-mono text-slate-900">{formatQuote(row.best_bid_1)}</span>
          </div>
        </div>
      </div>
      <div className="rounded-md border border-emerald-200 bg-emerald-50/95 px-3 py-2 shadow">
        <div className="space-y-0.5">
          <div className="text-[10px] uppercase text-slate-500">
            {row.condition_2 || "Condition 2"}
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">ask:</span>
            <span className="font-mono text-slate-900">{formatQuote(row.best_ask_2)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">bid:</span>
            <span className="font-mono text-slate-900">{formatQuote(row.best_bid_2)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function LogChart({
  data,
  loading,
  error,
  emptyMessage = "Pick a log to view its chart.",
  startMs,
  heightClass = "h-[calc(100%-28px)]",
}: LogChartProps) {
  const ticks = useMemo(() => {
    if (data.length === 0) return [];
    const maxT = Math.max(...data.map((row) => row.t));
    if (!Number.isFinite(maxT) || maxT <= 0) return [0];
    const steps = [30, 60, 300, 600, 900, 1200, 1800, 3600];
    let step = steps[0];
    for (const candidate of steps) {
      const count = Math.floor(maxT / candidate) + 1;
      if (count <= 5) {
        step = candidate;
        break;
      }
      step = candidate;
    }
    const minTicks = 4;
    const tickMax = Math.max(maxT, step * (minTicks - 1));
    const tks: number[] = [];
    for (let t = 0; t <= tickMax; t += step) {
      tks.push(t);
    }
    return tks.length > 1 ? tks : [0, maxT];
  }, [data]);

  if (error) return <div className="text-[11px] text-amber-400">{error}</div>;
  if (loading) return <div className="text-[11px] text-slate-400">Loading chart...</div>;
  if (data.length === 0) return <div className="text-[11px] text-slate-500">{emptyMessage}</div>;

  return (
    <ChartContainer config={chartConfig} className={`w-full ${heightClass}`}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }} isAnimationActive={false}>
        <XAxis
          dataKey="t"
          tickLine
          axisLine
          tickMargin={6}
          fontSize={10}
          ticks={ticks}
          tickFormatter={formatTick}
        />
        <YAxis tickLine axisLine tickMargin={6} fontSize={10} domain={[0, 1]} />
        <ChartTooltip cursor={false} content={<LogChartTooltip startMs={startMs} />} />
        <Line type="monotone" dataKey="best_bid_1" stroke="var(--color-best_bid_1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_ask_1" stroke="var(--color-best_ask_1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_bid_2" stroke="var(--color-best_bid_2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_ask_2" stroke="var(--color-best_ask_2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ChartContainer>
  );
}
