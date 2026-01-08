import type { ChangeEvent, FormEvent } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  fetchAreas,
  fetchDocumentReports,
  type Area,
  type DocumentReportFilters,
  type DocumentReportResponse,
  type DocumentReportRow,
} from '../api';

const statusLabels: Record<string, string> = {
  draft: 'Rascunho',
  in_review: 'Em revisão',
  in_progress: 'Em andamento',
  completed: 'Concluído',
  rejected: 'Recusado',
  archived: 'Arquivado',
};

const signatureLabels: Record<string, string> = {
  electronic: 'Eletrônica',
  digital: 'Digital (certificado)',
};

const representativeStatusLabels: Record<string, string> = {
  pending: 'Pendente',
  signed: 'Assinado',
  refused: 'Recusado',
  delegated: 'Delegado',
  expired: 'Expirado',
};

const getRepresentativeStatus = (party: DocumentReportRow['parties'][number]) => {
  if (party.signed_at) return 'Assinado';
  const normalized = (party.status || '').toLowerCase();
  return representativeStatusLabels[normalized] ?? party.status ?? 'Pendente';
};

const defaultFilters = {
  startDate: '',
  endDate: '',
  status: '',
  areaId: '',
  signatureMethod: '',
  search: '',
};

const formatDateTime = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });
};

const formatDate = (value?: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('pt-BR');
};

const toDateStart = (value?: string) => (value ? `${value}T00:00:00` : undefined);
const toDateEnd = (value?: string) => (value ? `${value}T23:59:59` : undefined);

const buildCsv = (items: DocumentReportRow[]) => {
  if (!items.length) return null;
  const headers = [
    'Documento',
    'Status',
    'Área',
    'Criado por',
    'Criado em',
    'Workflow iniciado',
    'Workflow concluído',
    'Total signatários',
    'Assinados',
    'Pendentes',
    'Representante',
    'Papel',
    'Empresa',
    'Método configurado',
    'Assinou via',
    'Status representante',
    'Assinado em',
  ];

  const rows: string[][] = [];
  items.forEach(doc => {
    if (!doc.parties.length) {
      rows.push([
        doc.name,
        statusLabels[doc.status] ?? doc.status,
        doc.area_name,
        doc.created_by_name ?? '—',
        formatDateTime(doc.created_at),
        formatDateTime(doc.workflow_started_at),
        formatDateTime(doc.workflow_completed_at),
        String(doc.total_parties),
        String(doc.signed_parties),
        String(doc.pending_parties),
        '',
        '',
        '',
        '',
        '',
        '',
        '',
      ]);
      return;
    }

    doc.parties.forEach(party => {
      const configuredMethod = party.signature_method ? signatureLabels[party.signature_method.toLowerCase()] ?? party.signature_method : '—';
      const executedMethod = party.signature_type ? signatureLabels[party.signature_type.toLowerCase()] ?? party.signature_type : configuredMethod;
      rows.push([
        doc.name,
        statusLabels[doc.status] ?? doc.status,
        doc.area_name,
        doc.created_by_name ?? '—',
        formatDateTime(doc.created_at),
        formatDateTime(doc.workflow_started_at),
        formatDateTime(doc.workflow_completed_at),
        String(doc.total_parties),
        String(doc.signed_parties),
        String(doc.pending_parties),
        party.full_name,
        party.role,
        party.company_name ?? '—',
        configuredMethod,
        executedMethod,
        getRepresentativeStatus(party),
        formatDateTime(party.signed_at),
      ]);
    });
  });

  const csvContent = [headers, ...rows]
    .map(row => row.map(value => `"${String(value ?? '').replace(/"/g, '""')}"`).join(';'))
    .join('\n');

  return new Blob(['\ufeff', csvContent], { type: 'text/csv;charset=utf-8;' });
};

