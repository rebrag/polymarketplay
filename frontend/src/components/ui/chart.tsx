"use client";

import * as React from "react";
import { Tooltip, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

type ChartConfig = Record<
  string,
  {
    label?: string;
    color?: string;
  }
>;

const ChartContext = React.createContext<ChartConfig | null>(null);

const ChartContainer = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { config: ChartConfig }
>(({ className, config, children, ...props }, ref) => {
  const style = {} as React.CSSProperties & Record<string, string>;
  Object.entries(config).forEach(([key, value]) => {
    if (value.color) {
      style[`--color-${key}`] = value.color;
    }
  });
  return (
    <ChartContext.Provider value={config}>
      <div
        ref={ref}
        className={cn("h-[280px] w-full", className)}
        style={style}
        {...props}
      >
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
});
ChartContainer.displayName = "ChartContainer";

const ChartTooltip = Tooltip;

type ChartTooltipPayload = {
  dataKey?: string | number;
  value?: number | string;
};

type ChartTooltipProps = {
  active?: boolean;
  payload?: ChartTooltipPayload[];
  label?: string | number;
};

function ChartTooltipContent({ active, payload, label }: ChartTooltipProps) {
  const config = React.useContext(ChartContext) ?? {};
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-[11px] text-slate-700 shadow">
      <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-400">
        {label}
      </div>
      <div className="space-y-1">
        {payload.map((item) => {
          const key = item.dataKey as string;
          const meta = config[key];
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <span className="text-slate-500">{meta?.label ?? key}</span>
              <span className="font-mono text-slate-900">
                {typeof item.value === "number" ? item.value.toFixed(3) : item.value}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { ChartContainer, ChartTooltip, ChartTooltipContent };
