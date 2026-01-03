import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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

interface OddsOutcome {
  name?: string;
  price?: number;
}

interface OddsMarket {
  key?: string;
  outcomes?: OddsOutcome[];
}

interface OddsBookmaker {
  key?: string;
  markets?: OddsMarket[];
}

interface OddsEvent {
  home_team?: string;
  away_team?: string;
  bookmakers?: OddsBookmaker[];
}

interface OddsResponse {
  events?: OddsEvent[];
}

interface OddsSport {
  key?: string;
  title?: string;
  active?: boolean;
}

interface OddsSportsResponse {
  sports?: OddsSport[];
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

function normalizeTeamName(name: string): string {
  const cleaned = name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  const stop = new Set(["fc", "cf", "afc", "sc", "club", "the", "utd", "united"]);
  return parts.filter((p) => !stop.has(p)).join(" ");
}

function extractTeams(title: string): [string, string] | null {
  const parts = title.split(/ vs\.? | v\.? /i).map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 2) return [parts[0], parts[1]];
  return null;
}

function getOddsOutcomes(
  ev: LiveEvent,
  oddsEvents: OddsEvent[]
): Array<{ name: string; implied: number }> | null {
  const teams = extractTeams(ev.title);
  if (!teams) return null;
  const [teamA, teamB] = teams.map(normalizeTeamName);
  if (!teamA || !teamB) return null;
  for (const oddsEv of oddsEvents) {
    const home = normalizeTeamName(String(oddsEv.home_team ?? ""));
    const away = normalizeTeamName(String(oddsEv.away_team ?? ""));
    if (!home || !away) continue;
    const match =
      (teamA === home && teamB === away) ||
      (teamA === away && teamB === home);
    if (!match) continue;
    const books = oddsEv.bookmakers ?? [];
    for (const book of books) {
      const markets = book.markets ?? [];
      for (const market of markets) {
        if (market.key !== "h2h") continue;
        const outcomes = market.outcomes ?? [];
        const results: Array<{ name: string; implied: number }> = [];
        for (const outcome of outcomes) {
          const name = normalizeTeamName(String(outcome.name ?? ""));
          const price = typeof outcome.price === "number" ? outcome.price : Number(outcome.price);
          if (!name || !Number.isFinite(price) || price <= 0) continue;
          results.push({ name: String(outcome.name ?? ""), implied: 1 / price });
        }
        if (results.length > 0) return results;
      }
    }
  }
  return null;
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

function loadLiveFilters(): { minVolume: string; tagFilter: string } {
  try {
    const raw = localStorage.getItem("pm_live_filters");
    if (!raw) return { minVolume: "0", tagFilter: "all" };
    const parsed = JSON.parse(raw) as { minVolume?: string; tagFilter?: string };
    return {
      minVolume: typeof parsed.minVolume === "string" ? parsed.minVolume : "0",
      tagFilter: typeof parsed.tagFilter === "string" ? parsed.tagFilter : "all",
    };
  } catch {
    return { minVolume: "0", tagFilter: "all" };
  }
}

function loadOddsSport(): string {
  try {
    const raw = localStorage.getItem("pm_odds_sport");
    if (!raw) return "";
    return raw;
  } catch {
    return "";
  }
}

export function LiveEventsStrip({ events, subscribed, onAdd, onRemove }: LiveEventsStripProps) {
  const [query, setQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [oddsLoading, setOddsLoading] = useState(false);
  const [oddsCopied, setOddsCopied] = useState(false);
  const [oddsReady, setOddsReady] = useState(false);
  const [oddsError, setOddsError] = useState<string | null>(null);
  const [oddsData, setOddsData] = useState<OddsResponse | null>(null);
  const [oddsSports, setOddsSports] = useState<OddsSport[]>([]);
  const [oddsSportKey, setOddsSportKey] = useState(loadOddsSport());
  const initialFilters = useMemo(() => loadLiveFilters(), []);
  const [minVolume, setMinVolume] = useState(initialFilters.minVolume);
  const [tagFilter, setTagFilter] = useState(initialFilters.tagFilter);
  const initialScrollDone = useRef(false);
  const tagOptions = useMemo(() => {
    const tags = new Set<string>();
    for (const ev of events) {
      const raw = (ev.raw ?? {}) as { tags?: Array<{ name?: string; slug?: string; id?: string | number }> };
      const items = raw.tags ?? [];
      for (const tag of items) {
        const label = tag?.name || tag?.slug || (tag?.id != null ? String(tag.id) : "");
        if (label) tags.add(label);
      }
    }
    return Array.from(tags).sort((a, b) => a.localeCompare(b));
  }, [events]);
  const sorted = useMemo(() => {
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
    const minVolNum = Number(minVolume);
    const minVol = Number.isFinite(minVolNum) ? minVolNum : 0;
    return sorted.filter((ev) => {
      if (q && !ev.title.toLowerCase().includes(q)) return false;
      const volume = ev.volume ?? 0;
      if (volume < minVol) return false;
      if (tagFilter !== "all") {
        const raw = (ev.raw ?? {}) as { tags?: Array<{ name?: string; slug?: string; id?: string | number }> };
        const items = raw.tags ?? [];
        const matched = items.some((tag) => {
          const label = tag?.name || tag?.slug || (tag?.id != null ? String(tag.id) : "");
          return label === tagFilter;
        });
        if (!matched) return false;
      }
      return true;
    });
  }, [query, sorted, minVolume, tagFilter]);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [copiedRaw, setCopiedRaw] = useState(false);

  const handleFetchOdds = async () => {
    setOddsLoading(true);
    setOddsError(null);
    try {
      const params = new URLSearchParams();
      if (oddsSportKey) params.set("sport", oddsSportKey);
      const res = await fetch(`http://localhost:8000/odds/raw?${params.toString()}`);
      if (!res.ok) {
        setOddsError("Odds not available");
        return;
      }
      const data = await res.json();
      setOddsData(data as OddsResponse);
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setOddsCopied(true);
      setOddsReady(true);
      window.setTimeout(() => setOddsCopied(false), 1200);
    } catch {
      setOddsError("Odds request failed");
    } finally {
      setOddsLoading(false);
    }
  };

  const handleCopyOdds = async () => {
    if (!oddsData) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(oddsData, null, 2));
      setOddsCopied(true);
      window.setTimeout(() => setOddsCopied(false), 1200);
    } catch {
      setOddsError("Odds copy failed");
    }
  };
  const oddsEvents = useMemo(() => oddsData?.events ?? [], [oddsData]);

  useEffect(() => {
    if (!oddsSports.length) return;
    try {
      localStorage.setItem("pm_odds_sport", oddsSportKey);
    } catch {
      // ignore
    }
  }, [oddsSportKey, oddsSports.length]);

  useEffect(() => {
    if (oddsSports.length) return;
    const controller = new AbortController();
    fetch("http://localhost:8000/odds/sports", { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: OddsSportsResponse | null) => {
        if (!data?.sports) return;
        const activeSports = data.sports.filter((sport) => sport.active !== false);
        setOddsSports(activeSports);
        if (!oddsSportKey && activeSports.length > 0) {
          setOddsSportKey(String(activeSports[0].key ?? ""));
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [oddsSportKey, oddsSports.length]);

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
  useEffect(() => {
    const el = trackRef.current;
    if (!el || initialScrollDone.current) return;
    if (sorted.length === 0) return;
    const targetIndex = sorted.findIndex((ev) => getStatus(ev) !== "live");
    if (targetIndex <= 0) {
      initialScrollDone.current = true;
      return;
    }
    window.setTimeout(() => {
      const child = el.children.item(targetIndex) as HTMLElement | null;
      if (!child) return;
      el.scrollLeft = Math.max(0, child.offsetLeft - 12);
      initialScrollDone.current = true;
    }, 0);
  }, [sorted]);
  useEffect(() => {
    try {
      localStorage.setItem("pm_live_filters", JSON.stringify({ minVolume, tagFilter }));
    } catch {
      // ignore
    }
  }, [minVolume, tagFilter]);

  return (
    <div className="relative rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">Live Markets</span>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search (${filtered.length}) events...`}
            className="h-7 w-44 bg-slate-900/60 border-slate-800 text-[10px] text-slate-200"
          />
          <div className="relative">
            <Button
              onClick={() => setFiltersOpen((open) => !open)}
              className="h-7 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
            >
              Filters
            </Button>
            {filtersOpen && (
              <div className="absolute left-0 top-9 z-40 w-64 rounded-md border border-slate-800 bg-slate-950 p-3 shadow-lg">
                <div className="grid grid-cols-1 gap-3">
                  <div className="space-y-1">
                    <label className="text-[10px] uppercase font-bold text-slate-500">Min Volume</label>
                    <Input
                      value={minVolume}
                      onChange={(e) => setMinVolume(e.target.value)}
                      onFocus={(e) => e.currentTarget.select()}
                      className="h-7 bg-slate-900/60 border-slate-800 text-[10px] text-slate-200"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] uppercase font-bold text-slate-500">Tag</label>
                    <Select value={tagFilter} onValueChange={setTagFilter}>
                      <SelectTrigger className="h-7 px-2 text-[10px]">
                        <SelectValue placeholder="All tags" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All tags</SelectItem>
                        {tagOptions.map((tag) => (
                          <SelectItem key={tag} value={tag}>
                            {tag}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            )}
          </div>
          <Select value={oddsSportKey} onValueChange={setOddsSportKey}>
            <SelectTrigger className="h-7 px-2 text-[10px] min-w-[140px]">
              <SelectValue placeholder="Odds league" />
            </SelectTrigger>
            <SelectContent>
              {oddsSports.map((sport) => (
                <SelectItem key={String(sport.key ?? "")} value={String(sport.key ?? "")}>
                  {sport.title ?? sport.key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2">
            <Button
              onClick={handleFetchOdds}
              className="h-7 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
            >
              {oddsLoading ? "Odds..." : oddsCopied ? "Odds Copied" : "Odds"}
            </Button>
            <Button
              onClick={handleCopyOdds}
              disabled={!oddsReady}
              className={`h-7 px-2 text-[10px] uppercase font-bold border ${
                oddsReady
                  ? "border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
                  : "border-slate-800/60 bg-slate-950/40 text-slate-500"
              }`}
            >
              Copy Odds
            </Button>
          </div>
          {oddsError && (
            <span className="text-[10px] text-amber-400">{oddsError}</span>
          )}
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
          {filtered.slice(0, 500).map((ev) => {
            const isOn = subscribed.has(ev.slug);
            const status = getStatus(ev);
            const displayTime = getDisplayTime(ev);
            const oddsInfo = oddsEvents.length > 0 ? getOddsOutcomes(ev, oddsEvents) : null;
            const rawJson = JSON.stringify(ev.raw ?? ev, null, 2);
            return (
              <div
                key={ev.slug}
                title={rawJson}
                className="flex min-w-[220px] items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2"
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
                  {oddsInfo && (
                    <span className="text-[10px] text-amber-400 font-mono">
                      {oddsInfo
                        .map((item) => `${item.name}: ${(item.implied * 100).toFixed(1)}%`)
                        .join(" A? ")}
                    </span>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2">
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      navigator.clipboard.writeText(rawJson).catch(() => {});
                    }}
                    className="rounded border border-slate-700 bg-slate-950/90 px-2 py-0.5 text-[9px] uppercase font-semibold text-slate-400 hover:text-slate-200 hover:border-slate-500"
                  >
                    Copy
                  </button>
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
