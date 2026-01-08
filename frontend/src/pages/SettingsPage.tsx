import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import MySettingsPage from './MySettingsPage';
import SettingsAreasTab from '../components/settings/SettingsAreasTab';
import {
  fetchMyCompanyProfile,
  fetchTemplates,
  type CustomerSummary,
  type TemplateIndexResponse,
  type UserMe,
  type WorkflowTemplate,
} from '../api';

type SettingsTabKey = 'account' | 'areas' | 'templates' | 'company';

const tabItems: Array<{ key: SettingsTabKey; label: string; helper: string }> = [
  { key: 'account', label: 'Minha conta', helper: 'Dados pessoais e preferências' },
  { key: 'company', label: 'Minha empresa', helper: 'Razão social, nome fantasia e CNPJ' },
  { key: 'areas', label: 'Áreas da empresa', helper: 'Estruture times e permissões' },
  { key: 'templates', label: 'Templates por área', helper: 'Conecte fluxos às áreas' },
];

const SETTINGS_TAB_PARAM = 'settingsTab';
const SETTINGS_TAB_STORAGE_KEY = 'nacionalsign.settings.activeTab';
const allowedTabs: SettingsTabKey[] = ['account', 'company', 'areas', 'templates'];
const AREALESS_KEY = '__without-area__';

const isSettingsTabKey = (value: string | null): value is SettingsTabKey =>
  Boolean(value && allowedTabs.includes(value as SettingsTabKey));

const resolveInitialTab = (): SettingsTabKey => {
  if (typeof window === 'undefined') return 'account';
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get(SETTINGS_TAB_PARAM);
  if (isSettingsTabKey(fromQuery)) return fromQuery;
  try {
    const stored = window.localStorage.getItem(SETTINGS_TAB_STORAGE_KEY);
    if (isSettingsTabKey(stored)) return stored;
  } catch {
    // ignore storage errors
  }
  return 'account';
};

type TemplateWithOptionalArea = WorkflowTemplate & { area_name?: string };

interface TemplateAreaSummary {
  areaKey: string;
  areaId?: string;
  areaName: string;
  total: number;
  active: number;
  latestTemplate?: TemplateWithOptionalArea;
  latestTimestamp?: number;
}

interface SettingsPageProps {
  currentUser: UserMe | null;
  tenantId?: string;
  onUserUpdated?: (user: UserMe) => void;
  onOpenTemplates?: (areaId?: string) => void;
}

interface TemplatesTabContentProps {
  loading: boolean;
  error: string | null;
  summaries: TemplateAreaSummary[];
  recentTemplates: TemplateWithOptionalArea[];
  hasTenant: boolean;
  onRefresh: () => void;
  onOpenTemplates?: (areaId?: string) => void;
}

