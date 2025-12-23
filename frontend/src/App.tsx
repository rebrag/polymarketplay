import { useCallback, useEffect, useRef, useState } from "react";
import { OrderBookWidget, type UserPosition } from "./components/OrderBookWidget";
// import { Input } from "@/components/ui/input";
// import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RecentTradesTable, type Trade } from "./components/RecentTradesTable";
import { Navbar } from "./components/Navbar";

interface Market {
  question: string;
  outcomes: string[];
  clobTokenIds: string[];
  volume: number;
}

interface EventData {
  title: string;
  markets: Market[];
}

interface TokenWidget {
  uniqueKey: string;
  outcomeName: string;
  assetId: string;
  marketQuestion: string;
  marketVolume: number;
}

type UserSocketMessage =
  | { type: "new_markets"; markets: Market[] }
  | { type: "recent_trades"; trades: Trade[] };

function App() {
  const [url, setUrl] = useState("0x507e52ef684ca2dd91f90a9d26d149dd3288beae");
  const [minVolume, setMinVolume] = useState([10000]);
  const [loading, setLoading] = useState(false);
  const [eventData, setEventData] = useState<EventData | null>(null);
  const [widgets, setWidgets] = useState<TokenWidget[]>([]);
  const dismissedAssetsRef = useRef<Record<string, true>>({});

  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [positionHistory, setPositionHistory] = useState<Record<string, Trade>>({});

  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(null);
  const highlightTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const userSocketRef = useRef<WebSocket | null>(null);

  const triggerHighlight = (assetId: string) => {
    setHighlightedAsset(assetId);
    if (highlightTimeout.current) window.clearTimeout(highlightTimeout.current);
    highlightTimeout.current = window.setTimeout(() => setHighlightedAsset(null), 700);
  };

  const handleCloseWidget = useCallback((assetId: string) => {
    dismissedAssetsRef.current = { ...dismissedAssetsRef.current, [assetId]: true };
    setWidgets((prev) => prev.filter((w) => w.assetId !== assetId));
    setHighlightedAsset((prev) => (prev === assetId ? null : prev));
  }, []);

  useEffect(() => {
    return () => {
      if (userSocketRef.current) userSocketRef.current.close();
      if (highlightTimeout.current) window.clearTimeout(highlightTimeout.current);
    };
  }, []);

  const handleResolve = async () => {
    if (!url) return;

    if (userSocketRef.current) {
      userSocketRef.current.close();
      userSocketRef.current = null;
    }

    setLoading(true);
    setEventData(null);
    setWidgets([]);
    dismissedAssetsRef.current = {};
    setRecentTrades([]);
    setPositionHistory({});

    const input = url.trim();
    const isAddress = input.startsWith("0x") && input.length === 42;

    if (isAddress) {
      const wsUrl = `ws://localhost:8000/ws/watch/user/${input}?min_volume=${minVolume[0]}`;
      const ws = new WebSocket(wsUrl);
      userSocketRef.current = ws;

      setEventData({ title: `Monitor: ${input.slice(0, 6)}...${input.slice(-4)}`, markets: [] });

      ws.onopen = () => setLoading(false);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as UserSocketMessage;

        if (data.type === "new_markets") {
          const newWidgets: TokenWidget[] = [];

          data.markets.forEach((market) => {
            market.clobTokenIds.forEach((assetId, index) => {
              if (dismissedAssetsRef.current[assetId]) return;
              const outcomeName = market.outcomes[index] || `Outcome ${index + 1}`;
              newWidgets.push({
                uniqueKey: assetId,
                assetId,
                outcomeName,
                marketQuestion: market.question,
                marketVolume: market.volume,
              });
            });
          });

          setWidgets((prev) => {
            const exists = new Set(prev.map((w) => w.uniqueKey));
            const uniqueNew = newWidgets.filter((w) => !exists.has(w.uniqueKey));
            const combined = [...uniqueNew, ...prev];
            return combined.sort((a, b) => b.marketVolume - a.marketVolume);
          });
        }

        if (data.type === "recent_trades") {
          setRecentTrades((prev) => {
            // 1. Create a map of existing hashes for O(1) lookup
            const existingHashes = new Set(prev.map((t) => t.transactionHash));
            
            // 2. Only keep trades we haven't seen yet
            const newUniqueTrades = data.trades.filter(
              (t) => !existingHashes.has(t.transactionHash)
            );

            // 3. Prepend new trades to the front so they appear at the top
            // Then slice to keep the list performant (e.g., last 50 trades)
            return [...newUniqueTrades, ...prev].slice(0, 50);
          });

          setPositionHistory((prev) => {
            const updated = { ...prev };
            data.trades.forEach((t) => {
              // Always update with the latest trade data for an asset 
              // to ensure 'userPosition' in widgets is accurate
              updated[t.asset] = t;
            });
            return updated;
          });
        }
      };

      ws.onerror = () => {
        alert("Error connecting to user stream. Check server console.");
        setLoading(false);
      };

      return;
    }

    // URL / slug resolve mode
    const fullUrl = `http://localhost:8000/events/resolve?query=${encodeURIComponent(input)}&min_volume=${minVolume[0]}`;

    try {
      const res = await fetch(fullUrl);
      if (!res.ok) throw new Error("Failed to resolve target");

      const data = (await res.json()) as EventData;
      setEventData(data);

      const newWidgets: TokenWidget[] = [];
      data.markets.forEach((market) => {
        market.clobTokenIds.forEach((assetId, index) => {
          if (dismissedAssetsRef.current[assetId]) return;
          const outcomeName = market.outcomes[index] || `Outcome ${index + 1}`;
          newWidgets.push({
            uniqueKey: assetId,
            assetId,
            outcomeName,
            marketQuestion: market.question,
            marketVolume: market.volume,
          });
        });
      });

      newWidgets.sort((a, b) => b.marketVolume - a.marketVolume);
      setWidgets(newWidgets);
    } catch (err) {
      console.error(err);
      alert("Error finding event.");
    } finally {
      setLoading(false);
    }
  };

  return (
  <div className="h-screen w-full bg-black font-sans text-slate-200 overflow-hidden flex flex-col">
    {/* Top Navbar with Integrated Search & Balance Monitor */}
    <Navbar 
      userAddress={url.startsWith("0x") ? url : "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"}
      inputValue={url}
      setInputValue={setUrl}
      onResolve={handleResolve}
      loading={loading}
    />
    
    <ScrollArea className="flex-1 w-full">
      {/* Horizontal Dashboard Space */}
      <div className="p-4 max-w-none mx-auto space-y-4">
        
        {/* Header Section: Event Title & Compact Trades Table */}
        {eventData && (
          <div className="flex flex-col lg:flex-row gap-3 justify-between items-start bg-slate-900/20 p-0 rounded-lg">
            <div className="flex-shrink-0">
              <h2 className="text-xl font-bold text-white uppercase tracking-tighter">
                {eventData.title}
              </h2>
              <div className="flex items-center gap-4 mt-1">
                <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-900 bg-blue-900/10">
                  {widgets.length} BOOKS
                </Badge>
                <div className="flex items-center gap-2 min-w-[150px]">
                  <Slider 
                    value={minVolume} 
                    onValueChange={setMinVolume} 
                    max={50000} 
                    step={1000} 
                    className="w-24" 
                  />
                  <span className="text-[10px] text-slate-500 font-mono">
                    ${minVolume[0] / 1000}k+
                  </span>
                </div>
              </div>
            </div>

            {/* Compact Recent Trades Section */}
            {recentTrades.length > 0 && (
              <div className="w-full lg:w-2/3">
                <RecentTradesTable 
                  trades={recentTrades} 
                  onInteract={triggerHighlight} 
                />
              </div>
            )}
          </div>
        )}

        {/* High-Density Order Book Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4 pb-3">
          {widgets.map((w, index) => {
            const match = positionHistory[w.assetId];

            let userPos: UserPosition | null = null;
            if (match) {
              const shares = Number(match.size);
              const value = Number(match.usdcSize);
              const price = shares > 0 ? value / shares : 0;
              userPos = { side: match.side, price, shares };
            }

            // High-density optimization: first 10 books are "full", rest are "mini"
            const isFullMode = index < 10;

            return (
              <div key={w.uniqueKey} className="flex flex-col gap-1">
                <span 
                  className="text-[9px] text-slate-500 uppercase font-bold truncate px-1" 
                  title={w.marketQuestion}
                >
                  {w.marketQuestion}
                </span>
                <OrderBookWidget
                  assetId={w.assetId}
                  outcomeName={w.outcomeName}
                  volume={w.marketVolume}
                  userPosition={userPos}
                  isHighlighted={highlightedAsset === w.assetId}
                  viewMode={isFullMode ? "full" : "mini"}
                  onClose={handleCloseWidget}
                  apiBaseUrl="http://localhost:8000"
                />
              </div>
            );
          })}
        </div>
      </div>
    </ScrollArea>
  </div>
);
}

export default App;
