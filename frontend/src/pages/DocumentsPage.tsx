import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { isAxiosError } from "axios";

import {
  archiveDocument,
  deleteDocument,
  fetchDocuments,
  resendDocumentNotifications,
  type DocumentRecord,
  type Usage,
  type UserMe,
} from "../api";

export type DocumentListFilter = "all" | "my_pending" | "area_pending";

type DocumentStatusFilter = "all" | "draft" | "in_review" | "in_progress" | "completed" | "archived";

interface DocumentsPageProps {
  tenantId: string;
  areaId?: string;
  usage?: Usage | null;
  currentUser?: UserMe | null;
  focusFilter?: DocumentListFilter | null;
  onFocusConsumed?: () => void;
  onCreateNew?: () => void;
}

type PendingAction =
  | { type: "resend"; document: DocumentRecord }
  | { type: "archive"; document: DocumentRecord }
  | { type: "unarchive"; document: DocumentRecord }
  | { type: "delete"; document: DocumentRecord };

const statusTabs: Array<{ value: DocumentStatusFilter; label: string }> = [
  { value: "all", label: "Todos" },
  { value: "draft", label: "Rascunhos" },
  { value: "in_review", label: "Em revisão" },
  { value: "in_progress", label: "Em andamento" },
  { value: "completed", label: "Concluídos" },
  { value: "archived", label: "Arquivados" },
];

