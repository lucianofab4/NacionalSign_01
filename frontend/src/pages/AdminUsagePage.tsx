import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  type AdminUsageResponse,
  fetchAdminUsageOverview,
  sendUsageAlertEmail,
  type UsageAlertResult,
} from '../api';

const toDateInputValue = (date: Date) => date.toISOString().slice(0, 10);
const buildIso = (value: string, endOfDay = false) =>
  value ? `${value}T${endOfDay ? '23:59:59' : '00:00:00'}` : undefined;

const limitLabel: Record<string, string> = {
  ok: 'Dentro do limite',
  near_limit: 'Atenção',
  exceeded: 'Sem limite',
  unlimited: 'Sem limite definido',
};

const AdminUsagePage = () => {
  const today = useMemo(() => new Date(), []);
  const firstDay = useMemo(() => {
    const base = new Date(today);
    base.setDate(1);
    return base;
  }, [today]);
  const [startDate, setStartDate] = useState(toDateInputValue(firstDay));
  const [endDate, setEndDate] = useState(toDateInputValue(today));
  const [search, setSearch] = useState('');
  const [data, setData] = useState<AdminUsageResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [includeEmpty, setIncludeEmpty] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const response = await fetchAdminUsageOverview({
        start_date: buildIso(startDate),
        end_date: buildIso(endDate, true),
        search: search || undefined,
        include_empty: includeEmpty,
      });
      setData(response);
    } catch (error) {
      console.error('Failed to load admin usage', error);
      toast.error('Nao foi possivel carregar o painel de clientes.');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeEmpty]);

  const handleSubmitFilters = (event: React.FormEvent) => {
    event.preventDefault();
    if (startDate && endDate && startDate > endDate) {
      toast.error('A data inicial deve ser anterior a data final.');
      return;
    }
    void loadData();
  };

  const handleSendAlerts = async () => {
    setSending(true);
    try {
      const payload = {
        start_date: buildIso(startDate),
        end_date: buildIso(endDate, true),
      };
      const response: UsageAlertResult = await sendUsageAlertEmail(payload);
      if (response.sent) {
        toast.success(`Resumo enviado (${response.alerts} clientes sinalizados).`);
      } else {
        toast('Nenhum cliente atingiu o limite no periodo.');
      }
    } catch (error) {
      console.error('Failed to send alerts', error);
      toast.error('Falha ao enviar o alerta por e-mail.');
    } finally {
      setSending(false);
    }
  };

  const rows = data?.items ?? [];
  const alerts = data?.alerts ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Painel do proprietário</h2>
          <p className="text-sm text-slate-500">
            Acompanhe os clientes que mais consomem documentos e dispare alertas preventivos.
          </p>
        </div>
        <form className="flex flex-wrap gap-3 text-sm text-slate-600" onSubmit={handleSubmitFilters}>
          <label className="flex flex-col">
            <span className="text-xs uppercase text-slate-500">Início</span>
            <input
              type="date"
              value={startDate}
              onChange={event => setStartDate(event.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="flex flex-col">
            <span className="text-xs uppercase text-slate-500">Fim</span>
            <input
              type="date"
              value={endDate}
              onChange={event => setEndDate(event.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="flex flex-col flex-1 min-w-[180px]">
            <span className="text-xs uppercase text-slate-500">Buscar cliente</span>
            <input
              type="text"
              placeholder="Nome, e-mail..."
              value={search}
              onChange={event => setSearch(event.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <div className="flex items-end gap-2 flex-wrap">
            <button type="submit" className="btn btn-primary btn-sm" disabled={loading}>
              {loading ? 'Atualizando...' : 'Atualizar'}
            </button>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={handleSendAlerts}
              disabled={sending || !alerts.length}
            >
              {sending ? 'Enviando...' : 'Enviar alerta por e-mail'}
            </button>
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={includeEmpty}
                onChange={event => setIncludeEmpty(event.target.checked)}
              />
              Mostrar clientes sem atividade
            </label>
          </div>
        </form>
        <div className="text-xs text-slate-500">
          {alerts.length > 0 ? (
            <span>{alerts.length} clientes no limite &middot; clique no botão para enviar o resumo.</span>
          ) : (
            <span>Nenhum cliente sinalizado no período selecionado.</span>
          )}
        </div>
      </header>

      <div className="overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Cliente</th>
              <th className="px-4 py-3">Plano</th>
              <th className="px-4 py-3">Docs usados</th>
              <th className="px-4 py-3">Assinados</th>
              <th className="px-4 py-3">Limite</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Mensagem</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                  Carregando informações...
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                  Nenhum cliente encontrado nesse período.
                </td>
              </tr>
            )}
            {!loading &&
              rows.map(row => (
                <tr key={row.tenant_id} className="border-t border-slate-100">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-slate-800">{row.tenant_name}</div>
                    <div className="text-xs text-slate-500">{row.tenant_slug}</div>
                  </td>
                  <td className="px-4 py-3">{row.plan_name ?? '—'}</td>
                  <td className="px-4 py-3">
                    {row.documents_used}/{row.documents_quota ?? '∞'}
                  </td>
                  <td className="px-4 py-3">{row.documents_signed ?? 0}</td>
                  <td className="px-4 py-3">
                    {row.documents_quota ?? 'Sem limite'}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                        row.limit_state === 'exceeded'
                          ? 'bg-rose-100 text-rose-700'
                          : row.limit_state === 'near_limit'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-emerald-100 text-emerald-700'
                      }`}
                    >
                      {limitLabel[row.limit_state] ?? row.limit_state}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{row.message ?? '—'}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default AdminUsagePage;
