import { useMutation, useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  createTemplate,
  duplicateTemplate,
  fetchTemplates,
  updateTemplate,
  toggleTemplate,
  deleteTemplate,
  WorkflowTemplate,
  WorkflowTemplateStep,
  TemplateIndexResponse,
} from '../api';
import StepBuilder, { BuilderStep } from '../components/StepBuilder';

const digitsOnly = (value: string) => value.replace(/\D/g, '');

const normalize = (steps: BuilderStep[]): WorkflowTemplateStep[] =>
  steps.map((step, index) => ({
    order: index + 1,
    role: step.role.trim().toLowerCase(),
    action: step.action.trim().toLowerCase(),
    execution: step.execution,
    deadline_hours: step.deadline_hours,
    notification_channel: step.notification_channel,
    signature_method: step.signature_method,
    representative_name: step.representative_name.trim() || undefined,
    representative_cpf: digitsOnly(step.representative_cpf) || undefined,
    company_name: step.company_name.trim() || undefined,
    company_tax_id: digitsOnly(step.company_tax_id) || undefined,
    representative_email: step.representative_email.trim().toLowerCase() || undefined,
    representative_phone: digitsOnly(step.representative_phone) || undefined,
  }));

const defaultSteps = (): BuilderStep[] => [
  {
    id: crypto.randomUUID(),
    order: 1,
    role: 'signer',
    action: 'sign',
    execution: 'sequential',
    deadline_hours: null,
    notification_channel: 'email',
    signature_method: 'electronic',
    representative_name: '',
    representative_cpf: '',
    company_name: '',
    company_tax_id: '',
    representative_email: '',
    representative_phone: '',
  },
];

