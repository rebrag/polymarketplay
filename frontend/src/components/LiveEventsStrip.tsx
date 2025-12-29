import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface LiveEvent {
  id?: string;
  slug: string;
  title: string;
  volume?: number;
  startDate?: string;
  endDate?: string;
  markets?: { question: string; volume?: number; gameStartTime?: string }[];
  raw?: object;
}

interface LiveEventsStripProps {
  events: LiveEvent[];
  subscribed: Set<string>;
  onAdd: (slug: string) => void;
  onRemove: (slug: string) => void;
}

function formatVol(value: number | undefined): string {
  if (!value || value <= 0) return "--";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toFixed(0);
}

function shortTitle(title: string): string {
  if (title.length <= 32) return title;
  return `${title.slice(0, 29)}...`;
}

function shortMarketLabel(eventTitle: string, marketQuestion: string): string {
  const cleaned = marketQuestion.replace(eventTitle, "").replace(/^\s*[-:]\s*/, "").trim();
  if (!cleaned) return marketQuestion;
  if (cleaned.length <= 12) return cleaned;
  return `${cleaned.slice(0, 10)}…`;
}

function parseDate(raw?: string): Date | null {
  if (!raw) return null;
  const normalized = raw.replace("Z", "+00:00");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatStart(raw?: string): string {
  const dt = parseDate(raw);
  if (!dt) return "--";
  return dt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function getEventGameStart(ev: LiveEvent): string | undefined {
  const markets = ev.markets || [];
  let earliest: string | undefined;
  for (const m of markets) {
    if (!m.gameStartTime) continue;
    if (!earliest) {
      earliest = m.gameStartTime;
      continue;
    }
    const a = parseDate(m.gameStartTime)?.getTime() ?? Number.MAX_SAFE_INTEGER;
    const b = parseDate(earliest)?.getTime() ?? Number.MAX_SAFE_INTEGER;
    if (a < b) earliest = m.gameStartTime;
  }
  return earliest;
}

function getStatus(ev: LiveEvent): "live" | "upcoming" | "unknown" {
  const now = Date.now();
  const gameStart = getEventGameStart(ev);
  const start = parseDate(gameStart)?.getTime() ?? null;
  if (start !== null && now < start) return "upcoming";
  if (start !== null && now >= start) return "live";
  return "unknown";
}

function getDisplayTime(ev: LiveEvent): string | null {
  const gameStart = getEventGameStart(ev);
  if (!gameStart) return null;
  return formatStart(gameStart);
}

export function LiveEventsStrip({ events, subscribed, onAdd, onRemove }: LiveEventsStripProps) {
  const [query, setQuery] = useState("");
  const sorted = useMemo(() => {
    const now = Date.now();
    const sortTime = (ev: LiveEvent): number => {
      const gameStart = getEventGameStart(ev);
      const start = parseDate(gameStart)?.getTime() ?? null;
      if (start !== null) return start;
      return Number.MAX_SAFE_INTEGER;
    };
    return [...events].sort((a, b) => {
      const aTime = sortTime(a);
      const bTime = sortTime(b);
      if (aTime !== bTime) return aTime - bTime;
      return (b.volume ?? 0) - (a.volume ?? 0);
    });
  }, [events]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter((ev) => ev.title.toLowerCase().includes(q));
  }, [query, sorted]);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [copiedRaw, setCopiedRaw] = useState(false);

  const scrollBy = (delta: number) => {
    const el = trackRef.current;
    if (!el) return;
    el.scrollBy({ left: delta, behavior: "smooth" });
  };

  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;

    const update = () => {
      const maxScrollLeft = el.scrollWidth - el.clientWidth;
      setCanScrollLeft(el.scrollLeft > 0);
      setCanScrollRight(el.scrollLeft < maxScrollLeft - 1);
    };

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [sorted.length]);

  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">Live Markets</span>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search teams..."
            className="h-7 w-44 bg-slate-900/60 border-slate-800 text-[10px] text-slate-200"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-mono">Window set in Settings</span>
          <Button
            onClick={async () => {
              try {
                const res = await fetch("http://localhost:8000/debug/events_raw?limit=500&tag_id=1");
                if (!res.ok) return;
                const data = await res.json();
                await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
                setCopiedRaw(true);
                window.setTimeout(() => setCopiedRaw(false), 1200);
              } catch {
                setCopiedRaw(false);
              }
            }}
            className="h-6 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
          >
            {copiedRaw ? "Copied" : "Copy Raw"}
          </Button>
        </div>
      </div>
      <div className="relative">
        {canScrollLeft && (
          <Button
            onClick={() => scrollBy(-720)}
            className="absolute left-0 top-1/2 -translate-y-1/2 h-8 w-8 rounded-full border border-slate-800 bg-slate-950/80 text-slate-300 hover:text-white"
          >
            {"<"}
          </Button>
        )}
        <div
          ref={trackRef}
          className="flex gap-3 overflow-hidden scroll-smooth px-0"
        >
          {filtered.slice(0, 50).map((ev) => {
            const isOn = subscribed.has(ev.slug);
            const status = getStatus(ev);
            const displayTime = getDisplayTime(ev);
            const marketTags = (ev.markets || [])
              .slice()
              .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
              .slice(0, 3);
            const rawJson = JSON.stringify(ev.raw ?? ev, null, 2);
            return (
              <div
                key={ev.slug}
                title={rawJson}
                onClick={() => {
                  navigator.clipboard.writeText(rawJson).catch(() => {});
                }}
                className="flex min-w-[200px] items-center gap-3 rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2"
              >
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase font-bold text-slate-400">
                    {displayTime ? displayTime : "Upcoming"}
                    {status === "live" && (
                      <>
                        <span className="ml-2 text-red-400">LIVE</span>
                        <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-red-500 align-middle" />
                      </>
                    )}
                  </span>
                  <span className="text-[11px] text-slate-200 font-semibold">{shortTitle(ev.title)}</span>
                  <span className="text-[10px] text-slate-500 font-mono">{formatVol(ev.volume)} vol</span>
                </div>
                <Button
                  onClick={() => (isOn ? onRemove(ev.slug) : onAdd(ev.slug))}
                  className={`h-7 px-3 text-[10px] uppercase font-bold ${
                    isOn
                      ? "bg-slate-800 border border-slate-700 hover:bg-slate-700"
                      : "bg-blue-600 hover:bg-blue-500"
                  }`}
                >
                  {isOn ? "Remove" : "Add"}
                </Button>
              </div>
            );
          })}
        </div>
        {canScrollRight && (
          <Button
            onClick={() => scrollBy(720)}
            className="absolute right-0 top-1/2 -translate-y-1/2 h-8 w-8 rounded-full border border-slate-800 bg-slate-950/80 text-slate-300 hover:text-white"
          >
            {">"}
          </Button>
        )}
      </div>
    </div>
  );
}