const formatDateTime = (value: string | null | undefined) => {
  if (!value) return "-";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

const normalizeStatus = (status?: string | null) => (status ?? "").toLowerCase();

const statusBadgeClasses = (status: string | null | undefined) => {
  switch (normalizeStatus(status)) {
    case "draft":
      return "bg-slate-100 text-slate-600";
    case "in_review":
      return "bg-amber-100 text-amber-700";
    case "in_progress":
      return "bg-sky-100 text-sky-700";
    case "completed":
    case "signed":
      return "bg-emerald-100 text-emerald-700";
    case "archived":
      return "bg-slate-200 text-slate-700";
    default:
      return "bg-slate-100 text-slate-600";
  }
};

const statusLabel = (status: string | null | undefined) => {
  const normalized = normalizeStatus(status);
  switch (normalized) {
    case "draft":
      return "Rascunho";
    case "in_review":
      return "Em revisão";
    case "in_progress":
      return "Em andamento";
    case "completed":
    case "signed":
      return "Concluído";
    case "archived":
      return "Arquivado";
    default:
      return status ? status.replace(/_/g, " ") : "—";
  }
};

const getActionTitle = (type: PendingAction["type"]) => {
  switch (type) {
    case "resend":
      return "Reenviar notificações";
    case "archive":
      return "Arquivar documento";
    case "unarchive":
      return "Desarquivar documento";
    case "delete":
      return "Excluir documento";
    default:
      return "Confirmar ação";
  }
};

const getActionDescription = (type: PendingAction["type"], name: string) => {
  switch (type) {
    case "resend":
      return `Vamos reenviar os convites de assinatura para "${name}".`;
    case "archive":
      return `Arquivar "${name}" remove o documento da lista ativa, mas mantém o histórico para consulta.`;
    case "unarchive":
      return `Desarquivar "${name}" devolve o documento à listagem ativa.`;
    case "delete":
      return `Excluir "${name}" remove permanentemente o documento e suas versões. Esta ação não pode ser desfeita.`;
    default:
      return "";
  }
};

const getConfirmLabel = (type: PendingAction["type"]) => {
  switch (type) {
    case "resend":
      return "Reenviar";
    case "archive":
      return "Arquivar";
    case "unarchive":
      return "Desarquivar";
    case "delete":
      return "Excluir";
    default:
      return "Confirmar";
  }
};

export default function DocumentsPage({
  tenantId,
  areaId,
  usage = null,
  currentUser = null,
  focusFilter = null,
  onFocusConsumed,
  onCreateNew,
}: DocumentsPageProps) {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [documentFilter, setDocumentFilter] = useState<DocumentListFilter>("all");
  const [statusFilter, setStatusFilter] = useState<DocumentStatusFilter>("all");
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const selectAllRef = useRef<HTMLInputElement | null>(null);

  const documentsQuota = usage?.documents_quota ?? null;
  const documentsUsed = usage?.documents_used ?? 0;
  const documentLimitReached = documentsQuota !== null && documentsUsed >= documentsQuota;
  const areaReady = Boolean(areaId);

  const pendingStatuses = useMemo(() => new Set(["in_review", "in_progress"]), []);

  const loadDocuments = useCallback(async () => {
    if (!tenantId) {
      setDocuments([]);
      setSelectedIds(new Set());
      return;
    }
    setLoadingDocs(true);
    try {
      const list = await fetchDocuments(areaId);
      setDocuments(list);
      setSelectedIds(new Set());
    } catch (error) {
      console.error(error);
      toast.error("Erro ao carregar documentos.");
    } finally {
      setLoadingDocs(false);
    }
  }, [tenantId, areaId]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!focusFilter) return;
    setDocumentFilter(focusFilter);
    if (focusFilter === "my_pending") {
      toast.success("Mostrando documentos pendentes criados por você.");
    } else if (focusFilter === "area_pending") {
      toast.success("Mostrando pendentes na sua área.");
    }
    onFocusConsumed?.();
  }, [focusFilter, onFocusConsumed]);

  useEffect(() => {
    setSelectedIds(new Set());
  }, [documentFilter, statusFilter]);

  const filteredByAudience = useMemo(() => {
    if (documentFilter === "all") return documents;
    if (documentFilter === "my_pending") {
      if (!currentUser) return [];
      return documents.filter(
        doc => doc.created_by_id === currentUser.id && pendingStatuses.has(normalizeStatus(doc.status)),
      );
    }
    if (documentFilter === "area_pending") {
      return documents.filter(doc => {
        const matchesArea = areaId ? doc.area_id === areaId : true;
        return matchesArea && pendingStatuses.has(normalizeStatus(doc.status));
      });
    }
    return documents;
  }, [documents, documentFilter, currentUser, areaId, pendingStatuses]);

  const visibleDocuments = useMemo(() => {
    return filteredByAudience
      .filter(doc => {
        if (statusFilter === "all") return true;
        const normalized = normalizeStatus(doc.status);
        if (statusFilter === "completed") {
          return normalized === "completed" || normalized === "signed";
        }
        return normalized === statusFilter;
      })
      .sort((a, b) => {
        const dateA = new Date(a.updated_at ?? a.created_at ?? "").getTime();
        const dateB = new Date(b.updated_at ?? b.created_at ?? "").getTime();
        return dateB - dateA;
      });
  }, [filteredByAudience, statusFilter]);

  const selectedDocuments = useMemo(
    () => documents.filter(doc => selectedIds.has(doc.id)),
    [documents, selectedIds],
  );
  const selectedCount = selectedDocuments.length;
  const hasSelection = selectedCount > 0;
  const visibleSelectedCount = visibleDocuments.reduce(
    (total, doc) => total + (selectedIds.has(doc.id) ? 1 : 0),
    0,
  );
  const allVisibleSelected = visibleDocuments.length > 0 && visibleSelectedCount === visibleDocuments.length;
  const someVisibleSelected = visibleSelectedCount > 0 && !allVisibleSelected;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected, allVisibleSelected, visibleDocuments.length]);

  const toggleDocumentSelection = (documentId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else {
        next.add(documentId);
      }
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        visibleDocuments.forEach(doc => next.delete(doc.id));
      } else {
        visibleDocuments.forEach(doc => next.add(doc.id));
      }
      return next;
    });
  };

  const handleRowClick = (doc: DocumentRecord) => {
    const normalizedStatus = normalizeStatus(doc.status);
    if (normalizedStatus === "completed" || normalizedStatus === "signed") {
      navigate(`/documentos/${doc.id}`);
      return;
    }
    navigate(`/documentos/${doc.id}/gerenciar`);
  };

  const handleActionSelection = (doc: DocumentRecord, value: string) => {
    if (!value) return;
    if (value === "edit") {
      navigate(`/documentos/${doc.id}/gerenciar`);
      return;
    }
    if (value === "resend" || value === "archive" || value === "unarchive" || value === "delete") {
      setPendingAction({ type: value, document: doc } as PendingAction);
    }
  };

  const runBulkAction = useCallback(
    async (
      targets: DocumentRecord[],
      action: (documentId: string) => Promise<unknown>,
      successMessage: string,
    ) => {
      if (!targets.length) {
        return;
      }
      setActionLoading(true);
      try {
        for (const doc of targets) {
          await action(doc.id);
        }
        setSelectedIds(new Set());
        toast.success(successMessage);
        await loadDocuments();
      } catch (error) {
        console.error(error);
        toast.error("Não foi possível concluir a ação para todos os documentos selecionados.");
      } finally {
        setActionLoading(false);
      }
    },
    [loadDocuments],
  );

  const handleBulkArchive = async () => {
    const targets = selectedDocuments.filter(doc => normalizeStatus(doc.status) !== "archived");
    if (!targets.length) {
      toast.error("Selecione documentos ativos para arquivar.");
      return;
    }
    if (
      !window.confirm(
        `Arquivar ${targets.length} documento${targets.length > 1 ? "s" : ""}? Eles continuarão disponíveis na aba Arquivados.`,
      )
    ) {
      return;
    }
    await runBulkAction(targets, documentId => archiveDocument(documentId, true), "Documentos arquivados.");
  };

  const handleBulkUnarchive = async () => {
    const targets = selectedDocuments.filter(doc => normalizeStatus(doc.status) === "archived");
    if (!targets.length) {
      toast.error("Selecione documentos arquivados para desarquivar.");
      return;
    }
    if (
      !window.confirm(
        `Desarquivar ${targets.length} documento${targets.length > 1 ? "s" : ""}? Eles voltarão para a lista ativa.`,
      )
    ) {
      return;
    }
    await runBulkAction(targets, documentId => archiveDocument(documentId, false), "Documentos desarquivados.");
  };

  const handleBulkDelete = async () => {
    if (!hasSelection) {
      toast.error("Selecione documentos para excluir.");
      return;
    }
    if (
      !window.confirm(
        `Excluir ${selectedCount} documento${selectedCount > 1 ? "s" : ""}? Esta ação removerá permanentemente todas as versões e registros relacionados.`,
      )
    ) {
      return;
    }
    await runBulkAction(selectedDocuments, documentId => deleteDocument(documentId), "Documentos excluídos.");
  };

  const handleCloseActionModal = () => {
    if (actionLoading) return;
    setPendingAction(null);
  };

  const handleConfirmAction = async () => {
    if (!pendingAction) return;
    setActionLoading(true);
    const { type, document } = pendingAction;
    try {
      switch (type) {
        case "resend": {
          const response = await resendDocumentNotifications(document.id);
          toast.success(
            response.notified > 0
              ? `Notificações reenviadas para ${response.notified} destinatário(s).`
              : "Nenhum destinatário pendente para reenviar.",
          );
          break;
        }
        case "archive": {
          const updated = await archiveDocument(document.id, true);
          setDocuments(prev => prev.map(item => (item.id === updated.id ? updated : item)));
          toast.success("Documento arquivado.");
          break;
        }
        case "unarchive": {
          const updated = await archiveDocument(document.id, false);
          setDocuments(prev => prev.map(item => (item.id === updated.id ? updated : item)));
          toast.success("Documento restaurado.");
          break;
        }
        case "delete": {
          await deleteDocument(document.id);
          setDocuments(prev => prev.filter(item => item.id !== document.id));
          toast.success("Documento excluído.");
          break;
        }
        default:
          break;
      }
      setPendingAction(null);
    } catch (error) {
      console.error(error);
      let message = "Falha ao executar a ação.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      toast.error(message);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Documentos</h1>
          <p className="text-sm text-slate-500">Acompanhe todos os envios em um só lugar.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadDocuments()}>
            Atualizar
          </button>
          {onCreateNew && (
            <button type="button" className="btn btn-primary btn-sm" onClick={onCreateNew}>
              Novo documento
            </button>
          )}
        </div>
      </div>

      {documentLimitReached && (
        <div className="rounded-md border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          Limite de documentos assinados do plano foi atingido ({documentsUsed}/{documentsQuota} utilizados). Atualize o
          plano ou contrate um pacote adicional para enviar novos documentos.
        </div>
      )}

      {!areaReady && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Selecione uma área para visualizar os documentos disponíveis.
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-2">
            {statusTabs.map(tab => (
              <button
                key={tab.value}
                type="button"
                className={`rounded-full px-3 py-1 text-sm font-medium transition ${
                  statusFilter === tab.value ? "bg-indigo-600 text-white" : "border border-slate-200 text-slate-600"
                }`}
                onClick={() => setStatusFilter(tab.value)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <span>Filtro:</span>
            <select
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
              value={documentFilter}
              onChange={event => setDocumentFilter(event.target.value as DocumentListFilter)}
            >
              <option value="all">Todos</option>
              <option value="my_pending">Pendentes (meus)</option>
              <option value="area_pending">Pendentes na área</option>
            </select>
          </div>
        </div>

        {hasSelection && (
          <div className="mt-4 flex flex-col gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 md:flex-row md:items-center md:justify-between">
            <div className="font-medium">
              {selectedCount} documento{selectedCount > 1 ? "s" : ""} selecionado{selectedCount > 1 ? "s" : ""}.
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleBulkArchive}
                disabled={actionLoading}
              >
                Arquivar
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleBulkUnarchive}
                disabled={actionLoading}
              >
                Desarquivar
              </button>
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={handleBulkDelete}
                disabled={actionLoading}
              >
                Excluir
              </button>
            </div>
          </div>
        )}

        {loadingDocs ? (
          <div className="py-10 text-center text-sm text-slate-500">Carregando documentos...</div>
        ) : visibleDocuments.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-500">
            {documentFilter === "all" && statusFilter === "all"
              ? areaReady
                ? "Nenhum documento cadastrado nesta área."
                : "Conecte uma área para visualizar os documentos."
              : "Nenhum documento encontrado para os filtros selecionados."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-12 px-4 py-3">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      checked={visibleDocuments.length > 0 && allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                  <th className="px-4 py-3">Documento</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Atualizado</th>
                  <th className="px-4 py-3">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleDocuments.map(doc => {
                  const normalizedStatus = normalizeStatus(doc.status);
                  const isArchived = normalizedStatus === "archived";
                  const canResend = normalizedStatus !== "draft" && !isArchived;
                  return (
                    <tr
                      key={doc.id}
                      className="hover:bg-slate-50/80 cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
                      role="button"
                      tabIndex={0}
                      onClick={() => handleRowClick(doc)}
                      onKeyDown={event => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          handleRowClick(doc);
                        }
                      }}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          checked={selectedIds.has(doc.id)}
                          onClick={event => event.stopPropagation()}
                          onChange={event => {
                            event.stopPropagation();
                            toggleDocumentSelection(doc.id);
                          }}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-800">{doc.name}</div>
                        <div className="text-xs text-slate-500">{doc.id}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${statusBadgeClasses(doc.status)}`}>
                          {statusLabel(doc.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{formatDateTime(doc.updated_at ?? doc.created_at)}</td>
                      <td className="px-4 py-3">
                        <select
                          defaultValue=""
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm text-slate-700"
                          onClick={event => event.stopPropagation()}
                          onKeyDown={event => event.stopPropagation()}
                          onChange={event => {
                            handleActionSelection(doc, event.target.value);
                            event.currentTarget.value = "";
                          }}
                        >
                          <option value="" disabled>
                            Ações
                          </option>
                          <option value="edit">Editar participantes</option>
                          {canResend && <option value="resend">Reenviar notificações</option>}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {pendingAction && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-slate-800">{getActionTitle(pendingAction.type)}</h3>
              <p className="text-sm text-slate-600">
                {getActionDescription(pendingAction.type, pendingAction.document.name)}
              </p>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleCloseActionModal}
                disabled={actionLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleConfirmAction}
                disabled={actionLoading}
              >
                {actionLoading ? "Processando..." : getConfirmLabel(pendingAction.type)}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
