export interface OrderLevel {
  price: number;
  size: number;
  cum: number;
}

export interface LastTrade {
  price: number;
  size: number;
  side: "BUY" | "SELL";
  timestamp: number;
}

export interface BookState {
  ready: boolean;
  msg_count: number;
  bids: OrderLevel[];
  asks: OrderLevel[];
  tick_size: number;
  last_trade?: LastTrade;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function isOrderLevel(v: unknown): v is OrderLevel {
  if (!isRecord(v)) return false;
  return typeof v.price === "number" && typeof v.size === "number" && typeof v.cum === "number";
}

export function parseBookState(payload: unknown): BookState | null {
  if (!isRecord(payload)) return null;
  if (payload.status === "loading") return null;

  const { ready, msg_count, bids, asks, tick_size } = payload;
  if (typeof ready !== "boolean" || typeof msg_count !== "number") return null;
  if (!Array.isArray(bids) || !Array.isArray(asks)) return null;

  let lastTrade: LastTrade | undefined;
  const rawLast = (payload as { last_trade?: unknown }).last_trade;
  if (isRecord(rawLast)) {
    const price = Number(rawLast.price);
    const size = Number(rawLast.size);
    const timestamp = Number(rawLast.timestamp);
    const side = String(rawLast.side || "").toUpperCase();
    if (
      Number.isFinite(price) &&
      Number.isFinite(size) &&
      Number.isFinite(timestamp) &&
      (side === "BUY" || side === "SELL")
    ) {
      lastTrade = { price, size, timestamp, side } as LastTrade;
    }
  }

  return {
    ready,
    msg_count,
    bids: bids.filter(isOrderLevel),
    asks: asks.filter(isOrderLevel),
    tick_size: typeof tick_size === "number" ? tick_size : 0.01,
    last_trade: lastTrade,
  };
}