const TemplatesTabContent = ({
  loading,
  error,
  summaries,
  recentTemplates,
  hasTenant,
  onRefresh,
  onOpenTemplates,
}: TemplatesTabContentProps) => {
  if (!hasTenant) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-800">
        Vincule-se a um tenant ou selecione uma empresa para ver o painel de templates.
      </div>
    );
  }

  const formatDateTime = (value?: string | null) => {
    if (!value) return 'sem registro';
    try {
      return new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' });
    } catch {
      return value;
    }
  };

  const areaNameResolver = useMemo(() => {
    const map = new Map<string, string>();
    summaries.forEach(summary => {
      if (summary.areaId) map.set(summary.areaId, summary.areaName);
      map.set(summary.areaKey, summary.areaName);
    });
    return map;
  }, [summaries]);

  return (
    <div className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Templates por área</h2>
        <p className="mt-1 text-sm text-slate-500">
          Cada template precisa estar vinculado a uma área para garantir que somente os times corretos visualizem
          fluxos e documentos. Use os atalhos abaixo para manter áreas e templates sincronizados.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100"
          type="button"
          onClick={() => onOpenTemplates?.()}
        >
          Abrir gerenciador de templates
        </button>
        <button
          className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-70"
          type="button"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? 'Atualizando...' : 'Atualizar resumo'}
        </button>
        <p className="text-xs text-slate-500">
          Dica: defina a área padrão do usuário em &ldquo;Minha conta&rdquo; para limitar quais templates ele enxerga.
        </p>
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-700">Resumo por área</h3>
          {!loading && summaries.length > 0 && (
            <span className="text-xs uppercase tracking-wide text-slate-400">
              {summaries.length} área{summaries.length > 1 ? 's' : ''} com templates
            </span>
          )}
        </div>
        {error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>
        ) : loading ? (
          <p className="text-sm text-slate-500">Carregando templates...</p>
        ) : summaries.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nenhum template cadastrado ainda. Crie fluxos a partir do gerenciador para disponibilizá-los por área.
          </p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {summaries.map(summary => (
              <div
                key={summary.areaKey}
                className="flex flex-col justify-between rounded-lg border border-slate-200 bg-slate-50 p-4 shadow-inner"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <h4 className="text-base font-semibold text-slate-800">{summary.areaName}</h4>
                    <span
                      className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-500"
                      title="Templates ativos / totais"
                    >
                      {summary.active}/{summary.total}
                    </span>
                  </div>
                  {summary.latestTemplate ? (
                    <p className="mt-1 text-sm text-slate-600">
                      Último: <span className="font-medium">{summary.latestTemplate.name}</span> (
                      {formatDateTime(summary.latestTemplate.updated_at ?? summary.latestTemplate.created_at)})
                    </p>
                  ) : (
                    <p className="mt-1 text-sm text-slate-500">Nenhum template nesta área.</p>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-white"
                    type="button"
                    onClick={() => onOpenTemplates?.(summary.areaId)}
                  >
                    Gerenciar templates
                  </button>
                  <button
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-white"
                    type="button"
                    onClick={() => onOpenTemplates?.(summary.areaId)}
                  >
                    Duplicar fluxo
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-700">Últimos templates atualizados</h3>
          {recentTemplates.length > 0 && (
            <span className="text-xs uppercase tracking-wide text-slate-400">
              {recentTemplates.length} registro{recentTemplates.length > 1 ? 's' : ''}
            </span>
          )}
        </div>
        {recentTemplates.length === 0 ? (
          <p className="text-sm text-slate-500">Nenhuma alteração recente encontrada.</p>
        ) : (
          <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-slate-50">
            {recentTemplates.map(template => {
              const areaKey = template.area_id ?? AREALESS_KEY;
              const areaLabel =
                areaNameResolver.get(template.area_id ?? '') ??
                areaNameResolver.get(areaKey) ??
                template.area_name ??
                'Sem área';
              return (
                <li
                  key={template.id}
                  className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-semibold text-slate-800">{template.name}</p>
                    <p className="text-xs text-slate-500">
                      Área: <span className="font-medium">{areaLabel}</span> •{' '}
                      {template.is_active ? 'Ativo' : 'Inativo'}
                    </p>
                  </div>
                  <div className="text-xs text-slate-500">
                    Atualizado em {formatDateTime(template.updated_at ?? template.created_at)}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
};

const formatCnpj = (raw: string | null | undefined): string => {
  if (!raw) return '—';
  const digits = raw.replace(/\D/g, '');
  if (digits.length !== 14) return raw;
  return digits.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
};

const CompanyProfileTab = () => {
  const [company, setCompany] = useState<CustomerSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCompany = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMyCompanyProfile();
      setCompany(data);
    } catch (err) {
      console.error(err);
      setError('Não foi possível carregar as informações da empresa.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCompany();
  }, [loadCompany]);

  const infoEntries = [
    { label: 'Razão social', value: company?.corporate_name ?? '—' },
    { label: 'Nome fantasia', value: company?.trade_name ?? '—' },
    { label: 'CNPJ', value: formatCnpj(company?.cnpj ?? null) },
    { label: 'Responsável', value: company?.responsible_name ?? '—' },
    { label: 'E-mail do responsável', value: company?.responsible_email ?? '—' },
    { label: 'Telefone do responsável', value: company?.responsible_phone ?? '—' },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4">
        <h2 className="text-xl font-semibold text-slate-800">Minha empresa</h2>
        <p className="mt-1 text-sm text-slate-500">
          Dados oficiais da empresa vinculada ao seu ambiente. Mantenha razão social, nome fantasia e contatos sempre
          atualizados para evitar divergências em contratos e notificações.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Carregando informações...</p>
      ) : error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          <p>{error}</p>
          <button
            type="button"
            className="mt-3 rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition hover:bg-white"
            onClick={() => void loadCompany()}
          >
            Tentar novamente
          </button>
        </div>
      ) : company ? (
        <dl className="grid gap-4 md:grid-cols-2">
          {infoEntries.map(entry => (
            <div key={entry.label} className="rounded-lg border border-slate-100 bg-slate-50 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">{entry.label}</dt>
              <dd className="mt-1 text-base font-medium text-slate-800">{entry.value || '—'}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
          Não encontramos um cadastro de empresa vinculado a este tenant. Solicite ao suporte a ativação do seu cliente.
        </div>
      )}
    </div>
  );
};

export default function SettingsPage({ currentUser, tenantId, onUserUpdated, onOpenTemplates }: SettingsPageProps) {
  const [activeTab, setActiveTab] = useState<SettingsTabKey>(() => resolveInitialTab());
  const [templatesData, setTemplatesData] = useState<TemplateIndexResponse | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [templatesFetched, setTemplatesFetched] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(SETTINGS_TAB_STORAGE_KEY, activeTab);
    } catch {
      // ignore
    }
    const url = new URL(window.location.href);
    url.searchParams.set(SETTINGS_TAB_PARAM, activeTab);
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  }, [activeTab]);

  const loadTemplates = useCallback(async () => {
    if (!tenantId) return;
    setTemplatesLoading(true);
    setTemplatesError(null);
    try {
      const response = await fetchTemplates(tenantId);
      if (!mountedRef.current) return;
      setTemplatesData(response);
      setTemplatesFetched(true);
    } catch (error) {
      console.error(error);
      if (!mountedRef.current) return;
      setTemplatesError('Não foi possível carregar o resumo de templates.');
    } finally {
      if (mountedRef.current) {
        setTemplatesLoading(false);
      }
    }
  }, [tenantId]);

  useEffect(() => {
    setTemplatesFetched(false);
    setTemplatesData(null);
    setTemplatesError(null);
  }, [tenantId]);

  useEffect(() => {
    if (activeTab !== 'templates' || templatesFetched || templatesLoading || !tenantId) return;
    void loadTemplates();
  }, [activeTab, templatesFetched, templatesLoading, tenantId, loadTemplates]);

  const areaSummaries = useMemo<TemplateAreaSummary[]>(() => {
    if (!templatesData?.templates?.length) return [];
    const areas = new Map<string, string>();
    templatesData.areas?.forEach(area => areas.set(area.id, area.name));

    const grouped = templatesData.templates.reduce<Record<string, TemplateAreaSummary>>((acc, template) => {
      const templateWithArea = template as TemplateWithOptionalArea;
      const areaKey = template.area_id ?? AREALESS_KEY;
      if (!acc[areaKey]) {
        acc[areaKey] = {
          areaKey,
          areaId: template.area_id ?? undefined,
          areaName: areas.get(template.area_id ?? '') ?? templateWithArea.area_name ?? 'Sem área',
          total: 0,
          active: 0,
        };
      }
      acc[areaKey].total += 1;
      if (template.is_active) acc[areaKey].active += 1;
      const timestamp = new Date(template.updated_at ?? template.created_at ?? new Date().toISOString()).getTime();
      if (!acc[areaKey].latestTimestamp || timestamp > acc[areaKey].latestTimestamp!) {
        acc[areaKey].latestTimestamp = timestamp;
        acc[areaKey].latestTemplate = templateWithArea;
      }
      return acc;
    }, {});

    return Object.values(grouped).sort((a, b) => a.areaName.localeCompare(b.areaName, 'pt-BR'));
  }, [templatesData]);

  const recentTemplates = useMemo<TemplateWithOptionalArea[]>(() => {
    if (!templatesData?.templates?.length) return [];
    return [...templatesData.templates]
      .sort(
        (a, b) =>
          new Date(b.updated_at ?? b.created_at).getTime() - new Date(a.updated_at ?? a.created_at).getTime(),
      )
      .slice(0, 5);
  }, [templatesData]);

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'company':
        return <CompanyProfileTab />;
      case 'areas':
        return <SettingsAreasTab />;
      case 'templates':
        return (
          <TemplatesTabContent
            loading={templatesLoading}
            error={templatesError}
            summaries={areaSummaries}
            recentTemplates={recentTemplates}
            hasTenant={Boolean(tenantId)}
            onRefresh={() => void loadTemplates()}
            onOpenTemplates={onOpenTemplates}
          />
        );
      case 'account':
      default:
        return <MySettingsPage currentUser={currentUser} onUserUpdated={onUserUpdated} />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold text-slate-800">Configurações</h1>
          <p className="text-sm text-slate-500">
            Use as guias abaixo para manter alinhados seus dados pessoais, as áreas corporativas e os templates que
            dependem delas. Assim cada usuário só enxerga documentos e fluxos da própria área.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {tabItems.map(tab => (
            <button
              key={tab.key}
              type="button"
              className={`rounded-lg border px-4 py-2 text-sm transition ${
                activeTab === tab.key
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                  : 'border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900'
              }`}
              onClick={() => setActiveTab(tab.key)}
            >
              <div className="flex flex-col text-left">
                <span className="font-semibold">{tab.label}</span>
                <span className="text-xs text-slate-500">{tab.helper}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
      {renderActiveTab()}
    </div>
  );
}
