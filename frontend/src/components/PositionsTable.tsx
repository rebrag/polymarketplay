import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export interface PositionRow {
  asset: string;
  size?: number | string;
  avgPrice?: number | string;
  currentValue?: number | string;
  cashPnl?: number | string;
  percentPnl?: number | string;
  title?: string;
  outcome?: string;
}

interface PositionsTableProps {
  positions: PositionRow[];
  onSelect?: (pos: PositionRow) => void;
}

function toNumber(val: number | string | undefined): number {
  if (val === undefined) return 0;
  if (typeof val === "number") return val;
  const parsed = Number(val);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function PositionsTable({ positions, onSelect }: PositionsTableProps) {
  const normalized = positions
    .map((p) => ({
      ...p,
      sizeNum: toNumber(p.size),
      avgNum: toNumber(p.avgPrice),
      valueNum: toNumber(p.currentValue),
      pnlNum: toNumber(p.cashPnl),
      pnlPct: toNumber(p.percentPnl),
    }))
    .filter((p) => p.sizeNum > 0)
    .sort((a, b) => b.valueNum - a.valueNum)
    .slice(0, 12);

  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/50 w-full">
      <div className="px-3 py-2 border-b border-slate-800 bg-slate-950 flex items-center justify-between">
        <span className="text-[10px] uppercase font-bold text-slate-400">Positions</span>
        <Badge variant="outline" className="text-[10px] border-slate-800 text-blue-300 bg-slate-900/50">
          {positions.length} total
        </Badge>
      </div>
      <ScrollArea className="w-full" style={{ height: "250px" }}>
        {normalized.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[11px] text-slate-500">
            No open positions
          </div>
        ) : (
          <Table className="text-xs">
            <TableHeader className="bg-slate-950 sticky top-0 z-10">
              <TableRow className="hover:bg-slate-950 border-slate-800">
                <TableHead className="text-slate-400 h-7 text-[10px]">Market</TableHead>
                <TableHead className="text-slate-400 h-7 text-right text-[10px]">Size</TableHead>
                <TableHead className="text-slate-400 h-7 text-right text-[10px]">Avg</TableHead>
                <TableHead className="text-slate-400 h-7 text-right text-[10px]">Value</TableHead>
                <TableHead className="text-slate-400 h-7 text-right text-[10px] pr-3">P/L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {normalized.map((p) => {
                const pnlClass = p.pnlNum >= 0 ? "text-emerald-400" : "text-red-400";
                const title = p.title || p.outcome || "Unknown";
                return (
                  <TableRow
                    key={p.asset}
                    onClick={() => onSelect?.(p)}
                    className="border-slate-800/50 hover:bg-slate-800/50 h-9 cursor-pointer"
                  >
                    <TableCell className="py-0 align-middle">
                      <div className="flex flex-col">
                        <span className="text-[11px] text-slate-200 truncate max-w-[160px]">{title}</span>
                        <span className="text-[9px] text-slate-500 font-mono truncate max-w-[160px]">{p.asset}</span>
                      </div>
                    </TableCell>
                    <TableCell className="py-0 text-right align-middle font-mono text-[11px] text-slate-200">
                      {p.sizeNum.toFixed(2)}
                    </TableCell>
                    <TableCell className="py-0 text-right align-middle font-mono text-[11px] text-slate-200">
                      {p.avgNum > 0 ? `${(p.avgNum * 100).toFixed(0)}¢` : "--"}
                    </TableCell>
                    <TableCell className="py-0 text-right align-middle font-mono text-[11px] text-slate-200">
                      ${p.valueNum.toFixed(2)}
                    </TableCell>
                    <TableCell className={`py-0 text-right align-middle font-mono text-[11px] pr-3 ${pnlClass}`}>
                      {p.pnlNum >= 0 ? "+" : ""}
                      {p.pnlNum.toFixed(2)} ({p.pnlPct.toFixed(1)}%)
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </ScrollArea>
    </div>
  );
}
