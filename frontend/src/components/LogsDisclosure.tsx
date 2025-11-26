import { useState } from "react";

interface LogsDisclosureProps {
  title?: string;
  entries: Array<{
    id?: string;
    created_at?: string;
    event_type?: string;
    description?: string | null;
    details?: unknown;
  }>;
}

export default function LogsDisclosure({ title = "Logs", entries }: LogsDisclosureProps) {
  const [open, setOpen] = useState(false);
  if (!entries || entries.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-slate-700"
        onClick={() => setOpen(value => !value)}
      >
        <span>{title}</span>
        <span className="text-xs text-slate-500">{open ? "Ocultar" : "Exibir"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-600 space-y-2">
          {entries.map((entry, index) => (
            <div key={entry.id ?? `${entry.event_type}-${entry.created_at ?? index}`}>
              <div className="font-semibold text-slate-700">
                {entry.event_type ?? "evento"}{" "}
                {entry.created_at ? `· ${new Date(entry.created_at).toLocaleString()}` : null}
              </div>
              {entry.description && <div>{entry.description}</div>}
              {entry.details && typeof entry.details === "object" && (
                <pre className="bg-slate-50 text-[11px] text-slate-500 rounded-lg px-3 py-2 overflow-x-auto">
                  {JSON.stringify(entry.details, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
