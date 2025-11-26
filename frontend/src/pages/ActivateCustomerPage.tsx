import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import {
  completeCustomerActivation,
  fetchCustomerActivationStatus,
  type CustomerActivationCompleteResponse,
  type CustomerActivationStatus,
} from '../api';

interface FormState {
  full_name: string;
  email: string;
  password: string;
  confirm_password: string;
  accept_terms: boolean;
}

const defaultForm = (): FormState => ({
  full_name: '',
  email: '',
  password: '',
  confirm_password: '',
  accept_terms: true,
});

export default function ActivateCustomerPage() {
  const params = useParams();
  const navigate = useNavigate();
  const token = params.token ?? '';

  const [status, setStatus] = useState<CustomerActivationStatus | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CustomerActivationCompleteResponse | null>(null);

  useEffect(() => {
    if (!token) {
      setError('Token não informado.');
      setLoading(false);
      return;
    }
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchCustomerActivationStatus(token);
        setStatus(data);
        setForm(prev => ({
          ...prev,
          full_name: data.responsible_name ?? prev.full_name,
          email: data.responsible_email ?? prev.email,
        }));
      } catch (err: any) {
        console.error(err);
        const detail = err?.response?.data?.detail ?? 'Link inválido ou expirado.';
        setError(detail);
      } finally {
        setLoading(false);
      }
    };
    load().catch(console.error);
  }, [token]);

  const handleInput = (key: keyof FormState, value: string | boolean) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token) {
      toast.error('Token inválido.');
      return;
    }
    if (!form.accept_terms) {
      toast.error('Você precisa aceitar os termos para continuar.');
      return;
    }
    if (!form.password || form.password.length < 8) {
      toast.error('Informe uma senha com pelo menos 8 caracteres.');
      return;
    }
    if (form.password !== form.confirm_password) {
      toast.error('As senhas não coincidem.');
      return;
    }
    setSubmitting(true);
    try {
      const response = await completeCustomerActivation(token, {
        admin_full_name: form.full_name || undefined,
        admin_email: form.email || undefined,
        password: form.password,
        confirm_password: form.confirm_password,
      });
      setResult(response);
      toast.success('Empresa ativada com sucesso!');
    } catch (err: any) {
      console.error(err);
      const detail = err?.response?.data?.detail ?? 'Falha ao concluir ativação.';
      toast.error(detail);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoToLogin = () => {
    if (result?.login_url) {
      window.location.href = result.login_url;
      return;
    }
    navigate('/');
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-xl border border-slate-200 p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold text-slate-900">Ativação do Cliente</h1>
          <p className="text-sm text-slate-500">Confirme seus dados e crie a senha para acessar o NacionalSign.</p>
        </div>

        {loading ? (
          <div className="text-center text-slate-500">Carregando informações...</div>
        ) : error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-600">
            {error}
          </div>
        ) : result ? (
          <div className="space-y-4 text-center">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-700">
              <p className="font-medium text-lg">Conta ativada com sucesso!</p>
              <p className="text-sm mt-1">Agora você pode acessar o sistema com o e-mail informado e a senha criada.</p>
            </div>
            <button className="btn btn-primary" onClick={handleGoToLogin}>
              Ir para o login
            </button>
          </div>
        ) : status?.activated ? (
          <div className="space-y-4 text-center">
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-700">
              <p className="font-medium text-lg">Este link já foi utilizado.</p>
              <p className="text-sm mt-1">Se precisar de um novo acesso, peça ao administrador para reenviar o link.</p>
            </div>
            <button className="btn btn-secondary" onClick={() => navigate('/')}>
              Voltar para o início
            </button>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Empresa
                <input className="mt-1 rounded border border-slate-300 px-3 py-2 bg-slate-100" value={status?.corporate_name ?? ''} disabled />
              </label>
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Responsável
                <input className="mt-1 rounded border border-slate-300 px-3 py-2 bg-slate-100" value={status?.responsible_name ?? ''} disabled />
              </label>
            </div>

            <label className="flex flex-col text-sm font-medium text-slate-600">
              Nome completo
              <input
                className="mt-1 rounded border border-slate-300 px-3 py-2"
                value={form.full_name}
                onChange={event => handleInput('full_name', event.target.value)}
                required
              />
            </label>

            <label className="flex flex-col text-sm font-medium text-slate-600">
              E-mail
              <input
                type="email"
                className="mt-1 rounded border border-slate-300 px-3 py-2"
                value={form.email}
                onChange={event => handleInput('email', event.target.value)}
                required
              />
            </label>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Senha
                <input
                  type="password"
                  className="mt-1 rounded border border-slate-300 px-3 py-2"
                  value={form.password}
                  onChange={event => handleInput('password', event.target.value)}
                  required
                />
              </label>
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Confirmar senha
                <input
                  type="password"
                  className="mt-1 rounded border border-slate-300 px-3 py-2"
                  value={form.confirm_password}
                  onChange={event => handleInput('confirm_password', event.target.value)}
                  required
                />
              </label>
            </div>

            <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={form.accept_terms}
                onChange={event => handleInput('accept_terms', event.target.checked)}
              />
              <span>
                Confirmo que estou autorizado a representar a empresa acima e concordo com os{' '}
                <a className="text-primary-600 underline" href="https://nacionalsign.com.br/termos" target="_blank" rel="noreferrer">
                  termos de uso
                </a>
                .
              </span>
            </label>

            <button className="btn btn-primary w-full" type="submit" disabled={submitting}>
              {submitting ? 'Ativando...' : 'Ativar acesso'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
