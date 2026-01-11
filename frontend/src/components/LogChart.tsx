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
  return formatElapsed(value * 1000);
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
      <div className="rounded-md border border-slate-200 bg-white/95 px-3 py-2 shadow">
        <div className="space-y-0.5">
          <div className="text-[10px] uppercase text-slate-500">Time Since Start</div>
          <div className="text-[11px] font-mono text-slate-900">
            {elapsed ?? "--"}
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
  const fallbackStartMs = useMemo(() => {
    if (startMs && Number.isFinite(startMs)) return startMs;
    const times = data.map((row) => row.tsMs).filter((t) => Number.isFinite(t) && t > 0);
    if (!times.length) return null;
    return Math.min(...times);
  }, [data, startMs]);
  const ticks = useMemo(() => {
    if (data.length === 0) return [];
    const times = data.map((row) => row.t).filter((t) => Number.isFinite(t));
    if (!times.length) return [];
    const maxT = Math.max(...times);
    if (!Number.isFinite(maxT) || maxT <= 0) return [0];
    let end =
      maxT >= 60 ? Math.floor(maxT / 60) * 60 : Math.max(1, Math.round(maxT));
    if (end > maxT) end = maxT;
    const tks = end === 0 ? [0] : [0, end];
    return Array.from(new Set(tks));
  }, [data]);

  if (error) return <div className="text-[11px] text-amber-400">{error}</div>;
  if (loading) return <div className="text-[11px] text-slate-400">Loading chart...</div>;
  if (data.length === 0) return <div className="text-[11px] text-slate-500">{emptyMessage}</div>;

  return (
    <ChartContainer config={chartConfig} className={`w-full ${heightClass}`}>
      <LineChart data={data} margin={{ top: 8, right: 36, left: 4, bottom: 0 }}>
        <XAxis
          dataKey="t"
          type="number"
          scale="linear"
          tickLine={false}
          axisLine={false}
          interval={0}
          minTickGap={20}
          tickMargin={8}
          padding={{ right: 20 }}
          fontSize={10}
          ticks={ticks}
          tickFormatter={formatTick}
          allowDuplicatedCategory={false}
          domain={[0, "dataMax"]}
        />
        <YAxis tickLine={false} axisLine tickMargin={6} fontSize={10} domain={[0, 1]} />
        <ChartTooltip cursor={false} content={<LogChartTooltip startMs={fallbackStartMs} />} />
        <Line type="monotone" dataKey="best_bid_1" stroke="var(--color-best_bid_1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_ask_1" stroke="var(--color-best_ask_1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_bid_2" stroke="var(--color-best_bid_2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="best_ask_2" stroke="var(--color-best_ask_2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ChartContainer>
  );
}
