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
  markets?: {
    question: string;
    volume?: number;
    gameStartTime?: string;
    outcomes?: string[];
    clobTokenIds?: string[];
  }[];
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

interface MoneylineToken {
  tokenId: string;
  outcome: string;
}

interface MoneylinePricesResponse {
  items?: Array<{ token_id?: string; best_ask?: number | null; best_bid?: number | null }>;
}

const BOOKS_BATCH_MIN_INTERVAL_MS = 10_000;

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

function normalizeMarketQuestion(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function normalizeTeamName(name: string): string {
  const cleaned = name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  const stop = new Set(["fc", "cf", "afc", "sc", "club", "the", "utd", "united"]);
  return parts.filter((p) => !stop.has(p)).join(" ");
}

function isSoccerEvent(ev: LiveEvent): boolean {
  const raw = (ev.raw ?? {}) as {
    tags?: Array<{ name?: string; label?: string; slug?: string; id?: string | number }>;
  };
  const tags = raw.tags ?? [];
  return tags.some((tag) => {
    const values = [tag?.name, tag?.label, tag?.slug].map((v) => String(v ?? "").toLowerCase());
    return values.some((v) => v.includes("soccer"));
  });
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

function getMoneylineTokens(ev: LiveEvent): MoneylineToken[] {
  const normalizeRows = (
    rows: MoneylineToken[],
    max: number,
    dedupeByOutcome: boolean = false
  ): MoneylineToken[] => {
    const seen = new Set<string>();
    const out: MoneylineToken[] = [];
    for (const row of rows) {
      const token = String(row.tokenId ?? "");
      const outcome = String(row.outcome ?? "");
      if (!token || !outcome) continue;
      const key = dedupeByOutcome ? outcome.toLowerCase() : `${token}|${outcome.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ tokenId: token, outcome });
      if (out.length >= max) break;
    }
    return out;
  };

  const markets = ev.markets ?? [];
  if (!markets.length) return [];
  if (isSoccerEvent(ev)) {
    const teams = extractTeams(ev.title);
    if (!teams) return [];
    const [teamA, teamB] = teams;
    const normA = normalizeTeamName(teamA);
    const normB = normalizeTeamName(teamB);

    const getYesToken = (m: (typeof markets)[number]): string | null => {
      const outcomes = m.outcomes ?? [];
      const tokenIds = m.clobTokenIds ?? [];
      for (let i = 0; i < outcomes.length && i < tokenIds.length; i += 1) {
        if (String(outcomes[i] ?? "").trim().toLowerCase() === "yes") {
          const token = String(tokenIds[i] ?? "");
          return token || null;
        }
      }
      if (tokenIds.length > 0) {
        const token = String(tokenIds[0] ?? "");
        return token || null;
      }
      return null;
    };

    const used = new Set<number>();
    const pickMarket = (predicate: (q: string) => boolean): (typeof markets)[number] | null => {
      for (let i = 0; i < markets.length; i += 1) {
        if (used.has(i)) continue;
        const q = normalizeTeamName(markets[i].question ?? "");
        if (!predicate(q)) continue;
        used.add(i);
        return markets[i];
      }
      return null;
    };

    const marketDraw = pickMarket((q) => q.includes("draw"));
    const marketA = pickMarket((q) => q.includes("win") && !q.includes("draw") && !!normA && q.includes(normA));
    const marketB = pickMarket((q) => q.includes("win") && !q.includes("draw") && !!normB && q.includes(normB));

    const rows: MoneylineToken[] = [];
    if (marketA) {
      const token = getYesToken(marketA);
      if (token) rows.push({ tokenId: token, outcome: teamA });
    }
    if (marketDraw) {
      const token = getYesToken(marketDraw);
      if (token) rows.push({ tokenId: token, outcome: "Draw" });
    }
    if (marketB) {
      const token = getYesToken(marketB);
      if (token) rows.push({ tokenId: token, outcome: teamB });
    }
    if (rows.length >= 3) return normalizeRows(rows, 3, true);

    // Fallback for single trinary soccer market with outcomes [Team A, Draw, Team B].
    for (const market of markets) {
      const outcomes = market.outcomes ?? [];
      const tokenIds = market.clobTokenIds ?? [];
      if (outcomes.length < 3 || tokenIds.length < 3) continue;
      const mapped: MoneylineToken[] = [];
      for (let i = 0; i < outcomes.length && i < tokenIds.length; i += 1) {
        const out = String(outcomes[i] ?? "");
        const outNorm = normalizeTeamName(out);
        const token = String(tokenIds[i] ?? "");
        if (!token) continue;
        if (outNorm.includes("draw")) mapped.push({ tokenId: token, outcome: "Draw" });
        else if (normA && outNorm.includes(normA)) mapped.push({ tokenId: token, outcome: teamA });
        else if (normB && outNorm.includes(normB)) mapped.push({ tokenId: token, outcome: teamB });
      }
      const normalized = normalizeRows(mapped, 3, true);
      if (normalized.length >= 3) return normalized;
    }
  }

  const titleNorm = normalizeMarketQuestion(ev.title);
  const byExactTitle = markets.filter((m) => normalizeMarketQuestion(m.question) === titleNorm);
  const byQuestion = byExactTitle.length ? byExactTitle : markets;
  const preferred = byQuestion.filter((m) => {
    const q = normalizeMarketQuestion(m.question);
    if (q.includes("spread")) return false;
    if (q.includes(" o/u ")) return false;
    if (q.includes(" over/under")) return false;
    if (q.includes("total points")) return false;
    return true;
  });
  const pool = preferred.length ? preferred : byQuestion;
  for (const market of pool) {
    const outcomes = market.outcomes ?? [];
    const tokenIds = market.clobTokenIds ?? [];
    if (outcomes.length < 2 || tokenIds.length < 2) continue;
    const rows: MoneylineToken[] = [];
    for (let i = 0; i < outcomes.length && i < tokenIds.length; i += 1) {
      const tokenId = String(tokenIds[i] ?? "");
      const outcome = String(outcomes[i] ?? "");
      if (!tokenId || !outcome) continue;
      rows.push({ tokenId, outcome });
    }
    if (rows.length >= 2) return normalizeRows(rows, 2);
  }
  return [];
}

function shortOutcome(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "N/A";
  if (trimmed.toLowerCase() === "draw") return "DRAW";
  const token = trimmed.split(/\s+/)[0] ?? trimmed;
  return token.toUpperCase().slice(0, 4);
}

function formatCents(price: number | null | undefined): string {
  if (price === null || price === undefined || !Number.isFinite(price)) return "100c";
  return `${Math.round(price * 100)}c`;
}

function getStatus(ev: LiveEvent): "live" | "upcoming" | "unknown" {
  const now = Date.now();
  const gameStart = getEventGameStart(ev);
  const start = parseDate(gameStart)?.getTime() ?? null;
  if (start !== null && now < start) return "upcoming";
  if (start !== null && now >= start) return "live";
  return "unknown";
}

function isClosedByMoneylinePrices(
  moneyline: MoneylineToken[],
  askLookup: Record<string, number | null>
): boolean {
  if (moneyline.length < 2) return false;
  const cents = moneyline
    .map((row) => {
      const v = askLookup[row.tokenId];
      if (typeof v === "number" && Number.isFinite(v)) return Math.round(v * 100);
      return 100;
    });
  if (cents.length < 2) return false;
  const min = Math.min(...cents);
  const max = Math.max(...cents);
  return min <= 1 && max >= 99;
}

function getDisplayTime(ev: LiveEvent): string | null {
  const gameStart = getEventGameStart(ev);
  if (!gameStart) return null;
  return formatStart(gameStart);
}

function loadLiveFilters(): { minVolume: string; tagFilter: string; hideMoreMarkets: boolean } {
  try {
    const raw = localStorage.getItem("pm_live_filters");
    if (!raw) return { minVolume: "0", tagFilter: "all", hideMoreMarkets: true };
    const parsed = JSON.parse(raw) as { minVolume?: string; tagFilter?: string; hideMoreMarkets?: boolean };
    return {
      minVolume: typeof parsed.minVolume === "string" ? parsed.minVolume : "0",
      tagFilter: typeof parsed.tagFilter === "string" ? parsed.tagFilter : "all",
      hideMoreMarkets: parsed.hideMoreMarkets !== false,
    };
  } catch {
    return { minVolume: "0", tagFilter: "all", hideMoreMarkets: true };
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
  const [oddsData] = useState<OddsResponse | null>(null);
  const [oddsSports, setOddsSports] = useState<OddsSport[]>([]);
  const [oddsSportKey, setOddsSportKey] = useState(loadOddsSport());
  const initialFilters = useMemo(() => loadLiveFilters(), []);
  const [minVolume, setMinVolume] = useState(initialFilters.minVolume);
  const [tagFilter, setTagFilter] = useState(initialFilters.tagFilter);
  const [hideMoreMarkets, setHideMoreMarkets] = useState(initialFilters.hideMoreMarkets);
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
      if (hideMoreMarkets && String(ev.slug ?? "").toLowerCase().includes("more-markets")) return false;
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
  }, [query, sorted, minVolume, tagFilter, hideMoreMarkets]);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [copiedRaw, setCopiedRaw] = useState(false);
  const [moneylineAsks, setMoneylineAsks] = useState<Record<string, number | null>>({});
  const lastBooksBatchFetchMsRef = useRef(0);

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

    const rafUpdate = () => {
      window.requestAnimationFrame(update);
    };

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    const observer = new ResizeObserver(rafUpdate);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      observer.disconnect();
    };
  }, [sorted.length, filtered.length]);

  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    window.requestAnimationFrame(() => {
      const maxScrollLeft = el.scrollWidth - el.clientWidth;
      setCanScrollLeft(el.scrollLeft > 0);
      setCanScrollRight(el.scrollLeft < maxScrollLeft - 1);
    });
  }, [filtered.length]);
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
      localStorage.setItem("pm_live_filters", JSON.stringify({ minVolume, tagFilter, hideMoreMarkets }));
    } catch {
      // ignore
    }
  }, [minVolume, tagFilter, hideMoreMarkets]);

  const visibleMoneylineTokens = useMemo(() => {
    const ids: string[] = [];
    filtered.slice(0, 500).forEach((ev) => {
      getMoneylineTokens(ev).forEach((row) => ids.push(row.tokenId));
    });
    return Array.from(new Set(ids));
  }, [filtered]);

  useEffect(() => {
    if (!visibleMoneylineTokens.length) {
      setMoneylineAsks({});
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      if (now - lastBooksBatchFetchMsRef.current < BOOKS_BATCH_MIN_INTERVAL_MS) return;
      lastBooksBatchFetchMsRef.current = now;
      try {
        const res = await fetch("http://localhost:8000/books/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token_ids: visibleMoneylineTokens }),
        });
        if (!res.ok) return;
        const payload = (await res.json()) as MoneylinePricesResponse;
        if (cancelled) return;
        const next: Record<string, number | null> = {};
        (payload.items ?? []).forEach((item) => {
          const tokenId = String(item.token_id ?? "");
          if (!tokenId) return;
          const ask = item.best_ask;
          next[tokenId] = typeof ask === "number" && Number.isFinite(ask) ? ask : null;
        });
        setMoneylineAsks(next);
      } catch {
        // no-op
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), BOOKS_BATCH_MIN_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [visibleMoneylineTokens]);

  const liveEventSlugs = useMemo(() => {
    const slugs: string[] = [];
    for (const ev of filtered.slice(0, 500)) {
      const hidePreviewPills = String(ev.slug ?? "").toLowerCase().includes("more-markets");
      const moneyline = hidePreviewPills ? [] : getMoneylineTokens(ev);
      const previewPills = moneyline.slice(0, 3);
      const status = isClosedByMoneylinePrices(previewPills, moneylineAsks) ? "closed" : getStatus(ev);
      if (status === "live" && !subscribed.has(ev.slug)) {
        slugs.push(ev.slug);
      }
    }
    return slugs;
  }, [filtered, moneylineAsks, subscribed]);
  const liveEventsCount = useMemo(() => {
    let count = 0;
    for (const ev of filtered.slice(0, 500)) {
      const hidePreviewPills = String(ev.slug ?? "").toLowerCase().includes("more-markets");
      const moneyline = hidePreviewPills ? [] : getMoneylineTokens(ev);
      const previewPills = moneyline.slice(0, 3);
      const status = isClosedByMoneylinePrices(previewPills, moneylineAsks) ? "closed" : getStatus(ev);
      if (status === "live") count += 1;
    }
    return count;
  }, [filtered, moneylineAsks]);

  return (
    <div className="relative rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">Live Markets</span>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search (${filtered.length}) events. (${liveEventsCount} LIVE)`}
            className="h-7 w-60 bg-slate-900/60 border-slate-800 text-[10px] text-slate-200"
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
          <Button
            onClick={() => {
              liveEventSlugs.forEach((slug) => onAdd(slug));
            }}
            disabled={liveEventSlugs.length === 0}
            className={`h-7 px-2 text-[10px] uppercase font-bold border ${
              liveEventSlugs.length > 0
                ? "border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
                : "border-slate-800/60 bg-slate-950/40 text-slate-500"
            }`}
          >
            Add All Live
          </Button>
          <Button
            onClick={() => setHideMoreMarkets((v: boolean) => !v)}
            className={`h-7 px-2 text-[10px] uppercase font-bold border ${
              hideMoreMarkets
                ? "border-emerald-700 bg-emerald-900/30 text-emerald-100 hover:text-white"
                : "border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
            }`}
          >
            {hideMoreMarkets ? "Hide More-Markets" : "Show More-Markets"}
          </Button>
          {/* <Select value={oddsSportKey} onValueChange={setOddsSportKey}>
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
          </div> */}
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
            const displayTime = getDisplayTime(ev);
            const oddsInfo = oddsEvents.length > 0 ? getOddsOutcomes(ev, oddsEvents) : null;
            const rawJson = JSON.stringify(ev.raw ?? ev, null, 2);
            const hidePreviewPills = String(ev.slug ?? "").toLowerCase().includes("more-markets");
            const moneyline = hidePreviewPills ? [] : getMoneylineTokens(ev);
            const previewPills = moneyline.slice(0, 3);
            const status = isClosedByMoneylinePrices(previewPills, moneylineAsks) ? "closed" : getStatus(ev);
            return (
              <div
                key={ev.slug}
                title={rawJson}
                className="flex h-[95px] min-w-[220px] max-w-[220px] flex-col rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2"
              >
                <div className="flex min-h-0 items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="h-4 truncate text-[10px] uppercase font-bold text-slate-400">
                      {displayTime ? displayTime : "Upcoming"}
                      {status === "live" && (
                        <>
                          <span className="ml-2 text-red-400">LIVE</span>
                          <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-red-500 align-middle" />
                        </>
                      )}
                      {status === "closed" && (
                        <>
                          <span className="ml-2 text-slate-300">CLOSED</span>
                          <span className="ml-1 align-middle text-[10px]">🔒</span>
                        </>
                      )}
                    </span>
                    <span className="truncate text-[11px] font-semibold text-slate-200">{shortTitle(ev.title)}</span>
                    <span className="h-4 text-[10px] text-slate-500 font-mono">{formatVol(ev.volume)} vol</span>
                    {oddsInfo && (
                      <span className="truncate text-[10px] text-amber-400 font-mono">
                        {oddsInfo
                          .map((item) => `${item.name}: ${(item.implied * 100).toFixed(1)}%`)
                          .join(" A? ")}
                      </span>
                    )}
                  </div>
                  <div className="flex h-full flex-col items-end justify-between gap-2">
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        navigator.clipboard.writeText(rawJson).catch(() => {});
                      }}
                      className="h-5 rounded border border-slate-700 bg-slate-950/90 px-2 py-0.5 text-[9px] uppercase font-semibold text-slate-400 hover:text-slate-200 hover:border-slate-500"
                    >
                      Copy
                    </button>
                    <Button
                      onClick={() => (isOn ? onRemove(ev.slug) : onAdd(ev.slug))}
                      className={`h-7 w-[72px] px-0 text-[10px] uppercase font-bold ${
                        isOn
                          ? "bg-slate-800 border border-slate-700 hover:bg-slate-700"
                          : "bg-blue-600 hover:bg-blue-500"
                      }`}
                    >
                      {isOn ? "Remove" : "Add"}
                    </Button>
                  </div>
                </div>
                {previewPills.length >= 2 && (
                  <div
                    className={`mt-2 grid w-full gap-1 ${
                      previewPills.length >= 3 ? "grid-cols-3" : previewPills.length === 2 ? "grid-cols-2" : "grid-cols-1"
                    }`}
                  >
                    {previewPills.map((row, idx) => (
                      <span
                        key={`${row.tokenId}-${row.outcome}-${idx}`}
                        className="w-full truncate rounded bg-slate-800 px-1.5 py-[1px] text-center text-[9px] font-semibold text-slate-200"
                        title={row.outcome}
                      >
                        {shortOutcome(row.outcome)} {formatCents(moneylineAsks[row.tokenId])}
                      </span>
                    ))}
                  </div>
                )}
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
