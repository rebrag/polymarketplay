import { useEffect, useRef, useMemo, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

export interface Trade {
  transactionHash: string;
  timestamp: number;
  side: "BUY" | "SELL";
  outcome: string;
  size: string;
  usdcSize: string;
  title: string;
  asset: string; 
}

interface RecentTradesTableProps {
  trades: Trade[];
  onInteract: (assetId: string) => void;
}

function formatTimeAgo(timestamp: number, currentNow: number): string {
  const seconds = Math.max(0, Math.floor((currentNow - timestamp * 1000) / 1000));
  if (seconds < 60) return "Just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export function RecentTradesTable({ trades, onInteract }: RecentTradesTableProps) {
  const lastHashRef = useRef<string | null>(null);
  const isFirstRender = useRef(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  
  // FIX: Initialize state with a function to ensure purity
  const [now, setNow] = useState<number>(() => Date.now());

  const sortedTrades = useMemo(() => {
    return [...trades].sort((a, b) => {
      if (b.timestamp !== a.timestamp) return b.timestamp - a.timestamp;
      return b.transactionHash.localeCompare(a.transactionHash);
    });
  }, [trades]);

  // Handle "ticker" and Audio Initialization
  useEffect(() => {
    // FIX: Initialize audio inside useEffect to avoid "Accessing ref during render"
    if (!audioRef.current) {
      audioRef.current = new Audio("https://codeskulptor-demos.commondatastorage.googleapis.com/pang/pop.mp3");
    }

    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (sortedTrades.length === 0) return;
    const latestTrade = sortedTrades[0];
    
    if (lastHashRef.current !== latestTrade.transactionHash) {
      if (!isFirstRender.current && audioRef.current) {
        const sfx = audioRef.current;
        sfx.currentTime = 0;
        sfx.volume = 0.4;
        sfx.play().catch(() => {});
        onInteract(latestTrade.asset);
      }
      lastHashRef.current = latestTrade.transactionHash;
    }
    isFirstRender.current = false;
  }, [sortedTrades, onInteract]);

  return (
    <ScrollArea className="rounded-md border border-slate-800 bg-slate-900/50 w-full select-none" style={{ height: "250px" }}>
      <div className="w-full text-xs">
        <Table>
          <TableHeader className="bg-slate-950 sticky top-0 z-10">
            <TableRow className="hover:bg-slate-950 border-slate-800">
              <TableHead className="text-slate-400 h-7 w-12 text-[10px]">Type</TableHead>
              <TableHead className="text-slate-400 h-7 text-[10px]">Market</TableHead>
              <TableHead className="text-slate-400 h-7 text-right text-[10px] pr-4">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedTrades.map((t) => {
              const shares = parseFloat(t.size);
              const totalValue = parseFloat(t.usdcSize);
              const price = shares > 0 ? (totalValue / shares) : 0;
              const priceDisplay = price < 1 ? `${(price * 100).toFixed(0)}¢` : `$${price.toFixed(2)}`;

              return (
                <TableRow 
                  key={t.transactionHash} 
                  onClick={() => onInteract(t.asset)}
                  className="border-slate-800/50 hover:bg-slate-800/50 cursor-pointer h-9 transition-colors"
                >
                  <TableCell className="py-0 align-middle">
                    <Badge className={`font-mono border-0 text-[9px] px-1 py-0 uppercase ${
                      t.side === "BUY" ? "text-blue-400 bg-blue-400/10" : "text-red-400 bg-red-400/10"
                    }`}>
                      {t.side}
                    </Badge>
                  </TableCell>
                  
                  <TableCell className="py-0 align-middle">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-200 truncate max-w-[140px] text-[11px]">{t.title}</span>
                      <div className={`px-1 rounded flex items-center gap-1 font-mono text-[10px] ${
                         t.side === "BUY" ? "bg-slate-800 text-emerald-400" : "bg-slate-800 text-orange-400"
                      }`}>
                        <span className="font-bold">{t.outcome}</span>
                        <span className="opacity-80">{priceDisplay}</span>
                      </div>
                    </div>
                  </TableCell>

                  <TableCell className="py-0 text-right align-middle pr-4">
                    <div className="flex flex-col leading-none">
                      <span className="font-mono text-slate-200 text-[11px] font-medium">${totalValue.toFixed(2)}</span>
                      <span className="text-[9px] text-slate-500 font-mono">
                        {shares.toFixed(1)} sh • {formatTimeAgo(t.timestamp, now)}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </ScrollArea>
  );
}