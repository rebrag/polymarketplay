// import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface NavbarProps {
  userAddress: string;
  inputValue: string;
  setInputValue: (val: string) => void;
  onResolve: () => void;
  loading: boolean;
  apiBaseUrl?: string;
}

// interface BalanceData {
//   portfolioValue: number;
//   cash: number;
// }

export function Navbar({ 
//   userAddress, 
  inputValue, 
  setInputValue, 
  onResolve, 
  loading,
//   apiBaseUrl = "http://localhost:8000" 
}: NavbarProps) {
//   const [data, setData] = useState<BalanceData>({ portfolioValue: 0, cash: 0 });

//   useEffect(() => {
//     const fetchBalance = async () => {
//       try {
//         const res = await fetch(`${apiBaseUrl}/user/balance?address=${userAddress}`);
//         const json = await res.json();
//         setData({ portfolioValue: json.portfolio || 0, cash: json.cash || 0 });
//       } catch (e) {
//         console.error("Balance fetch failed", e);
//       }
//     };
//     fetchBalance();
//     const interval = setInterval(fetchBalance, 990000);
//     return () => clearInterval(interval);
//   }, [userAddress, apiBaseUrl]);

  return (
    <nav className="flex items-center justify-between px-6 py-2 border-b border-slate-800 bg-[#0f172a] sticky top-0 z-50 h-14">
      {/* Left: Branding */}
      <div className="flex items-center gap-3 min-w-[180px]">
        <div className="flex -space-x-1">
          <div className="w-3 h-6 bg-blue-600 rounded-full animate-pulse" />
          <div className="w-3 h-6 bg-blue-400 rounded-full" />
        </div>
        <span className="text-lg font-black italic text-white uppercase tracking-tighter">
          Poly<span className="text-blue-500">Terminal</span>
        </span>
      </div>

      {/* Center: Expanded Search Bar */}
      <div className="flex items-center gap-2 flex-1 max-w-4xl px-4">
        <div className="relative w-full">
          <Input
            placeholder="Search URL, Slug, or 0x..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onResolve()}
            className="bg-slate-900/50 border-slate-700 h-9 pl-9 text-xs text-slate-200 focus:bg-slate-900 transition-all w-full"
          />
          <span className="absolute left-3 top-2.5 text-slate-500 text-xs">🔍</span>
        </div>
        <Button onClick={onResolve} disabled={loading} className="bg-blue-600 h-8 px-6 text-[11px] font-bold uppercase">
          {loading ? "..." : "Load"}
        </Button>
      </div>

      {/* Right: Metrics Only */}
      <div className="flex items-center gap-6 min-w-[220px] justify-end">
        <div className="flex flex-col items-end">
          <span className="text-[9px] text-slate-500 uppercase font-bold">Portfolio</span>
          {/* <span className="text-sm font-bold text-emerald-400 font-mono">${data.portfolioValue.toFixed(2)}</span> */}
          <span className="text-sm font-bold text-emerald-400 font-mono">${0.00}</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[9px] text-slate-500 uppercase font-bold">Cash</span>
          {/* <span className="text-sm font-bold text-emerald-400 font-mono">${data.cash.toFixed(2)}</span> */}
        </div>
      </div>
    </nav>
  );
}