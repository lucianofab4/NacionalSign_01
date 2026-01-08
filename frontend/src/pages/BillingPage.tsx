import { useEffect, useMemo, useState } from 'react';
import {
  fetchPlans,
  fetchSubscription,
  fetchInvoices,
  createOrUpdateSubscription,
  seedDefaultPlans,
  fetchUsage,
  retryInvoice,
  type Plan,
  type Subscription,
  type Invoice,
  type Usage,
} from '../api';
// Valor máximo de tentativas (deve ser mantido em sincronia com backend)
const BILLING_MAX_RETRIES = 3;

const currency = (cents: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format((cents || 0) / 100);

interface BillingPageProps {
  canManagePlans?: boolean;
}

export default function BillingPage({ canManagePlans = false }: BillingPageProps) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [planChoice, setPlanChoice] = useState<string>('');
  const [payToken, setPayToken] = useState<string>('tok_demo');
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const invoicePromise = canManagePlans ? fetchInvoices() : Promise.resolve<Invoice[]>([]);
        const [p, s, u, i] = await Promise.all([
          fetchPlans(),
          fetchSubscription(),
          fetchUsage(),
          invoicePromise,
        ]);
        setPlans(p);
        setSubscription(s);
        setUsage(u);
        setInvoices(i);
        if (!planChoice && p.length) setPlanChoice(p[0].id);
      } catch (e) {
        setError('Não foi possível carregar informações de cobrança.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [canManagePlans]);

  const reloadInvoices = async () => {
    try {
      const list = await fetchInvoices();
      setInvoices(list);
    } catch (_) {}
  };

  const currentPlan = useMemo(() => plans.find(p => p.id === subscription?.plan_id) || null, [plans, subscription]);
  const resolvedPlanName = currentPlan?.name ?? (subscription ? 'Plano contratado' : 'Sem plano definido');
  const resolvedDocQuota = currentPlan?.document_quota ?? usage?.documents_quota ?? null;

  const handleUpgrade = async () => {
    try {
      setBusy(true);
      const sub = await createOrUpdateSubscription(planChoice, payToken);
      setSubscription(sub);
    } catch (e) {
      setError('Não foi possível atualizar a assinatura.');
    } finally {
      setBusy(false);
    }
  };

  const handleSeedPlans = async () => {
    try {
      setBusy(true);
      const seeded = await seedDefaultPlans();
      setPlans(seeded);
      if (!planChoice && seeded.length) setPlanChoice(seeded[0].id);
      setError(null);
    } catch (e: any) {
      if (e?.response?.status === 403 || e?.response?.status === 401) {
        setError('Você não tem permissão para criar planos padrão.');
      } else {
        setError('Falha ao criar planos padrão.');
      }
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async (invoiceId: string) => {
    try {
      setBusy(true);
      await retryInvoice(invoiceId);
      await reloadInvoices();
      setError(null);
    } catch (e: any) {
      setError('Não foi possível reprocessar a fatura.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="flex items-center gap-2 text-slate-600"><span className="animate-spin h-5 w-5 border-2 border-slate-300 border-t-emerald-400 rounded-full inline-block"></span> Carregando...</div>;
  if (error) return <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2"><span className="material-icons text-xl">error_outline</span>{error}</div>;

  return (
    <div className="space-y-6">
      {/* Banner de tentativas máximas */}
      {canManagePlans && invoices.some(inv => (inv.retry_count ?? 0) >= BILLING_MAX_RETRIES && inv.status !== 'paid') && (
        <div className="bg-amber-100 border border-amber-300 text-amber-900 rounded-md px-4 py-3 mb-2 flex items-center gap-2">
          <span className="material-icons text-amber-700">warning_amber</span>
          <span><strong>Atenção:</strong> Algumas faturas atingiram o limite máximo de tentativas ({BILLING_MAX_RETRIES}) e foram marcadas como <span className="font-semibold">falhadas</span>. Entre em contato com o suporte ou gere uma nova fatura.</span>
        </div>
      )}
      {/* Banner de tentativas próximas do limite */}
      {canManagePlans && invoices.some(inv => (inv.retry_count ?? 0) === BILLING_MAX_RETRIES - 1 && inv.status !== 'paid') && (
        <div className="bg-orange-50 border border-orange-200 text-orange-800 rounded-md px-4 py-3 mb-2 flex items-center gap-2">
          <span className="material-icons text-orange-600">report_problem</span>
          <span><strong>Alerta:</strong> Existem faturas com apenas mais uma tentativa restante antes de serem marcadas como falhadas.</span>
        </div>
      )}
      {usage && (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200">
          <h2 className="text-lg font-semibold mb-2">Consumo do plano</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div>
              <div className="text-sm text-slate-700 mb-1">Documentos</div>
              <div className="w-full bg-slate-100 rounded-md h-3 overflow-hidden">
                <div
                  className={`h-3 rounded-md ${((usage.documents_percent ?? (usage.documents_quota ? Math.round((usage.documents_used / (usage.documents_quota || 1)) * 100) : 0)) >= 90) ? 'bg-amber-500' : 'bg-emerald-500'}`}
                  style={{
                    width: `${
                      usage.documents_percent ??
                      (usage.documents_quota
                        ? Math.round((usage.documents_used / (usage.documents_quota || 1)) * 100)
                        : 0)
                    }%`,
                  }}
                />
              </div>
              <div className="text-xs text-slate-600 mt-1">
                {usage.documents_used}/{usage.documents_quota ?? 'sem limite'} neste periodo
              </div>
            </div>
            <div>
              <div className="text-sm text-slate-700 mb-1">Usuários</div>
              <div className="text-2xl font-semibold text-slate-900">Ilimitados</div>
              <div className="text-xs text-slate-600 mt-1">
                Contas ativas: {usage.users_used}
              </div>
            </div>
            <div>
              <div className="text-sm text-slate-700 mb-1">Documentos assinados</div>
              <div className="text-2xl font-semibold text-slate-900">{usage.documents_signed ?? 0}</div>
              <div className="text-xs text-slate-600 mt-1">Concluidos neste periodo</div>
            </div>
          </div>
        </div>
      )}
      {canManagePlans ? (
        <>
          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200">
            <h2 className="text-lg font-semibold mb-2">Seu plano</h2>
            {subscription ? (
              <div className="text-sm text-slate-700">
                <div><span className="font-medium">Plano:</span> {currentPlan ? currentPlan.name : subscription.plan_id}</div>
                <div><span className="font-medium">Status:</span> {subscription.status}</div>
                <div><span className="font-medium">Válido até:</span> {subscription.valid_until ? new Date(subscription.valid_until).toLocaleDateString('pt-BR') : '—'}</div>
              </div>
            ) : (
              <div className="text-sm text-slate-700">Nenhuma assinatura ativa.</div>
            )}
          </div>

          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200">
            <h2 className="text-lg font-semibold mb-2">Planos disponíveis</h2>
            {plans.length === 0 && (
              <div className="mb-3 text-sm text-slate-600">Nenhum plano encontrado. Se estiver em ambiente de desenvolvimento, você pode criar os planos padrão:</div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {plans.map(plan => (
                <div key={plan.id} className={`border rounded-lg p-4 ${subscription?.plan_id === plan.id ? 'border-emerald-400' : 'border-slate-200'}`}>
                  <div className="text-slate-900 font-semibold">{plan.name}</div>
                  <div className="text-slate-600 text-sm">{plan.document_quota} documentos • Usuários ilimitados</div>
                  <div className="text-slate-900 text-lg mt-2">{currency(plan.price_monthly)}/mês</div>
                  <div className="text-slate-500 text-sm">{currency(plan.price_yearly)}/ano</div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-2 items-end">
              {plans.length === 0 && (
                <button className="btn btn-secondary" onClick={handleSeedPlans} disabled={busy}>Criar planos padrão</button>
              )}
              <div className="flex-1">
                <label className="block text-sm font-medium text-slate-600">Selecionar plano</label>
                <select className="w-full border border-slate-300 rounded-md px-3 py-2" value={planChoice} onChange={e => setPlanChoice(e.target.value)}>
                  {plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div className="flex-1">
                <label className="block text-sm font-medium text-slate-600">Token de pagamento (demo)</label>
                <input className="w-full border border-slate-300 rounded-md px-3 py-2" value={payToken} onChange={e => setPayToken(e.target.value)} />
              </div>
              <button className="btn btn-secondary" onClick={handleUpgrade} disabled={busy}>Atualizar plano</button>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200">
            <h2 className="text-lg font-semibold mb-2">Faturas</h2>
            {invoices.length === 0 ? (
              <div className="text-sm text-slate-600">Nenhuma fatura ainda.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-600">
                      <th className="py-2 pr-4">Data</th>
                      <th className="py-2 pr-4">Valor</th>
                      <th className="py-2 pr-4">Status <span className="cursor-help" title="Status visual: verde=paga, vermelho=falhada, amarelo=pending">🛈</span></th>
                      <th className="py-2 pr-4">Gateway</th>
                      <th className="py-2 pr-4">Ref.</th>
                      <th className="py-2 pr-4">Tax ID</th>
                      <th className="py-2 pr-4">Recibo</th>
                      <th className="py-2 pr-4">Nota Fiscal</th>
                      <th className="py-2 pr-4">Tentativas</th>
                      <th className="py-2 pr-4" title="Backoff: 1ª=15min, 2ª=1h, 3ª=6h, 4+=24h">Próx. tentativa <span className="cursor-help" title="Após cada tentativa, o sistema aguarda: 1ª=15min, 2ª=1h, 3ª=6h, 4+=24h antes de permitir nova reprocessamento.">🛈</span></th>
                      <th className="py-2 pr-4"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map(inv => {
                      let statusColor = '';
                      if (inv.status === 'paid') statusColor = 'bg-emerald-50 text-emerald-700';
                      else if (inv.status === 'failed') statusColor = 'bg-red-50 text-red-700';
                      else statusColor = 'bg-amber-50 text-amber-700';
                      return (
                        <tr key={inv.id} className={`border-t ${statusColor}`} title={inv.status === 'failed' ? 'Fatura falhada: limite de tentativas atingido.' : inv.status === 'pending' ? 'Fatura pendente: aguardando pagamento ou nova tentativa.' : 'Fatura paga.'}>
                          <td className="py-2 pr-4">{new Date(inv.due_date).toLocaleDateString('pt-BR')}</td>
                          <td className="py-2 pr-4">{currency(inv.amount_cents)}</td>
                          <td className="py-2 pr-4 flex items-center gap-1">
                            {inv.status === 'paid' && <span className="material-icons text-emerald-500" title="Fatura paga">check_circle</span>}
                            {inv.status === 'failed' && <span className="material-icons text-red-500" title="Fatura falhada">cancel</span>}
                            {inv.status === 'pending' && <span className="material-icons text-amber-500" title="Fatura pendente">hourglass_empty</span>}
                            <span>{inv.status}</span>
                          </td>
                          <td className="py-2 pr-4">{inv.gateway}</td>
                          <td className="py-2 pr-4">{inv.external_id}</td>
                          <td className="py-2 pr-4">{inv.tax_id ?? '—'}</td>
                          <td className="py-2 pr-4">{inv.receipt_url ? <a href={inv.receipt_url} target="_blank" rel="noopener noreferrer" className="text-emerald-700 underline">Recibo</a> : '—'}</td>
                          <td className="py-2 pr-4">{inv.fiscal_note_number ?? '—'}</td>
                          <td className="py-2 pr-4" title={`Tentativas: ${inv.retry_count ?? 0} de ${BILLING_MAX_RETRIES}`}>{inv.retry_count ?? 0}</td>
                          <td className="py-2 pr-4" title="Próxima tentativa automática de cobrança.">{inv.next_attempt_at ? new Date(inv.next_attempt_at).toLocaleString('pt-BR') : '—'}</td>
                          <td className="py-2 pr-4">
                            {inv.status !== 'paid' && inv.status !== 'failed' && (
                              <button className="btn btn-secondary btn-sm flex items-center gap-1" onClick={() => handleRetry(inv.id)} disabled={busy} title="Tentar nova cobrança">
                                {busy ? <span className="animate-spin h-4 w-4 border-2 border-slate-300 border-t-emerald-400 rounded-full inline-block"></span> : <span className="material-icons text-slate-500">refresh</span>}
                                Tentar novamente
                              </button>
                            )}
                            {inv.status === 'failed' && (
                              <button className="btn btn-primary btn-sm ml-2" title="Gerar nova fatura">
                                Gerar nova fatura
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200">
          <h2 className="text-lg font-semibold mb-2">Seu plano</h2>
          <div className="text-sm text-slate-700 space-y-1">
            <div><span className="font-medium">Plano:</span> {resolvedPlanName}</div>
            <div>
              <span className="font-medium">Limite de documentos:</span>{' '}
              {typeof resolvedDocQuota === 'number' ? `${resolvedDocQuota} por período` : 'Sem limite'}
            </div>
            <div>
              <span className="font-medium">Usuários:</span> Ilimitados
            </div>
            {subscription && (
              <div><span className="font-medium">Status:</span> {subscription.status}</div>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-4">Para alterar o plano ou revisar condições comerciais, fale com o time Comercial da NacionalSign.</p>
        </div>
      )}
    </div>
  );
}