const FlowPreview = ({ steps }: { steps: BuilderStep[] }) => {
  if (!steps.length) return null;

  const formatCpf = (value: string) => {
    const digits = digitsOnly(value);
    if (digits.length !== 11) return value || '';
    return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
  };

  const formatCnpj = (value: string) => {
    const digits = digitsOnly(value);
    if (digits.length !== 14) return value || '';
    return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12)}`;
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-6">
      <h3 className="text-base font-semibold text-slate-800 mb-4">Pre-visualizacao do fluxo</h3>
      <div className="flex flex-wrap justify-center gap-6">
        {steps.map((step, index) => (
          <div key={step.id} className="w-48 rounded-lg bg-white border border-slate-300 px-4 py-3 shadow text-center">
            <div className="text-xs text-slate-500">Etapa {index + 1}</div>
            <div className="mt-1 text-lg font-semibold capitalize text-slate-900">{step.role}</div>
            <div className="mt-1 text-sm text-slate-600">
              {step.action} - {step.execution === 'sequential' ? 'Sequencial' : 'Paralelo'}
            </div>
            <div className="mt-2 text-xs uppercase text-slate-500">{step.notification_channel}</div>
            <div className="mt-1 text-xs text-slate-500">
              {step.signature_method === 'digital' ? 'Ass. digital' : 'Ass. eletrônica'}
            </div>
            {step.deadline_hours && <div className="mt-1 text-xs text-slate-500">Prazo: {step.deadline_hours}h</div>}
            {step.representative_name && (
              <div className="mt-2 text-xs text-slate-600">
                Rep.: <span className="font-semibold">{step.representative_name}</span>
              </div>
            )}
            {step.representative_cpf && (
              <div className="text-[11px] text-slate-500">CPF: {formatCpf(step.representative_cpf)}</div>
            )}
            {step.company_name && <div className="text-[11px] text-slate-500">Empresa: {step.company_name}</div>}
            {step.company_tax_id && (
              <div className="text-[11px] text-slate-500">CNPJ: {formatCnpj(step.company_tax_id)}</div>
            )}
            {step.representative_email && <div className="text-[11px] text-slate-500 break-all">Email: {step.representative_email}</div>}
            {step.representative_phone && (
              <div className="text-[11px] text-slate-500">Tel: {digitsOnly(step.representative_phone)}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

interface TemplatesPageProps {
  tenantId: string;
  onTenantChange: (tenant: string) => void;
  areaId?: string;
  onAreaChange: (area?: string) => void;
  currentProfile?: string | null;
  currentAreaId?: string | null;
}

type TemplateListItem = WorkflowTemplate & { area_name?: string };

const resolveErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detail;
    }
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
};

function TemplatesPage({
  tenantId,
  onTenantChange: _onTenantChange,
  areaId,
  onAreaChange,
  currentProfile,
  currentAreaId,
}: TemplatesPageProps) {
  const normalizedProfile = (currentProfile ?? '').toLowerCase();
  const canManageAllAreas = normalizedProfile === 'owner' || normalizedProfile === 'admin';
  const enforcedArea = canManageAllAreas ? areaId ?? '' : currentAreaId ?? '';
  const [selectedArea, setSelectedArea] = useState(enforcedArea);
  const [steps, setSteps] = useState<BuilderStep[]>(defaultSteps());
  const [name, setName] = useState('Novo template');
  const [description, setDescription] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateListItem | null>(null);
  const [activeTab, setActiveTab] = useState<'list' | 'form'>('list');
  void _onTenantChange;

  useEffect(() => {
    const nextArea = enforcedArea;
    if (nextArea !== selectedArea) {
      setSelectedArea(nextArea);
      if (!canManageAllAreas) {
        onAreaChange(nextArea || undefined);
      }
    }
  }, [enforcedArea, selectedArea, canManageAllAreas, onAreaChange]);

  const {
    data,
    refetch,
    isFetching,
    error: templatesError,
    isError: isTemplatesError,
  } = useQuery<TemplateIndexResponse>({
    queryKey: ['templates', tenantId, selectedArea || 'all'],
    queryFn: () => fetchTemplates(tenantId, selectedArea || undefined),
    enabled: Boolean(tenantId && (canManageAllAreas || selectedArea)),
  });

  const rawAreas = useMemo(() => data?.areas ?? [], [data]);
  const areas = useMemo(() => {
    if (canManageAllAreas) return rawAreas;
    if (!currentAreaId) return [];
    return rawAreas.filter(area => area.id === currentAreaId);
  }, [rawAreas, canManageAllAreas, currentAreaId]);
  const areasLoading = isFetching && areas.length === 0;
  const areasError = isTemplatesError && areas.length === 0;
  const areaLookup = useMemo(
    () =>
      areas.reduce<Record<string, string>>((acc, area) => {
        acc[area.id] = area.name;
        return acc;
      }, {}),
    [areas],
  );
  const templateList: TemplateListItem[] = useMemo(() => {
    const templates = data?.templates ?? [];
    if (!selectedArea) return templates;
    return templates.filter(template => template.area_id === selectedArea);
  }, [data, selectedArea]);
  const selectedAreaName = useMemo(() => areaLookup[selectedArea] ?? null, [areaLookup, selectedArea]);

  useEffect(() => {
    if (canManageAllAreas && !selectedArea && areas.length > 0) {
      const nextArea = areas[0].id;
      setSelectedArea(nextArea);
      onAreaChange(nextArea);
    }
  }, [areas, onAreaChange, selectedArea, canManageAllAreas]);

  useEffect(() => {
    if (!selectedTemplate) {
      setName('Novo template');
      setDescription('');
      setSteps(defaultSteps());
      return;
    }

    const safeSteps = selectedTemplate.steps ?? [];
    setName(selectedTemplate.name);
    setDescription(selectedTemplate.description ?? '');
    setSteps(
      safeSteps.map((step, index) => ({
        id: crypto.randomUUID(),
        order: index + 1,
        role: step.role,
        action: step.action,
        execution: step.execution === 'parallel' ? 'parallel' : 'sequential',
        deadline_hours: step.deadline_hours,
        notification_channel: step.notification_channel === 'sms' ? 'sms' : 'email',
        signature_method: step.signature_method === 'digital' ? 'digital' : 'electronic',
        representative_name: step.representative_name ?? '',
        representative_cpf: step.representative_cpf ?? '',
        company_name: step.company_name ?? '',
        company_tax_id: step.company_tax_id ?? '',
        representative_email: step.representative_email ?? '',
        representative_phone: step.representative_phone ?? '',
      })),
    );
    setActiveTab('form');
  }, [selectedTemplate]);

  const createMutation = useMutation({
    mutationFn: (payload: { area_id: string; name: string; description?: string; steps: WorkflowTemplateStep[] }) =>
      createTemplate(tenantId, payload),
    onSuccess: () => {
      refetch();
      setSelectedTemplate(null);
      setActiveTab('list');
      setSteps(defaultSteps());
      setName('Novo template');
      setDescription('');
      toast.success('Template criado');
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: { templateId: string; data: { name?: string; description?: string; steps: WorkflowTemplateStep[] } }) =>
      updateTemplate(tenantId, input.templateId, input.data, selectedArea),
    onSuccess: () => {
      refetch();
      setSelectedTemplate(null);
      setActiveTab('list');
      setSteps(defaultSteps());
      setName('Novo template');
      setDescription('');
      toast.success('Template atualizado');
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (input: { templateId: string; nextStatus: boolean; areaId?: string }) =>
      toggleTemplate(tenantId, input.templateId, input.nextStatus, input.areaId),
    onSuccess: () => refetch(),
  });

  const duplicateMutation = useMutation({
    mutationFn: (params: { templateId: string; name: string; targetAreaId?: string; areaId?: string }) =>
      duplicateTemplate(tenantId, params.templateId, params.name, params.targetAreaId, params.areaId),
    onSuccess: () => refetch(),
  });

  const deleteMutation = useMutation({
    mutationFn: (templateId: string) => deleteTemplate(tenantId, templateId),
    onSuccess: () => {
      toast.success('Template excluído');
      refetch();
    },
  });

  const isSaving = createMutation.isPending || updateMutation.isPending;

  const handleSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedArea) {
      toast.error('Selecione uma area antes de salvar');
      return;
    }
    const normalizedSteps = normalize(steps);
    try {
      if (selectedTemplate) {
        await updateMutation.mutateAsync({
          templateId: selectedTemplate.id,
          data: { name, description: description || undefined, steps: normalizedSteps },
        });
      } else {
        await createMutation.mutateAsync({
          area_id: selectedArea,
          name,
          description: description || undefined,
          steps: normalizedSteps,
        });
      }
    } catch (error) {
      toast.error(resolveErrorMessage(error, 'Erro ao salvar template'));
    }
  };

  const handleToggle = async (template: TemplateListItem) => {
    try {
      await toggleMutation.mutateAsync({
        templateId: template.id,
        nextStatus: !template.is_active,
        areaId: template.area_id,
      });
      toast.success(template.is_active ? 'Template desativado' : 'Template ativado');
    } catch (error) {
      toast.error(resolveErrorMessage(error, 'Erro ao atualizar status'));
    }
  };

  const handleDuplicate = async (template: TemplateListItem) => {
    try {
      await duplicateMutation.mutateAsync({
        templateId: template.id,
        name: `${template.name} (copia)`,
        targetAreaId: selectedArea || template.area_id,
        areaId: selectedArea || template.area_id,
      });
      toast.success('Template duplicado');
    } catch (error) {
      toast.error(resolveErrorMessage(error, 'Erro ao duplicar template'));
    }
  };

  const handleDelete = async (template: TemplateListItem) => {
    const confirmed = window.confirm(`Excluir o template "${template.name}"? Essa ação não pode ser desfeita.`);
    if (!confirmed) return;
    try {
      await deleteMutation.mutateAsync(template.id);
      if (selectedTemplate?.id === template.id) {
        setSelectedTemplate(null);
        setActiveTab('list');
      }
    } catch (error) {
      toast.error(resolveErrorMessage(error, 'Erro ao excluir template'));
    }
  };

  const handleSelectArea = (value: string) => {
    if (!canManageAllAreas) {
      return;
    }
    setSelectedArea(value);
    onAreaChange(value);
    setSelectedTemplate(null);
    setActiveTab('list');
    setSteps(defaultSteps());
    setName('Novo template');
    setDescription('');
  };

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="max-w-6xl mx-auto space-y-8">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-slate-900">Modelos de workflow</h1>
          <p className="text-sm text-slate-600 mt-1">Organize e padronize os fluxos de assinatura da sua area</p>
        </div>

        <div className="max-w-2xl mx-auto w-full space-y-2">
          <label className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            Area responsavel
            {selectedAreaName && (
              <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-normal text-slate-600">
                {selectedAreaName}
              </span>
            )}
          </label>
          <p className="text-xs text-slate-500">
            Os templates ficam visiveis somente para usuarios da mesma area. Escolha abaixo qual contexto deseja administrar.
          </p>
          {areasLoading ? (

            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">

              Carregando areas disponiveis...

            </div>

          ) : areasError ? (

            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              Nao foi possivel carregar as areas. Atualize e tente novamente.
              {templatesError instanceof Error && (
                <span className="block text-xs text-rose-500 mt-1">{templatesError.message}</span>
              )}
            </div>

          ) : areas.length === 0 ? (

            <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-3 text-sm text-slate-500">

              Nenhuma area cadastrada para este tenant. Cadastre uma area primeiro para criar modelos de workflow.

            </div>

          ) : canManageAllAreas ? (

            <div className="relative">

              <select

                className="w-full border border-slate-300 rounded-lg px-4 py-2 bg-white text-sm appearance-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"

                value={selectedArea}

                onChange={event => handleSelectArea(event.target.value)}

              >
                {!selectedArea && <option value="">Selecione uma area</option>}
                {areas.map(area => (
                  <option key={area.id} value={area.id}>
                    {area.name}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-slate-400">v</span>
            </div>

          ) : (

            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
              {selectedAreaName
                ? `Você está limitado à área "${selectedAreaName}".`
                : 'Nenhuma área padrão atribuída. Solicite ao administrador para configurar sua área.'}
            </div>

          )}
        </div>

        <div className="flex justify-center">
          <div className="inline-flex rounded-md shadow-sm bg-white">
            <button
              className={`px-6 py-2 rounded-l-md text-sm font-medium ${
                activeTab === 'list' ? 'bg-indigo-600 text-white' : 'text-slate-700'
              }`}
              onClick={() => setActiveTab('list')}
            >
              Templates existentes
            </button>
            <button
              className={`px-6 py-2 rounded-r-md text-sm font-medium ${
                activeTab === 'form' ? 'bg-indigo-600 text-white' : 'text-slate-700'
              }`}
              onClick={() => {
                setSelectedTemplate(null);
                setActiveTab('form');
              }}
            >
              Criar ou editar
            </button>
          </div>
        </div>

        {activeTab === 'list' && (
          <div className="bg-white rounded-lg shadow border border-slate-200 p-6">
            <h2 className="text-lg font-semibold mb-4">Templates cadastrados</h2>
            {isFetching ? (
              <p className="text-center text-slate-500 py-8">Carregando...</p>
            ) : templateList.length === 0 ? (
              <p className="text-center text-slate-500 py-8">Nenhum template encontrado para esta area.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {templateList.map(template => (
                  <div key={template.id} className="bg-slate-50 rounded-lg border border-slate-200 p-5 space-y-3">
                    <div>
                      <h3 className="font-semibold text-lg text-slate-900">{template.name}</h3>
                      <p className="text-sm text-slate-600">
                        Area: {areaLookup[template.area_id] ?? template.area_name ?? template.area_id}
                      </p>
                      <p className="text-sm text-slate-600">{template.steps.length} etapas</p>
                      {template.description && <p className="text-sm text-slate-500 mt-2">{template.description}</p>}
                    </div>
                    <span
                      className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${
                        template.is_active ? 'bg-green-100 text-green-800' : 'bg-slate-200 text-slate-700'
                      }`}
                    >
                      {template.is_active ? 'Ativo' : 'Inativo'}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <button className="btn btn-secondary text-sm" onClick={() => handleToggle(template)}>
                        {template.is_active ? 'Desativar' : 'Ativar'}
                      </button>
                      <button className="btn btn-secondary text-sm" onClick={() => setSelectedTemplate(template)}>
                        Editar
                      </button>
                      <button className="btn btn-primary text-sm" onClick={() => handleDuplicate(template)}>
                        Duplicar
                      </button>
                      <button
                        className="btn btn-danger text-sm"
                        onClick={() => handleDelete(template)}
                        disabled={deleteMutation.isPending && deleteMutation.variables === template.id}
                      >
                        {deleteMutation.isPending && deleteMutation.variables === template.id ? 'Excluindo...' : 'Excluir'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'form' && (
          <div className="max-w-4xl mx-auto bg-white rounded-lg shadow border border-slate-200 p-8">
            <h2 className="text-xl font-semibold mb-6 text-center">
              {selectedTemplate ? 'Editar template' : 'Criar novo template'}
            </h2>
            {!canManageAllAreas && !selectedArea && (
              <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                Configure uma área padrão com um administrador para criar modelos.
              </div>
            )}
            <form onSubmit={handleSave} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Nome</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-4 py-2"
                  value={name}
                  onChange={event => setName(event.target.value)}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Descricao (opcional)</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-4 py-2"
                  value={description}
                  onChange={event => setDescription(event.target.value)}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-3">Configurar etapas do fluxo</label>
                <div className="bg-slate-50 rounded-lg p-4">
                  <StepBuilder value={steps} onChange={setSteps} />
                </div>
              </div>
              <FlowPreview steps={steps} />
              <div className="text-center">
                <button type="submit" className="px-8 py-3 btn btn-primary" disabled={isSaving || !selectedArea}>
                  {isSaving ? 'Salvando...' : 'Salvar template'}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}

export default TemplatesPage;
