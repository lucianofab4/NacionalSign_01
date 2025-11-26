import React from 'react';
import { resolveApiBaseUrl } from '../utils/env';

const apiBase = resolveApiBaseUrl();
const isMock = String((import.meta as any).env?.VITE_MOCK ?? '').toLowerCase() === '1' || String((import.meta as any).env?.VITE_MOCK ?? '').toLowerCase() === 'true';

function hostOf(url: string): string {
  try {
    const u = new URL(url);
    return u.host;
  } catch {
    return url;
  }
}

export default function EnvBadge() {
  return (
    <div className="inline-flex items-center gap-2 rounded-full bg-slate-800/70 px-3 py-1 text-xs text-slate-200 border border-slate-700">
      <span className="opacity-80">API:</span>
      <span className="font-mono">{hostOf(apiBase)}</span>
      {isMock && <span className="ml-1 rounded-full bg-amber-500/90 px-2 py-0.5 text-[10px] font-semibold text-white">MOCK</span>}
    </div>
  );
}
