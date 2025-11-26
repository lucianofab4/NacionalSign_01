import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';

import { fetchAreas, fetchMe, updateMySettings, type Area, type UserMe } from '../api';

interface FormState {
  full_name: string;
  phone_number: string;
  default_area_id: string | null;
  password: string;
  password_confirm: string;
  two_factor_enabled: boolean;
}

const buildFormState = (user: UserMe): FormState => ({
  full_name: user.full_name,
  phone_number: user.phone_number ?? '',
  default_area_id: user.default_area_id,
  password: '',
  password_confirm: '',
  two_factor_enabled: user.two_factor_enabled,
});

interface MySettingsPageProps {
  currentUser: UserMe | null;
  onUserUpdated?: (user: UserMe) => void;
}

export default function MySettingsPage({ currentUser, onUserUpdated }: MySettingsPageProps) {
  const [user, setUser] = useState<UserMe | null>(currentUser);
  const [areas, setAreas] = useState<Area[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [me, areasResponse] = await Promise.all([
        currentUser ? Promise.resolve(currentUser) : fetchMe(),
        fetchAreas(),
      ]);
      setUser(me);
      setAreas(areasResponse);
      setForm(buildFormState(me));
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível carregar suas configurações.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form) return;
    if (!form.full_name.trim()) {
      toast.error('Informe o seu nome completo.');
      return;
    }
    if (!form.phone_number.trim()) {
      toast.error('Informe um telefone para contato.');
      return;
    }
    if (form.password || form.password_confirm) {
      if (form.password !== form.password_confirm) {
        toast.error('As senhas não conferem.');
        return;
      }
      if (form.password.length < 8) {
        toast.error('A senha deve ter pelo menos 8 caracteres.');
        return;
      }
    }
    setSaving(true);
    try {
      const payload = {
        full_name: form.full_name.trim(),
        phone_number: form.phone_number.trim(),
        default_area_id: form.default_area_id ?? undefined,
        two_factor_enabled: form.two_factor_enabled,
        password: form.password || undefined,
      };
      const updated = await updateMySettings(payload);
      toast.success('Configurações atualizadas.');
      const normalized: UserMe = {
        id: updated.id,
        tenant_id: updated.tenant_id,
        default_area_id: updated.default_area_id,
        email: updated.email,
        cpf: updated.cpf,
        full_name: updated.full_name,
        phone_number: updated.phone_number ?? null,
        profile: updated.profile,
        is_active: updated.is_active,
        two_factor_enabled: updated.two_factor_enabled,
        last_login_at: updated.last_login_at ?? null,
      };
      setUser(normalized);
      setForm(buildFormState(normalized));
      onUserUpdated?.(normalized);
    } catch (error) {
      console.error(error);
      toast.error('Erro ao salvar suas configurações.');
    } finally {
      setSaving(false);
    }
  };

  const areaOptions = useMemo(
    () => areas.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR')),
    [areas],
  );

  if (loading || !form || !user) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
        <h1 className="text-xl font-semibold text-slate-700">Minhas configurações</h1>
        <p className="text-sm text-slate-500 mt-2">Carregando informações...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">Minhas configurações</h1>
          <p className="text-sm text-slate-500 mt-1">
            Ajuste suas preferências pessoais, atualize dados de contato e defina a área padrão para novos documentos.
          </p>
        </div>

        <form className="grid grid-cols-1 md:grid-cols-2 gap-4" onSubmit={handleSubmit}>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Nome completo
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.full_name}
              onChange={event => setForm(prev => (prev ? { ...prev, full_name: event.target.value } : prev))}
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            E-mail
            <input className="mt-1 border rounded px-3 py-2 bg-slate-100 text-slate-500" value={user.email} disabled />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            CPF
            <input className="mt-1 border rounded px-3 py-2 bg-slate-100 text-slate-500" value={user.cpf} disabled />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Telefone celular
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.phone_number}
              onChange={event => setForm(prev => (prev ? { ...prev, phone_number: event.target.value } : prev))}
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Área padrão
            <select
              className="mt-1 border rounded px-3 py-2"
              value={form.default_area_id ?? ''}
              onChange={event =>
                setForm(prev => (prev ? { ...prev, default_area_id: event.target.value || null } : prev))
              }
            >
              <option value="">Selecionar área</option>
              {areaOptions.map(area => (
                <option key={area.id} value={area.id}>
                  {area.name}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-3 mt-6">
            <input
              id="two-factor"
              type="checkbox"
              checked={form.two_factor_enabled}
              onChange={event => setForm(prev => (prev ? { ...prev, two_factor_enabled: event.target.checked } : prev))}
            />
            <label htmlFor="two-factor" className="text-sm font-medium text-slate-600">
              Habilitar autenticação em duas etapas
            </label>
          </div>

          <div className="md:col-span-2 border-t border-slate-200 pt-4">
            <h2 className="text-base font-semibold text-slate-700 mb-3">Alterar senha</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Nova senha
                <input
                  className="mt-1 border rounded px-3 py-2"
                  type="password"
                  value={form.password}
                  onChange={event => setForm(prev => (prev ? { ...prev, password: event.target.value } : prev))}
                  placeholder="Deixe em branco para manter a atual"
                />
              </label>
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Confirmar nova senha
                <input
                  className="mt-1 border rounded px-3 py-2"
                  type="password"
                  value={form.password_confirm}
                  onChange={event => setForm(prev => (prev ? { ...prev, password_confirm: event.target.value } : prev))}
                />
              </label>
            </div>
          </div>

          <div className="md:col-span-2 flex justify-end">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar alterações'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
