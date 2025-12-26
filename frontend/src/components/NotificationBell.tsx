import { useCallback, useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import {
  fetchNotificationsList,
  markAllNotificationsAsRead,
  markNotificationAsRead,
  type NotificationItem,
} from "../api";

interface NotificationBellProps {
  onSelectDocument?: (documentId: string) => void;
}

const formatDateTime = (value?: string | null) => {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

export default function NotificationBell({ onSelectDocument }: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const loadNotifications = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
      }
      try {
        const response = await fetchNotificationsList({ limit: 15 });
        setItems(response.items);
        setUnread(response.unread_count);
      } catch (error) {
        console.error(error);
        toast.error("Falha ao carregar notificações.");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadNotifications({ silent: true });
    const interval = window.setInterval(() => {
      void loadNotifications({ silent: true });
    }, 60000);
    return () => window.clearInterval(interval);
  }, [loadNotifications]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (containerRef.current && event.target instanceof Node && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleBellClick = () => {
    setOpen(prev => !prev);
    if (!open) {
      void loadNotifications({ silent: true });
    }
  };

  const handleItemClick = async (item: NotificationItem) => {
    if (!item.id) return;
    try {
      if (!item.read_at) {
        const updated = await markNotificationAsRead(item.id);
        setItems(prev => prev.map(entry => (entry.id === updated.id ? updated : entry)));
        setUnread(value => Math.max(0, value - 1));
      }
    } catch (error) {
      console.error(error);
      toast.error("Falha ao atualizar a notificação.");
    }
    setOpen(false);
    if (onSelectDocument) {
      onSelectDocument(item.document_id);
    }
  };

  const handleMarkAll = async () => {
    setMarkingAll(true);
    try {
      await markAllNotificationsAsRead();
      setItems(prev =>
        prev.map(entry => ({
          ...entry,
          read_at: entry.read_at ?? new Date().toISOString(),
        })),
      );
      setUnread(0);
    } catch (error) {
      console.error(error);
      toast.error("Falha ao marcar as notificações.");
    } finally {
      setMarkingAll(false);
    }
  };

  const renderDescription = (item: NotificationItem) => {
    const signer = item.signer_name || "Participante";
    const document = item.document_name || "Documento";
    return `${signer} assinou ${document}`;
  };

  const hasUnread = unread > 0;

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={handleBellClick}
        className="relative inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-lg text-slate-600 transition hover:bg-slate-100"
        aria-label="Notificações"
      >
        <span role="img" aria-hidden="true">
          🔔
        </span>
        {hasUnread && (
          <span className="absolute -top-1 -right-1 inline-flex min-h-[18px] min-w-[18px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-2xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <p className="text-sm font-semibold text-slate-800">Notificações</p>
            <button
              type="button"
              className="text-xs font-medium text-indigo-600 disabled:opacity-50"
              onClick={handleMarkAll}
              disabled={markingAll || unread === 0}
            >
              {markingAll ? "Processando..." : "Marcar todas"}
            </button>
          </div>
          <div className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
            {loading ? (
              <p className="px-4 py-4 text-sm text-slate-500">Carregando...</p>
            ) : items.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-slate-500">Sem notificações recentes.</p>
            ) : (
              items.map(item => {
                const isUnread = !item.read_at;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`block w-full px-4 py-3 text-left transition ${
                      isUnread ? "bg-indigo-50/80 hover:bg-indigo-100" : "hover:bg-slate-50"
                    }`}
                    onClick={() => handleItemClick(item)}
                  >
                    <p className="text-sm font-semibold text-slate-800">{renderDescription(item)}</p>
                    {item.signer_email && (
                      <p className="text-xs text-slate-500">{item.signer_email}</p>
                    )}
                    <p className="mt-1 text-[11px] uppercase tracking-wide text-slate-400">
                      {formatDateTime(item.created_at)}
                    </p>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
