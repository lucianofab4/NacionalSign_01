import { useCallback, useEffect, useState } from 'react';
import { matchPath, useLocation, useNavigate } from 'react-router-dom';
import toast, { Toaster } from 'react-hot-toast';

import TemplatesPage from './pages/TemplatesPage';
import BillingPage from './pages/BillingPage';
import DocumentsPage, { DocumentListFilter } from './pages/DocumentsPage';
import DocumentCreatePage from './pages/DocumentCreatePage';
import DocumentManagerPage from './pages/DocumentManagerPage';
import CustomersPage from './pages/CustomersPage';
import UsersPage from './pages/UsersPage';
import SettingsPage from './pages/SettingsPage';
import PublicSignaturePage from './pages/PublicSignaturePage';
import ReportsPage from './pages/ReportsPage';

import LoginForm from './components/LoginForm';
import NotificationBell from './components/NotificationBell';
import loginBackground from './assets/imagem_login.png';
import {
  login,
  setAuthToken,
  fetchUsage,
  fetchMe,
  fetchDashboardMetrics,
  requestPasswordReset,
  updateUserPassword,
  TOKEN_STORAGE_KEY,
  type Usage,
  type UserMe,
} from './api';

type ViewKey =
  | 'dashboard'
  | 'settings'
  | 'users'
  | 'relationships'
  | 'templates'
  | 'reports'
  | 'finance'
  | 'documents'
  | 'customers';

type MetricKey = 'pending_for_user' | 'to_sign' | 'signed_in_area' | 'pending_in_area';

interface Metric {
  key: MetricKey;
  label: string;
  icon: string;
  value: number;
}

const metricOrder: MetricKey[] = ['pending_for_user', 'to_sign', 'signed_in_area', 'pending_in_area'];

const metricConfig: Record<MetricKey, { label: string; icon: string }> = {
  pending_for_user: { label: 'Pendentes (meus)', icon: '📄' },
  to_sign: { label: 'Para assinar', icon: '✍️' },
  signed_in_area: { label: 'Assinados na área', icon: '🏢' },
  pending_in_area: { label: 'Pendentes na área', icon: '🕓' },
};

const defaultMetrics: Metric[] = metricOrder.map(key => ({
  key,
  label: metricConfig[key].label,
  icon: metricConfig[key].icon,
  value: 0,
}));

const metricClickMap: Partial<Record<MetricKey, DocumentListFilter>> = {
  pending_for_user: 'my_pending',
  pending_in_area: 'area_pending',
};

const navItems: Array<{ key: ViewKey; label: string; icon: string }> = [
  { key: 'dashboard', label: 'Início', icon: '🏠' },
  { key: 'settings', label: 'Configurações', icon: '⚙️' },
  { key: 'users', label: 'Usuários', icon: '👤' },
  { key: 'relationships', label: 'Relacionamentos', icon: '🤝' },
  { key: 'templates', label: 'Templates', icon: '🧩' },
  { key: 'reports', label: 'Relatórios', icon: '📊' },
  { key: 'finance', label: 'Financeiro da Empresa', icon: '💰' },
];

const rawCustomerAdminEnv =
  ((import.meta as any)?.env?.VITE_CUSTOMER_ADMIN_EMAILS as string | undefined) ??
  'luciano.dias888@gmail.com';
const CUSTOMER_ADMIN_EMAILS = rawCustomerAdminEnv
  .split(',')
  .map(value => value.trim().toLowerCase())
  .filter(Boolean);

const profileLabels: Record<string, string> = {
  owner: 'Proprietário',
  admin: 'Administrador',
  area_manager: 'Gestor de área',
  user: 'Usuário',
  procurator: 'Procurador',
};

const MainCTA = ({ onClick }: { onClick: () => void }) => (
  <div className="flex justify-center py-12">
    <button
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 px-6 py-3 text-lg font-semibold text-white shadow-lg shadow-indigo-500/30 transition hover:from-indigo-500 hover:to-indigo-400 focus:outline-none"
    >
      📤 Enviar Documento para Assinatura
    </button>
  </div>
);

