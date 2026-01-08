import { FormEvent, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';

import {
  fetchCustomers,
  createCustomer,
  updateCustomer,
  deleteCustomer,
  generateCustomerActivationLink,
  grantCustomerDocuments,
  renewCustomerPlan,
  fetchPlans,
  type CustomerSummary,
  type CustomerCreatePayload,
  type CustomerUpdatePayload,
  type CustomerActivationLink,
  type Plan,
} from '../api';

const defaultForm = (): CustomerCreatePayload => ({
  corporate_name: '',
  trade_name: '',
  cnpj: '',
  responsible_name: '',
  responsible_email: '',
  responsible_phone: '',
  plan_id: '',
  document_quota: undefined,
  is_active: true,
});

const formatCnpj = (value: string) => {
  const digits = value.replace(/\D/g, '').slice(0, 14);
  return digits
    .replace(/^(\d{2})(\d)/, '$1.$2')
    .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2')
    .replace(/(\d{4})(\d)/, '$1-$2');
};

const formatPhone = (value: string) => {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  if (digits.length <= 2) return digits;
  if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
  if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
  return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
};

const resolveQuota = (planId: string | null, plans: Plan[]): number | null => {
  if (!planId) return null;
  const plan = plans.find(item => item.id === planId);
  return plan ? plan.document_quota : null;
};

export default function CustomersPage() {
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<CustomerCreatePayload>(defaultForm());
  const [creating, setCreating] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerSummary | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [lastActivation, setLastActivation] = useState<CustomerActivationLink | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [grantingId, setGrantingId] = useState<string | null>(null);
  const [renewingId, setRenewingId] = useState<string | null>(null);

  const planOptions = useMemo(() => plans.filter(plan => plan.is_active), [plans]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [plansResponse, customersResponse] = await Promise.all([fetchPlans(), fetchCustomers()]);
      setPlans(plansResponse);
      setCustomers(customersResponse);
    } catch (error) {
      console.error(error);
      toast.error('Falha ao carregar clientes.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  const resetForm = () => {
    setForm(defaultForm());
    setSelectedCustomer(null);
  };

  const issueActivationLink = async (customerId: string, autoCopy = false) => {
    const link = await generateCustomerActivationLink(customerId);
    setLastActivation(link);
    let copied = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(link.activation_url);
        copied = true;
      } catch (error) {
        console.error(error);
      }
    }
    if (copied) {
      toast.success(autoCopy ? 'Link do cliente gerado e copiado.' : 'Link de ativação copiado.');
    } else {
      toast.success(autoCopy ? 'Link do cliente gerado.' : 'Link de ativação gerado.');
    }
    return link;
  };

  const handleCopyLastActivation = async () => {
    if (!lastActivation) return;
    try {
      await navigator.clipboard.writeText(lastActivation.activation_url);
      toast.success('Link copiado para a área de transferência.');
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível copiar o link.');
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const preparedPayload: CustomerCreatePayload = {
      ...form,
      cnpj: form.cnpj?.replace(/\D/g, '') ?? '',
      plan_id: form.plan_id ? form.plan_id : null,
      document_quota:
        form.plan_id && form.plan_id.length > 0
          ? resolveQuota(form.plan_id, plans) ?? form.document_quota ?? null
          : form.document_quota ?? null,
    };

    if (!preparedPayload.corporate_name.trim() || !preparedPayload.cnpj || preparedPayload.cnpj.length !== 14) {
      toast.error('Informe razão social e um CNPJ válido.');
      return;
    }
    if (!preparedPayload.responsible_name.trim()) {
      toast.error('Informe o responsável.');
      return;
    }

    try {
      setCreating(true);
      if (selectedCustomer) {
        const updatePayload: CustomerUpdatePayload = {
          corporate_name: preparedPayload.corporate_name,
          trade_name: preparedPayload.trade_name,
          cnpj: preparedPayload.cnpj,
          responsible_name: preparedPayload.responsible_name,
          responsible_email: preparedPayload.responsible_email,
          responsible_phone: preparedPayload.responsible_phone,
          plan_id: preparedPayload.plan_id,
          document_quota: preparedPayload.document_quota,
          is_active: preparedPayload.is_active,
        };
        const updated = await updateCustomer(selectedCustomer.id, updatePayload);
        setCustomers(prev => prev.map(item => (item.id === updated.id ? updated : item)));
        toast.success('Cliente atualizado.');
      } else {
        const created = await createCustomer(preparedPayload);
        setCustomers(prev => [created, ...prev]);
        toast.success('Cliente cadastrado.');
        try {
          await issueActivationLink(created.id, true);
        } catch (linkError) {
          console.error(linkError);
          toast.error('Falha ao gerar o link do cliente automaticamente.');
        }
      }
      resetForm();
    } catch (error: any) {
      console.error(error);
      const detail = error?.response?.data?.detail ?? 'Erro ao salvar cliente.';
      toast.error(detail);
    } finally {
      setCreating(false);
    }
  };

  const handleEdit = (customer: CustomerSummary) => {
    setSelectedCustomer(customer);
    setForm({
      corporate_name: customer.corporate_name,
      trade_name: customer.trade_name ?? '',
      cnpj: formatCnpj(customer.cnpj),
      responsible_name: customer.responsible_name,
      responsible_email: customer.responsible_email ?? '',
      responsible_phone: customer.responsible_phone ?? '',
      plan_id: customer.plan_id ?? '',
      document_quota: customer.document_quota ?? undefined,
      is_active: customer.is_active,
    });
  };

  const handleGenerateLink = async (customer: CustomerSummary) => {
    try {
      setGenerating(customer.id);
      await issueActivationLink(customer.id);
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível gerar o link de ativação.');
    } finally {
      setGenerating(null);
    }
  };

  const handleDelete = async (customer: CustomerSummary) => {
    const confirmed = window.confirm(
      `Excluir o cliente "${customer.corporate_name}"? Essa ação remove o cadastro e libera o tenant vinculado.`,
    );
    if (!confirmed) return;
    try {
      setDeletingId(customer.id);
      await deleteCustomer(customer.id);
      setCustomers(prev => prev.filter(item => item.id !== customer.id));
      if (selectedCustomer?.id === customer.id) resetForm();
      toast.success('Cliente excluído.');
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível excluir o cliente.');
    } finally {
      setDeletingId(null);
    }
  };

  const handleGrantDocuments = async (customer: CustomerSummary) => {
    const suggestion = customer.document_quota ? Math.max(Math.ceil(customer.document_quota * 0.2), 1) : 10;
    const input = window.prompt(
      `Quantos documentos adicionais deseja liberar para ${customer.corporate_name}?`,
      String(suggestion),
    );
    if (input === null) return;
    const amount = Number(input);
    if (!Number.isFinite(amount) || amount <= 0) {
      toast.error('Informe uma quantidade válida.');
      return;
    }
    try {
      setGrantingId(customer.id);
      const updated = await grantCustomerDocuments(customer.id, Math.floor(amount));
      setCustomers(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      if (selectedCustomer?.id === updated.id) {
        handleEdit(updated);
      }
      toast.success(`Liberados ${Math.floor(amount)} documentos extras.`);
    } catch (error: any) {
      console.error(error);
      const detail = error?.response?.data?.detail ?? 'Não foi possível liberar documentos extras.';
      toast.error(detail);
    } finally {
      setGrantingId(null);
    }
  };

  const handleRenewPlan = async (customer: CustomerSummary) => {
    if (!customer.plan_id) {
      toast.error('Cliente sem plano associado.');
      return;
    }
    const input = window.prompt(
      `Por quantos dias deseja renovar o plano de ${customer.corporate_name}?`,
      '30',
    );
    if (input === null) return;
    const days = Number(input);
    if (!Number.isFinite(days) || days <= 0) {
      toast.error('Informe um número de dias válido.');
      return;
    }
    try {
      setRenewingId(customer.id);
      const updated = await renewCustomerPlan(customer.id, Math.floor(days));
      setCustomers(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      if (selectedCustomer?.id === updated.id) {
        handleEdit(updated);
      }
      toast.success(`Plano renovado por ${Math.floor(days)} dias.`);
    } catch (error: any) {
      console.error(error);
      const detail = error?.response?.data?.detail ?? 'Não foi possível renovar o plano.';
      toast.error(detail);
    } finally {
      setRenewingId(null);
    }
  };
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadAll();
      toast.success('Lista atualizada.');
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Clientes</h1>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary btn-sm" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? 'Atualizando...' : 'Atualizar'}
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h2 className="text-lg font-semibold text-slate-700 mb-4">
          {selectedCustomer ? 'Editar cliente' : 'Cadastrar novo cliente'}
        </h2>
        <form className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" onSubmit={handleSubmit}>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Razão social
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.corporate_name}
              onChange={event => setForm(prev => ({ ...prev, corporate_name: event.target.value }))}
              required
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Nome fantasia
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.trade_name ?? ''}
              onChange={event => setForm(prev => ({ ...prev, trade_name: event.target.value }))}
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            CNPJ
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.cnpj}
              onChange={event => setForm(prev => ({ ...prev, cnpj: formatCnpj(event.target.value) }))}
              placeholder="00.000.000/0000-00"
              required
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Responsável
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.responsible_name}
              onChange={event => setForm(prev => ({ ...prev, responsible_name: event.target.value }))}
              required
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            E-mail do responsável
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.responsible_email ?? ''}
              onChange={event => setForm(prev => ({ ...prev, responsible_email: event.target.value }))}
              type="email"
              placeholder="responsavel@empresa.com"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Telefone
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.responsible_phone ?? ''}
              onChange={event => setForm(prev => ({ ...prev, responsible_phone: formatPhone(event.target.value) }))}
              placeholder="(00) 00000-0000"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Plano
            <select
              className="mt-1 border rounded px-3 py-2"
              value={form.plan_id ?? ''}
              onChange={event => {
                const value = event.target.value;
                setForm(prev => ({
                  ...prev,
                  plan_id: value,
                  document_quota: value ? resolveQuota(value, plans) ?? prev.document_quota ?? undefined : prev.document_quota,
                }));
              }}
            >
              <option value="">Sem plano</option>
              {planOptions.map(plan => (
                <option key={plan.id} value={plan.id}>
                  {plan.name} — {plan.document_quota} docs/mês
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Limite de documentos (caso sem plano)
            <input
              type="number"
              min={0}
              className="mt-1 border rounded px-3 py-2"
              value={form.document_quota ?? ''}
              onChange={event =>
                setForm(prev => ({
                  ...prev,
                  document_quota: event.target.value ? Number(event.target.value) : undefined,
                }))
              }
              disabled={Boolean(form.plan_id)}
              placeholder="Ex.: 100"
            />
          </label>
          <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
            <input
              type="checkbox"
              checked={form.is_active ?? true}
              onChange={event => setForm(prev => ({ ...prev, is_active: event.target.checked }))}
            />
            Cliente ativo
          </label>
          <div className="md:col-span-3 flex justify-end gap-2">
            {selectedCustomer && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={resetForm}>
                Cancelar edição
              </button>
            )}
            <button type="submit" className="btn btn-primary btn-sm" disabled={creating}>
              {creating ? 'Salvando...' : selectedCustomer ? 'Salvar alterações' : 'Cadastrar cliente'}
            </button>
          </div>
        </form>
      </div>

      {lastActivation && (
        <div className="bg-white rounded-xl shadow-sm border border-amber-200 p-4">
          <div className="text-sm text-slate-600">Link de acesso recente do cliente:</div>
          <div className="mt-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <a className="text-primary-600 underline break-all" href={lastActivation.activation_url} target="_blank" rel="noreferrer">
              {lastActivation.activation_url}
            </a>
            <button type="button" className="btn btn-secondary btn-xs self-start" onClick={handleCopyLastActivation}>
              Copiar link
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Clientes cadastrados</h2>
          {lastActivation && (
            <div className="text-xs text-slate-500">
              Último link gerado{' '}
              <a className="text-primary-600 underline" href={lastActivation.activation_url} target="_blank" rel="noreferrer">
                {lastActivation.activation_url}
              </a>
            </div>
          )}
        </div>
        {loading ? (
          <div className="px-6 py-6 text-sm text-slate-500">Carregando clientes...</div>
        ) : customers.length === 0 ? (
          <div className="px-6 py-6 text-sm text-slate-500">Nenhum cliente cadastrado até o momento.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 uppercase tracking-wide text-xs">
                <tr>
                  <th className="px-4 py-3 text-left">Empresa</th>
                  <th className="px-4 py-3 text-left">Responsável</th>
                  <th className="px-4 py-3 text-left">Plano / Limite</th>
                  <th className="px-4 py-3 text-left">Uso</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Ações</th>
                </tr>
              </thead>
              <tbody>
                {customers.map(customer => {
                  const planName = customer.plan_id ? plans.find(plan => plan.id === customer.plan_id)?.name ?? 'Plano removido' : 'Sem plano';
                  const quotaLabel =
                    customer.plan_id && customer.document_quota !== null
                      ? `${customer.document_quota} docs`
                      : customer.document_quota !== null
                        ? `${customer.document_quota} docs`
                      : '—';
                  return (
                    <tr key={customer.id} className="border-t border-slate-100">
                      <td className="px-4 py-3">
                        <div className="font-semibold text-slate-800">{customer.corporate_name}</div>
                        <div className="text-xs text-slate-500">
                          {customer.trade_name ? `${customer.trade_name} · ` : ''}
                          {formatCnpj(customer.cnpj)}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{customer.responsible_name}</div>
                        <div className="text-xs text-slate-500">
                          {customer.responsible_email ?? 'Sem e-mail'}
                          {customer.responsible_phone && ` · ${formatPhone(customer.responsible_phone)}`}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{planName}</div>
                        <div className="text-xs text-slate-500">{quotaLabel}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {customer.documents_used}
                        {customer.document_quota !== null ? ` / ${customer.document_quota}` : ''}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
                            customer.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-600'
                          }`}
                        >
                          {customer.is_active ? 'Ativo' : 'Inativo'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <button className="btn btn-ghost btn-xs" onClick={() => handleEdit(customer)}>
                            Editar
                          </button>
                          <button
                            className="btn btn-outline btn-xs"
                            onClick={() => handleGrantDocuments(customer)}
                            disabled={grantingId === customer.id}
                          >
                            {grantingId === customer.id ? 'Liberando...' : 'Liberar docs'}
                          </button>
                          <button
                            className="btn btn-outline btn-xs"
                            onClick={() => handleRenewPlan(customer)}
                            disabled={renewingId === customer.id || !customer.plan_id}
                          >
                            {renewingId === customer.id ? 'Renovando...' : 'Renovar plano'}
                          </button>
                          <button
                            className="btn btn-secondary btn-xs"
                            onClick={() => handleGenerateLink(customer)}
                            disabled={generating === customer.id}
                          >
                            {generating === customer.id ? 'Gerando...' : 'Gerar link'}
                          </button>
                          <button
                            className="btn btn-error btn-xs"
                            onClick={() => handleDelete(customer)}
                            disabled={deletingId === customer.id}
                          >
                            {deletingId === customer.id ? 'Excluindo...' : 'Excluir'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
