import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export interface OrderView {
  orderID: string;
  asset_id: string;
  market?: string;
  outcome?: string;
  side: "BUY" | "SELL";
  price: string;
  size: string;
  expiration?: number;
  status: "open" | "closed";
  updatedAt: number;
}

interface OrdersPanelProps {
  orders: OrderView[];
}

function formatPrice(price: string): string {
  const val = Number(price);
  if (!Number.isFinite(val)) return price;
  return `${Math.round(val * 100)}¢`;
}

export function OrdersPanel({ orders }: OrdersPanelProps) {
  const sorted = [...orders].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 12);
  return (
    <Card className="border-slate-800 bg-blue-950/90">
      <CardHeader className="py-3 px-4 border-b border-slate-800">
        <CardTitle className="text-xs uppercase tracking-widest text-slate-400">
          Orders
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 space-y-2 text-xs">
        {sorted.length === 0 ? (
          <div className="text-slate-500">No recent orders</div>
        ) : (
          sorted.map((o) => (
            <div
              key={`${o.orderID}-${o.updatedAt}`}
              className="flex items-center justify-between border border-slate-800 rounded px-2 py-1"
            >
              <div className="flex items-center gap-2">
                <Badge className={`text-[9px] uppercase ${
                  o.side === "BUY" ? "bg-blue-600/20 text-blue-300" : "bg-red-600/20 text-red-300"
                }`}>
                  {o.side}
                </Badge>
                <span className="font-mono text-slate-300">{formatPrice(o.price)}</span>
                <span className="text-slate-500">{Number(o.size).toFixed(2)} sh</span>
              </div>
              <span className={`text-[10px] uppercase ${
                o.status === "open" ? "text-emerald-400" : "text-slate-400"
              }`}>
                {o.status}
              </span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