function App() {
  const [tenantId, setTenantId] = useState('');
  const [areaId, setAreaId] = useState<string | undefined>(undefined);
  const [token, setToken] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>(defaultMetrics);
  const [view, setView] = useState<ViewKey>('dashboard');
  const [me, setMe] = useState<UserMe | null>(null);
  const [documentsFocus, setDocumentsFocus] = useState<DocumentListFilter | null>(null);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ newPassword: '', confirmPassword: '' });
  const [passwordChanging, setPasswordChanging] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const navigate = useNavigate();
  const location = useLocation();
  const normalizedPathname = location.pathname.replace(/\/+$/, '') || '/';
  const isDocumentCreateRoute = normalizedPathname === '/documentos/novo';
  const manageMatch = matchPath('/documentos/:id/gerenciar', normalizedPathname);
  const managingDocumentId = manageMatch?.params?.id ?? null;

  const normalizedProfile = me?.profile ? me.profile.trim().toLowerCase() : null;
  const isOwner = normalizedProfile === 'owner';
  const profileLabel = normalizedProfile ? profileLabels[normalizedProfile] ?? normalizedProfile : null;
  const canManageCustomers =
    isOwner && CUSTOMER_ADMIN_EMAILS.includes((me?.email ?? '').trim().toLowerCase());

  useEffect(() => {
    const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (storedToken) {
      setToken(storedToken);
      setAuthToken(storedToken);
    }
  }, []);

  useEffect(() => {
    const loadUsage = async () => {
      if (!token || !me) {
        setUsage(null);
        return;
      }
      try {
        const data = await fetchUsage();
        setUsage(data);
      } catch {
        setUsage(null);
      }
    };
    void loadUsage();
  }, [token, me?.id]);

  useEffect(() => {
    const loadMe = async () => {
      if (!token) {
        setMe(null);
        return;
      }
      try {
        const info = await fetchMe();
        setMe(info);
        if (!tenantId && info.tenant_id) setTenantId(info.tenant_id);
        if (!areaId && info.default_area_id) setAreaId(info.default_area_id);
      } catch {
        setMe(null);
        setToken(null);
        setAuthToken(undefined);
        window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
    };
    void loadMe();
  }, [token]);

  useEffect(() => {
    const loadMetrics = async () => {
      if (!token || !me) {
        setMetrics(defaultMetrics);
        return;
      }
      try {
        const data = await fetchDashboardMetrics({ area_id: areaId ?? null });
        setMetrics(
          metricOrder.map(key => ({
            key,
            label: metricConfig[key].label,
            icon: metricConfig[key].icon,
            value: data[key] ?? 0,
          })),
        );
      } catch (error) {
        console.error('Failed to load dashboard metrics', error);
        setMetrics(defaultMetrics);
      }
    };
    void loadMetrics();
  }, [token, areaId, me?.id]);

  const handleLogin = async (email: string, password: string) => {
    try {
      setAuthLoading(true);
      setAuthError(null);
      const response = await login(email, password);
      const accessToken = response.access_token as string;
      setToken(accessToken);
      setAuthToken(accessToken);
      window.localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
      setMustChangePassword(Boolean(response.must_change_password));
      setPasswordForm({ newPassword: '', confirmPassword: '' });
      setPasswordError(null);
      try {
        const info = await fetchMe();
        setMe(info);
        setTenantId(info.tenant_id);
        if (info.default_area_id) setAreaId(info.default_area_id);
        setView('dashboard');
      } catch {
        // ignore
      }
    } catch (error) {
      console.error(error);
      setAuthError('Credenciais inválidas.');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    exitSpecialRoutes();
    setToken(null);
    setAuthToken(undefined);
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    setMe(null);
    setTenantId('');
    setAreaId(undefined);
    setDocumentsFocus(null);
    setView('dashboard');
    setMustChangePassword(false);
    setPasswordForm({ newPassword: '', confirmPassword: '' });
    setPasswordError(null);
  };

  const handleForgotPassword = async (email: string) => {
    try {
      await requestPasswordReset(email);
      toast.success('Se o e-mail existir, enviaremos uma senha temporária.');
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? 'Falha ao solicitar redefinição.';
      toast.error(detail);
      throw error;
    }
  };

  const handlePasswordChangeSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!passwordForm.newPassword.trim()) {
      setPasswordError('Informe a nova senha.');
      return;
    }
    if (passwordForm.newPassword.trim().length < 8) {
      setPasswordError('A senha deve ter pelo menos 8 caracteres.');
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setPasswordError('As senhas informadas não coincidem.');
      return;
    }
    setPasswordError(null);
    setPasswordChanging(true);
    try {
      await updateUserPassword({ new_password: passwordForm.newPassword.trim() });
      toast.success('Senha atualizada com sucesso.');
      setMustChangePassword(false);
      setPasswordForm({ newPassword: '', confirmPassword: '' });
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? 'Falha ao alterar a senha.';
      setPasswordError(detail);
    } finally {
      setPasswordChanging(false);
    }
  };

  const showSidebar = Boolean(token);
  const isManagingDocument = Boolean(managingDocumentId);
  const activeView = isDocumentCreateRoute || isManagingDocument ? 'documents' : view;
  const filteredNavItems = navItems.filter(item => item.key !== 'relationships' || canManageCustomers);
  const isCustomersView = activeView === 'customers' || activeView === 'relationships';

  const exitSpecialRoutes = () => {
    if (isDocumentCreateRoute || isManagingDocument) {
      navigate('/', { replace: true });
    }
  };

  const changeView = (nextView: ViewKey) => {
    if ((nextView === 'customers' || nextView === 'relationships') && !canManageCustomers) {
      toast.error('Acesso restrito aos proprietários.');
      return;
    }
    exitSpecialRoutes();
    setView(nextView);
  };

  useEffect(() => {
    if (
      !canManageCustomers &&
      (view === 'customers' ||
        view === 'relationships')
    ) {
      setView('dashboard');
    }
  }, [canManageCustomers, view]);

  const navigateToTemplates = (targetAreaId?: string) => {
    if (targetAreaId) {
      setAreaId(targetAreaId);
    }
    changeView('templates');
  };

  const handleMetricCardClick = (filter: DocumentListFilter) => {
    setDocumentsFocus(filter);
    changeView('documents');
  };

  const handleGoHome = () => {
    setDocumentsFocus(null);
    setView('dashboard');
    navigate('/', { replace: true });
  };

  const openDocumentCreate = () => {
    setDocumentsFocus(null);
    setView('documents');
    navigate('/documentos/novo', { replace: isDocumentCreateRoute });
  };

  const handleDocumentCreateFinished = (documentId?: string) => {
    setDocumentsFocus(null);
    setView('documents');
    if (documentId) {
      navigate(`/documentos/${documentId}/gerenciar`, { replace: true });
      return;
    }
    changeView('documents');
  };

  const handleNotificationNavigate = useCallback(
    (documentId: string) => {
      setDocumentsFocus(null);
      setView('documents');
      navigate(`/documentos/${documentId}/gerenciar`);
    },
    [navigate],
  );

  const renderContent = () => {
    if (isDocumentCreateRoute) {
      return (
        <DocumentCreatePage
          tenantId={tenantId}
          areaId={areaId}
          onFinished={handleDocumentCreateFinished}
        />
      );
    }

    if (managingDocumentId) {
      return (
        <DocumentManagerPage
          tenantId={tenantId}
          areaId={areaId}
          usage={usage}
          currentUser={me}
          focusFilter={documentsFocus}
          onFocusConsumed={() => setDocumentsFocus(null)}
          onCreateNew={openDocumentCreate}
          initialDocumentId={managingDocumentId}
          standalone
        />
      );
    }

    switch (view) {
      case 'templates':
        return (
          <TemplatesPage
            tenantId={tenantId}
            onTenantChange={setTenantId}
            areaId={areaId}
            onAreaChange={setAreaId}
          />
        );
      case 'documents':
        return (
          <DocumentsPage
            tenantId={tenantId}
            areaId={areaId}
            usage={usage}
            currentUser={me}
            focusFilter={documentsFocus}
            onFocusConsumed={() => setDocumentsFocus(null)}
            onCreateNew={openDocumentCreate}
          />
        );
      case 'reports':
        return <ReportsPage />;
      case 'finance':
        return <BillingPage />;
      case 'users':
        return <UsersPage currentProfile={normalizedProfile ?? 'user'} currentAreaId={me?.default_area_id} />;
      case 'settings':
        return (
          <SettingsPage
            currentUser={me}
            tenantId={tenantId}
            onUserUpdated={updated => setMe(updated)}
            onOpenTemplates={navigateToTemplates}
          />
        );
      case 'relationships':
      case 'customers':
        if (!canManageCustomers) {
          return (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
              Acesso permitido apenas ao proprietário da conta.
            </div>
          );
        }
        return <CustomersPage />;
      case 'reports':
        return (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
            Relatórios em construção.
          </div>
        );
      case 'dashboard':
      default:
        return (
          <>
            <MainCTA onClick={openDocumentCreate} />
            <div className="rounded-xl border border-slate-200 bg-white p-6 text-slate-600 shadow-sm">
              <p>
                Bem-vindo! Utilize o menu lateral para acessar as funcionalidades principais.
                Você pode começar enviando um documento para assinatura ou configurando um novo fluxo em Templates.
              </p>
            </div>
          </>
        );
    }
  };

  const publicSignMatch = matchPath("/public/sign/:token", normalizedPathname);
  if (publicSignMatch) {
    return <PublicSignaturePage />;
  }

  if (!token) {
    return (
      <div
        className="min-h-screen w-full bg-slate-900/80 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: `url(${loginBackground})` }}
      >
        <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-900/70 to-slate-900/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/40 bg-gradient-to-br from-indigo-600/95 to-blue-500/95 p-6 shadow-2xl backdrop-blur">
            <LoginForm
              onSubmit={handleLogin}
              isLoading={authLoading}
              error={authError}
              onForgotPassword={handleForgotPassword}
            />
          </div>
        </div>
      </div>
    );
  }

  if (isManagingDocument) {
    const nameLabel = me?.full_name || me?.name || me?.email || 'Usuário';
    const profileDisplay = profileLabel ? `Perfil: ${profileLabel}` : null;
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <header className="border-b border-slate-200 bg-white px-4 py-4 shadow-sm sm:px-8">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1 text-sm text-slate-600">
              <p className="text-base font-semibold text-slate-900">{nameLabel}</p>
              {profileDisplay && <p>{profileDisplay}</p>}
              {me?.email && <p>Email: {me.email}</p>}
            </div>
            <div className="flex flex-col gap-3 text-sm font-semibold text-slate-600 lg:flex-row lg:items-center lg:gap-4">
              <nav className="flex flex-wrap gap-3 text-xs uppercase tracking-wide text-slate-500">
                <span>Documentos</span>
                <span>Templates</span>
                <span>Clientes</span>
                <span>Meu cadastro</span>
              </nav>
              <div className="flex items-center gap-2">
                <NotificationBell onSelectDocument={handleNotificationNavigate} />
                <button type="button" className="btn btn-primary btn-sm" onClick={handleGoHome}>
                  Home
                </button>
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-8">
          {renderContent()}
        </main>

        <Toaster position="top-right" toastOptions={{ duration: 4000 }} />
        {mustChangePassword && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 px-4">
            <form
              className="w-full max-w-md space-y-4 rounded-xl bg-white p-6 shadow-2xl"
              onSubmit={handlePasswordChangeSubmit}
            >
              <div>
                <h2 className="text-lg font-semibold text-slate-800">Defina uma nova senha</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Por segurança, você precisa alterar a senha temporária antes de continuar utilizando a plataforma.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600">Nova senha</label>
                <input
                  type="password"
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                  value={passwordForm.newPassword}
                  onChange={event => setPasswordForm(prev => ({ ...prev, newPassword: event.target.value }))}
                  placeholder="Informe a nova senha"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600">Confirmar nova senha</label>
                <input
                  type="password"
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                  value={passwordForm.confirmPassword}
                  onChange={event => setPasswordForm(prev => ({ ...prev, confirmPassword: event.target.value }))}
                  placeholder="Repita a nova senha"
                  required
                />
              </div>
              {passwordError && <p className="text-sm text-red-600">{passwordError}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" className="btn btn-ghost btn-sm" onClick={handleLogout} disabled={passwordChanging}>
                  Sair
                </button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={passwordChanging}>
                  {passwordChanging ? 'Salvando...' : 'Salvar nova senha'}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      {showSidebar && (
        <aside className="hidden w-64 flex-col border-r border-slate-200 bg-white px-4 py-6 shadow-sm lg:flex lg:sticky lg:top-0 lg:h-screen">
          <div className="mb-8 flex items-center gap-2 px-2">
            <span className="text-xl font-semibold text-slate-900">NacionalSign</span>
          </div>
          <nav className="flex flex-1 flex-col gap-1">
            {filteredNavItems.map(item => (
              <button
                key={item.key}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                  activeView === item.key
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
                onClick={() => changeView(item.key)}
              >
                <span>{item.icon}</span>
                {item.label}
              </button>
            ))}
            <div className="mt-auto rounded-lg border border-slate-200 bg-slate-50 px-3 py-4 text-xs text-slate-500">
              <p className="font-semibold text-slate-600">Usuário</p>
              <p className="text-sm text-slate-700">{me?.full_name ?? '---'}</p>
              {me?.email ? <p className="mt-1 break-words text-[11px] text-slate-500">{me.email}</p> : null}
              <p className="mt-2 uppercase text-[10px] tracking-wide text-slate-400">
                Perfil: {profileLabel ?? '---'}
              </p>
              <div className="mt-3 flex flex-col gap-2">
                <button
                  className="w-full rounded-md border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
                  onClick={() => changeView('settings')}
                >
                  Minhas configurações
                </button>
                <button
                  className="w-full rounded-md border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
                  onClick={handleLogout}
                >
                  Sair
                </button>
              </div>
            </div>
          </nav>
        </aside>
      )}

      <div className="flex flex-1 flex-col">
        {token && (
          <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur shadow-sm">
            <div className="flex flex-col gap-3 px-6 py-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h1 className="text-xl font-semibold text-slate-900">
                    {me?.full_name ?? 'Usuário'}
                  </h1>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span>Perfil: {profileLabel ?? '---'}</span>
                    {me?.email ? <span className="hidden sm:inline">Email: {me.email}</span> : null}
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <NotificationBell onSelectDocument={handleNotificationNavigate} />
                  <div className="flex flex-wrap gap-2">
                    <button
                      className={`btn btn-sm ${activeView === 'documents' ? 'btn-primary' : 'btn-ghost'}`}
                      onClick={() => changeView('documents')}
                    >
                      Documentos
                    </button>
                    <button
                      className={`btn btn-sm ${activeView === 'templates' ? 'btn-primary' : 'btn-ghost'}`}
                      onClick={() => changeView('templates')}
                    >
                      Templates
                    </button>
                    {canManageCustomers && (
                      <button
                        className={`btn btn-sm ${isCustomersView ? 'btn-primary' : 'btn-ghost'}`}
                        onClick={() => changeView('relationships')}
                      >
                        Clientes
                      </button>
                    )}
                    <button
                      className={`btn btn-sm ${activeView === 'settings' ? 'btn-primary' : 'btn-ghost'}`}
                      onClick={() => changeView('settings')}
                    >
                      Meu cadastro
                    </button>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {metrics.map(item => {
                  const focusFilter = metricClickMap[item.key];
                  const cardClasses =
                    "rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 shadow-inner transition";
                  const content = (
                    <>
                      <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-500">
                        <span className="text-lg">{item.icon}</span>
                        <span>{item.label}</span>
                      </div>
                      <p className="mt-1 text-2xl font-semibold text-slate-900">{item.value}</p>
                    </>
                  );
                  if (focusFilter) {
                    return (
                      <button
                        key={item.key}
                        type="button"
                        className={`${cardClasses} text-left hover:border-indigo-300 hover:bg-indigo-50`}
                        onClick={() => handleMetricCardClick(focusFilter)}
                      >
                        {content}
                      </button>
                    );
                  }
                  return (
                    <div key={item.key} className={cardClasses}>
                      {content}
                    </div>
                  );
                })}
              </div>
            </div>
          </header>
        )}

        <main className="flex-1 px-6 py-8">
          {renderContent()}
        </main>
      </div>

      <Toaster position="top-right" toastOptions={{ duration: 4000 }} />
      {mustChangePassword && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 px-4">
          <form
            className="w-full max-w-md space-y-4 rounded-xl bg-white p-6 shadow-2xl"
            onSubmit={handlePasswordChangeSubmit}
          >
            <div>
              <h2 className="text-lg font-semibold text-slate-800">Defina uma nova senha</h2>
              <p className="mt-1 text-sm text-slate-500">
                Por segurança, você precisa alterar a senha temporária antes de continuar utilizando a plataforma.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">Nova senha</label>
              <input
                type="password"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={passwordForm.newPassword}
                onChange={event => setPasswordForm(prev => ({ ...prev, newPassword: event.target.value }))}
                placeholder="Informe a nova senha"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">Confirmar nova senha</label>
              <input
                type="password"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={passwordForm.confirmPassword}
                onChange={event => setPasswordForm(prev => ({ ...prev, confirmPassword: event.target.value }))}
                placeholder="Repita a nova senha"
                required
              />
            </div>
            {passwordError && <p className="text-sm text-red-600">{passwordError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-ghost btn-sm" onClick={handleLogout} disabled={passwordChanging}>
                Sair
              </button>
              <button type="submit" className="btn btn-primary btn-sm" disabled={passwordChanging}>
                {passwordChanging ? 'Salvando...' : 'Salvar nova senha'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export default App;
