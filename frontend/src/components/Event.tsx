import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReactNode } from "react";

interface EventProps {
  title: string;
  pairCount: number;
  minVolumeLabel?: string;
  minimized: boolean;
  onToggleMinimize: () => void;
  onClose?: () => void;
  children?: ReactNode;
  headerRight?: ReactNode;
}

export function Event({
  title,
  pairCount,
  minVolumeLabel,
  minimized,
  onToggleMinimize,
  onClose,
  children,
  headerRight,
}: EventProps) {
  return (
    <div className="flex flex-col gap-3 bg-slate-900/20 p-0 rounded-lg">
      <div className="flex flex-col lg:flex-row gap-3 justify-between items-start">
        <div className="flex-shrink-0">
          <h2 className="text-xl font-bold text-white uppercase tracking-tighter">
            {title}
          </h2>
          <div className="flex items-center gap-4 mt-1">
            <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-900 bg-blue-900/10">
              {pairCount} BOOKS
            </Badge>
            {minVolumeLabel ? (
              <div className="flex items-center gap-2 min-w-[150px]">
                <span className="text-[10px] text-slate-500 font-mono">
                  {minVolumeLabel}
                </span>
              </div>
            ) : null}
            {minimized ? (
              <Badge variant="outline" className="text-[10px] text-amber-300 border-amber-800 bg-amber-900/10">
                MINIMIZED
              </Badge>
            ) : null}
          </div>
        </div>
        <div className="w-full lg:w-auto flex items-center justify-end gap-2">
          {headerRight}
          <Button
            onClick={onToggleMinimize}
            className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
          >
            {minimized ? "Expand" : "Minimize"}
          </Button>
          {onClose ? (
            <Button
              onClick={onClose}
              className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-rose-200 hover:text-white hover:border-rose-700 transition-colors"
            >
              Close
            </Button>
          ) : null}
        </div>
      </div>
      <div className={minimized ? "hidden" : ""} aria-hidden={minimized}>
        {children}
      </div>
    </div>
  );
}