const ReportsPage = () => {
  const [areas, setAreas] = useState<Area[]>([]);
  const [filters, setFilters] = useState(defaultFilters);
  const [response, setResponse] = useState<DocumentReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAreas = useCallback(async () => {
    try {
      const result = await fetchAreas();
      setAreas(result);
    } catch (err) {
      console.error('Falha ao carregar áreas', err);
    }
  }, []);

  const loadReports = useCallback(
    async (override?: Partial<typeof filters>) => {
      setLoading(true);
      setError(null);
      try {
        const merged = { ...filters, ...(override ?? {}) };
        const payload: DocumentReportFilters = {
          startDate: merged.startDate ? toDateStart(merged.startDate) : undefined,
          endDate: merged.endDate ? toDateEnd(merged.endDate) : undefined,
          status: merged.status || undefined,
          areaId: merged.areaId || undefined,
          signatureMethod: merged.signatureMethod || undefined,
          search: merged.search || undefined,
          limit: 200,
          offset: 0,
        };
        const data = await fetchDocumentReports(payload);
        setResponse(data);
      } catch (err) {
        console.error(err);
        setError('Não foi possível carregar o relatório.');
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    loadAreas();
    loadReports();
  }, []);

  const handleInputChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = event.target;
    setFilters(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    loadReports();
  };

  const handleReset = () => {
    setFilters(defaultFilters);
    loadReports(defaultFilters);
  };

  const handleExport = () => {
    if (!response?.items.length) return;
    const blob = buildCsv(response.items);
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `relatorio-documentos-${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const statusCards = useMemo(() => {
    if (!response) return [];
    return Object.entries(response.status_summary || {}).map(([status, count]) => ({
      status,
      count,
      label: statusLabels[status] ?? status,
    }));
  }, [response]);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <form onSubmit={handleSubmit} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <div>
            <label className="text-sm font-medium text-slate-600">Período inicial</label>
            <input
              type="date"
              name="startDate"
              value={filters.startDate}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-600">Período final</label>
            <input
              type="date"
              name="endDate"
              value={filters.endDate}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-600">Status</label>
            <select
              name="status"
              value={filters.status}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            >
              <option value="">Todos</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-600">Área</label>
            <select
              name="areaId"
              value={filters.areaId}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            >
              <option value="">Todas</option>
              {areas.map(area => (
                <option key={area.id} value={area.id}>
                  {area.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-600">Método de assinatura</label>
            <select
              name="signatureMethod"
              value={filters.signatureMethod}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            >
              <option value="">Todos</option>
              <option value="electronic">Eletrônica</option>
              <option value="digital">Digital (certificado)</option>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-600">Busca por documento</label>
            <input
              type="text"
              name="search"
              placeholder="Contrato, proposta, ..."
              value={filters.search}
              onChange={handleInputChange}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </div>
          <div className="col-span-full flex flex-wrap gap-2 pt-2">
            <button type="submit" className="btn btn-primary btn-sm">
              Aplicar filtros
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={handleReset}>
              Limpar
            </button>
          </div>
        </form>
      </div>

      {statusCards.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {statusCards.map(card => (
            <div key={card.status} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 shadow-inner">
              <div className="text-xs font-medium uppercase text-slate-500">{card.label}</div>
              <div className="text-2xl font-semibold text-slate-900">{card.count}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-slate-600">
          {response?.items.length ? `Exibindo ${response.items.length} de ${response.total} documentos` : 'Nenhum documento encontrado'}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => loadReports()}
            disabled={loading}
          >
            Atualizar
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleExport}
            disabled={!response?.items.length}
          >
            Exportar CSV
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {loading && <div className="text-sm text-slate-500">Carregando relatórios...</div>}

      <div className="space-y-4">
        {response?.items.map(doc => (
          <div key={doc.document_id} className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap justify-between gap-3 border-b border-slate-100 px-4 py-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">{doc.name}</h3>
                <p className="text-sm text-slate-500">
                  Área {doc.area_name} • Criado por {doc.created_by_name ?? '—'} em {formatDateTime(doc.created_at)}
                </p>
                {doc.workflow_started_at && (
                  <p className="text-xs text-slate-400">
                    Enviado para assinatura em {formatDateTime(doc.workflow_started_at)}{' '}
                    {doc.workflow_completed_at && <>• Finalizado em {formatDateTime(doc.workflow_completed_at)}</>}
                  </p>
                )}
              </div>
              <div className="text-right">
                <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
                  {statusLabels[doc.status] ?? doc.status}
                </span>
                <p className="text-xs text-slate-500">
                  {doc.signed_parties}/{doc.total_parties} assinantes concluídos
                </p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-100 text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left">Representante</th>
                    <th className="px-4 py-3 text-left">Papel</th>
                    <th className="px-4 py-3 text-left">Empresa</th>
                    <th className="px-4 py-3 text-left">Método configurado</th>
                    <th className="px-4 py-3 text-left">Assinou via</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">Assinado em</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {doc.parties.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-3 text-center text-slate-500">
                        Nenhum participante cadastrado.
                      </td>
                    </tr>
                  )}
                  {doc.parties.map(party => {
                    const configuredMethod =
                      party.signature_method && signatureLabels[party.signature_method.toLowerCase()]
                        ? signatureLabels[party.signature_method.toLowerCase()]
                        : party.signature_method ?? '—';
                    const executedMethod =
                      party.signature_type && signatureLabels[party.signature_type.toLowerCase()]
                        ? signatureLabels[party.signature_type.toLowerCase()]
                        : configuredMethod;
                    return (
                      <tr key={party.party_id}>
                        <td className="px-4 py-3 font-medium text-slate-800">{party.full_name}</td>
                        <td className="px-4 py-3 text-slate-600">{party.role}</td>
                        <td className="px-4 py-3 text-slate-600">{party.company_name ?? '—'}</td>
                        <td className="px-4 py-3 text-slate-600">{configuredMethod}</td>
                        <td className="px-4 py-3 text-slate-600">{executedMethod}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
                              party.signed_at ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                            }`}
                          >
                            {party.signed_at ? 'Assinado' : 'Pendente'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{party.signed_at ? formatDateTime(party.signed_at) : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ReportsPage;
