import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useState, type ReactNode } from "react";

interface EventProps {
  title: string;
  slug?: string;
  pairCount: number;
  minVolumeLabel?: string;
  minimized: boolean;
  onToggleMinimize: () => void;
  onClose?: () => void;
  raw?: object;
  children?: ReactNode;
  headerRight?: ReactNode;
}

export function Event({
  title,
  slug,
  pairCount,
  minVolumeLabel,
  minimized,
  onToggleMinimize,
  onClose,
  raw,
  children,
  headerRight,
}: EventProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!raw) return;
    const payload = JSON.stringify(raw, null, 2);
    try {
      await navigator.clipboard.writeText(payload);
    } catch {
      const el = document.createElement("textarea");
      el.value = payload;
      el.style.position = "fixed";
      el.style.left = "-9999px";
      document.body.appendChild(el);
      el.focus();
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 900);
  };
  return (
    <div className="flex flex-col gap-3 bg-slate-900/20 p-0 rounded-lg">
      <div className="flex flex-col lg:flex-row gap-3 justify-between items-start">
        <div className="flex-shrink-0">
          <h2 className="text-xl font-bold text-white uppercase tracking-tighter">
            {slug ? (
              <a
                href={`https://polymarket.com/event/${slug}`}
                target="_blank"
                rel="noreferrer"
                className="hover:text-blue-300 transition-colors"
              >
                {title}
              </a>
            ) : (
              title
            )}
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
          {raw ? (
            <Button
              onClick={handleCopy}
              className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          ) : null}
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
