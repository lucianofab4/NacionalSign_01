import { useMutation, useQuery } from '@tanstack/react-query';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  createTemplate,
  duplicateTemplate,
  fetchTemplates,
  updateTemplate,
  toggleTemplate,
  fetchDocumentParties,
  type DocumentParty,
  WorkflowTemplate,
  WorkflowTemplateStep,
  TemplateIndexResponse,
  DocumentSummary,
  fetchUsage,
  type Usage,
} from '../api';
import StepBuilder, { BuilderStep, PartySuggestion } from '../components/StepBuilder';
import { resolveApiBaseUrl } from '../utils/env';

interface TemplatesPageProps {
  tenantId: string;
  onTenantChange: (tenant: string) => void;
  areaId?: string;
  onAreaChange: (area?: string) => void;
}

type TemplateListItem = WorkflowTemplate & { area_name?: string };

const normalize = (steps: BuilderStep[]): WorkflowTemplateStep[] =>
  steps.map((step, index) => ({
    order: index + 1,
    role: step.role.trim().toLowerCase(),
    action: step.action.trim().toLowerCase(),
    execution: step.execution,
    deadline_hours: step.deadline_hours,
    notification_channel: step.notification_channel,
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
  },
];

const FlowPreview = ({ steps }: { steps: BuilderStep[] }) => {
  if (!steps.length) {
    return null;
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-900 text-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300 mb-2">Pré-visualização do fluxo</h3>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {steps.map((step, index) => (
          <div key={step.id} className="min-w-[168px] rounded-md bg-slate-800 px-3 py-2">
            <div className="text-xs text-slate-400">Etapa {index + 1}</div>
            <div className="text-sm font-semibold capitalize">{step.role}</div>
            <div className="text-xs text-slate-300">
              {step.action} • {step.execution === 'sequential' ? 'Sequencial' : 'Paralelo'}
            </div>
            <div className="text-xs text-slate-400 mt-1">Canal: {step.notification_channel.toUpperCase()}</div>
            {step.deadline_hours && <div className="text-xs text-slate-400">Prazo: {step.deadline_hours}h</div>}
          </div>
        ))}
      </div>
    </div>
  );
};

function TemplatesPage({ tenantId, onTenantChange, areaId, onAreaChange }: TemplatesPageProps) {
  const [localTenant, setLocalTenant] = useState(tenantId);
  const [localArea, setLocalArea] = useState(areaId ?? '');
  const [steps, setSteps] = useState<BuilderStep[]>(defaultSteps);
  const [name, setName] = useState('Fluxo padrão');
  const [description, setDescription] = useState('');
  const [documentFilter, setDocumentFilter] = useState('');
  const [documentId, setDocumentId] = useState<string | undefined>(undefined);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateListItem | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const tenantReady = Boolean(tenantId);
  const apiBaseUrl = resolveApiBaseUrl();

  // Sincroniza campos locais quando props mudam (ex.: após login auto-preencher)
  useEffect(() => {
    setLocalTenant(tenantId);
  }, [tenantId]);
  useEffect(() => {
    setLocalArea(areaId ?? '');
  }, [areaId]);

  const { data, refetch, isFetching } = useQuery<TemplateIndexResponse>({
    queryKey: ['templates', tenantId, areaId],
    queryFn: () => fetchTemplates(tenantId, areaId),
    enabled: tenantReady,
  });

  const templateList: TemplateListItem[] = useMemo(() => data?.templates ?? [], [data]);
  const areas = data?.areas ?? [];
  const documents = data?.documents ?? [];

  const filteredDocuments = useMemo<DocumentSummary[]>(() => {
    if (!localArea) return documents;
    return documents.filter((document: DocumentSummary) => document.area_id === localArea);
  }, [documents, localArea]);

  const selectedDocument = useMemo(
    () => documents.find((document: DocumentSummary) => document.id === documentId),
    [documents, documentId],
  );

  const previewUrl = useMemo(() => {
    if (!selectedDocument) return null;
    return `${apiBaseUrl}/public/verification/${selectedDocument.id}/page`;
  }, [apiBaseUrl, selectedDocument]);

  useEffect(() => {
    if (!localArea && areas.length > 0) {
      setLocalArea(areas[0].id);
    }
  }, [areas, localArea]);

  useEffect(() => {
    if (filteredDocuments.length === 0) {
      setDocumentFilter('');
      return;
    }
    if (!documentFilter || !filteredDocuments.some((document: DocumentSummary) => document.id === documentFilter)) {
      setDocumentFilter(filteredDocuments[0].id);
    }
  }, [filteredDocuments, documentFilter]);

  useEffect(() => {
    const loadUsage = async () => {
      if (!tenantId) { setUsage(null); return; }
      try {
        const data = await fetchUsage();
        setUsage(data);
      } catch {
        setUsage(null);
      }
    };
    loadUsage();
  }, [tenantId]);

  useEffect(() => {
    if (selectedTemplate) {
      setName(selectedTemplate.name);
      setDescription(selectedTemplate.description ?? '');
      setSteps(
        selectedTemplate.steps.map((step, index) => ({
          id: crypto.randomUUID(),
          order: index + 1,
          role: step.role,
          action: step.action,
          execution: step.execution,
          deadline_hours: step.deadline_hours,
          notification_channel: step.notification_channel ?? 'email',
        })),
      );
    } else {
      setName('Fluxo padrão');
      setDescription('');
      setSteps(defaultSteps());
    }
  }, [selectedTemplate]);

  const {
    data: partiesData,
    refetch: refetchParties,
    isFetching: partiesLoading,
  } = useQuery({
    queryKey: ['document-parties', documentId, tenantId],
    queryFn: () => fetchDocumentParties(documentId as string),
    enabled: Boolean(tenantId && documentId),
  });

  const partySuggestions: PartySuggestion[] = useMemo(
    () =>
      (partiesData ?? []).map((party: DocumentParty) => ({
        role: party.role.toLowerCase(),
        email: party.email,
        phone_number: party.phone_number,
      })),
    [partiesData],
  );

  const createMutation = useMutation({
    mutationFn: (payload: { area_id: string; name: string; description?: string; steps: WorkflowTemplateStep[] }) =>
      createTemplate(tenantId, payload),
    onSuccess: () => refetch(),
  });

  const updateMutation = useMutation({
    mutationFn: (input: { templateId: string; data: { name?: string; description?: string; steps: WorkflowTemplateStep[] } }) =>
      updateTemplate(tenantId, input.templateId, input.data, areaId),
    onSuccess: () => refetch(),
  });

  const toggleMutation = useMutation({
    mutationFn: (templateId: string) => toggleTemplate(tenantId, templateId, areaId),
    onSuccess: () => refetch(),
  });

  const duplicateMutation = useMutation({
    mutationFn: (params: { templateId: string; name: string; targetAreaId?: string }) =>
      duplicateTemplate(tenantId, params.templateId, params.name, params.targetAreaId, areaId),
    onSuccess: () => refetch(),
  });

  const isSaving = createMutation.isPending || updateMutation.isPending;

  const handleToggleTemplate = async (template: TemplateListItem) => {
    try {
      await toggleMutation.mutateAsync(template.id);
      toast.success(template.is_active ? 'Template desativado' : 'Template ativado');
    } catch (error) {
      toast.error('Não foi possível atualizar o template');
    }
  };

  const handleDuplicateTemplate = async (template: TemplateListItem) => {
    try {
      await duplicateMutation.mutateAsync({
        templateId: template.id,
        name: `${template.name} (cópia)`,
      });
      toast.success('Template duplicado');
    } catch (error) {
      toast.error('Não foi possível duplicar o template');
    }
  };

  const handleFetch = (event: FormEvent) => {
    event.preventDefault();
    onTenantChange(localTenant);
    onAreaChange(localArea || undefined);
    setDocumentId(undefined);
    toast.success('Contexto atualizado');
  };

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!tenantId) {
      toast.error('Informe o tenant antes de salvar.');
      return;
    }
    if (!areaId) {
      toast.error('Selecione uma área antes de salvar.');
      return;
    }

    const normalizedSteps = normalize(steps);

    try {
      if (selectedTemplate) {
        await updateMutation.mutateAsync({
          templateId: selectedTemplate.id,
          data: {
            name,
            description: description || undefined,
            steps: normalizedSteps,
          },
        });
        toast.success('Template atualizado');
      } else {
        await createMutation.mutateAsync({
          area_id: areaId,
          name,
          description: description || undefined,
          steps: normalizedSteps,
        });
        toast.success('Template criado');
      }
      setSelectedTemplate(null);
    } catch (error) {
      toast.error('Não foi possível salvar o template');
    }
  };

  const handleLoadParties = async (event: FormEvent) => {
    event.preventDefault();
    if (!documentFilter) {
      toast.error('Selecione um documento para carregar as partes.');
      return;
    }
    try {
      setDocumentId(documentFilter);
      const result = await refetchParties();
      const total = (result.data ?? []).length;
      if (total === 0) {
        toast('Nenhuma parte encontrada para o documento selecionado.', { icon: 'ℹ️' });
      } else {
        toast.success(`Partes carregadas (${total})`);
      }
    } catch (error) {
      toast.error('Não foi possível carregar as partes do documento');
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong className="font-semibold">Dica rápida:</strong> selecione a área e, se quiser, um documento para sugerir papéis automaticamente.
      </div>

      <form onSubmit={handleFetch} className="bg-white rounded-xl shadow-sm p-6 border border-slate-200 space-y-4">
        <h2 className="text-lg font-semibold">Contexto</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-600">Tenant ID</label>
            <input
              className="w-full border border-slate-300 rounded-md px-3 py-2"
              value={localTenant}
              onChange={event => setLocalTenant(event.target.value)}
              placeholder="UUID do tenant"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600">Área</label>
            <select
              className="w-full border border-slate-300 rounded-md px-3 py-2"
              value={localArea}
              onChange={event => setLocalArea(event.target.value)}
            >
              <option value="">Todas as áreas</option>
              {areas.map(areaItem => (
                <option key={areaItem.id} value={areaItem.id}>
                  {areaItem.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {usage && (
          <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {(() => {
              const hasServerBanner = usage.near_limit && !!usage.message;
              if (hasServerBanner) return <div>{usage.message}</div>;
              const qDocs = usage.documents_quota ?? Infinity;
              const qUsers = usage.users_quota ?? Infinity;
              const nearDocs = qDocs !== Infinity && usage.documents_used / qDocs >= 0.8;
              const nearUsers = qUsers !== Infinity && usage.users_used / qUsers >= 0.8;
              if (!nearDocs && !nearUsers) return null;
              return (
                <div>
                  {nearDocs && (
                    <div>
                      Limite de documentos: {usage.documents_used}/{usage.documents_quota ?? '∞'} neste período.
                    </div>
                  )}
                  {nearUsers && (
                    <div>
                      Limite de usuários: {usage.users_used}/{usage.users_quota ?? '∞'}.
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}
        <div className="flex gap-3">
          <button type="submit" className="btn btn-secondary">Carregar templates</button>
        </div>
      </form>

      <form onSubmit={handleLoadParties} className="bg-white rounded-xl shadow-sm p-6 border border-slate-200 space-y-4">
        <h2 className="text-lg font-semibold">Partes do documento</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-slate-600">Documento</label>
            <select
              className="w-full border border-slate-300 rounded-md px-3 py-2"
              value={documentFilter}
              onChange={event => setDocumentFilter(event.target.value)}
            >
              <option value="">Selecione um documento</option>
              {filteredDocuments.map(document => (
                <option key={document.id} value={document.id}>
                  {document.name} • {document.area_name ?? document.area_id}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button type="submit" className="btn btn-secondary" disabled={!documentFilter || partiesLoading}>
              {partiesLoading ? 'Carregando...' : 'Carregar partes'}
            </button>
          </div>
        </div>
        {selectedDocument && (
          <div className="text-sm text-slate-500">
            Documento selecionado: <span className="font-medium">{selectedDocument.name}</span> • Status: {selectedDocument.status}
          </div>
        )}
        {documentId && partiesData && (
          <div className="text-sm text-slate-500">
            Partes carregadas: {partiesData.length}
            {partiesData.length > 0 && (
              <span>
                {' '}
                (
                {partiesData
                  .map(party => `${party.full_name} · ${party.role}`)
                  .join(', ')}
                )
              </span>
            )}
          </div>
        )}
        {previewUrl && (
          <div className="mt-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-2">Pré-visualização rápida</h3>
            <iframe
              src={previewUrl}
              title="Pré-visualização do documento"
              className="w-full h-[420px] rounded-md border border-slate-200"
            />
          </div>
        )}
      </form>

      {tenantReady && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
            <h2 className="text-lg font-semibold">Templates</h2>
            {isFetching ? (
              <p className="text-slate-500">Carregando...</p>
            ) : templateList.length === 0 ? (
              <p className="text-slate-500">Nenhum template cadastrado.</p>
            ) : (
              <ul className="space-y-3">
                {templateList.map(template => (
                  <li key={template.id} className="border border-slate-200 rounded-lg px-4 py-3 bg-slate-50">
                    <div className="flex justify-between items-start gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-800">{template.name}</h3>
                        <p className="text-sm text-slate-500">Área: {template.area_name ?? template.area_id}</p>
                        <p className="text-sm text-slate-500">Etapas: {template.steps.length}</p>
                      </div>
                      <span className={template.is_active ? 'status status-active' : 'status status-inactive'}>
                        {template.is_active ? 'Ativo' : 'Inativo'}
                      </span>
                    </div>
                    <div className="mt-3 flex gap-2 flex-wrap">
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => handleToggleTemplate(template)}
                        disabled={toggleMutation.isPending}
                      >
                        {template.is_active ? 'Desativar' : 'Ativar'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => setSelectedTemplate(template)}
                      >
                        Editar
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => handleDuplicateTemplate(template)}
                        disabled={duplicateMutation.isPending}
                      >
                        Duplicar
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">{selectedTemplate ? 'Editar template' : 'Novo template'}</h2>
                {selectedTemplate && <p className="text-sm text-slate-500">Editando {selectedTemplate.name}</p>}
              </div>
              {selectedTemplate && (
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedTemplate(null)}>
                  Criar novo
                </button>
              )}
            </div>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-slate-600">Nome</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={name}
                  onChange={event => setName(event.target.value)}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600">Descrição</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={description}
                  onChange={event => setDescription(event.target.value)}
                  placeholder="Opcional"
                />
              </div>
              <FlowPreview steps={steps} />
              <StepBuilder value={steps} onChange={setSteps} partySuggestions={partySuggestions} />
              <div className="flex gap-3">
                <button type="submit" className="btn btn-primary" disabled={isSaving}>
                  {isSaving ? 'Salvando...' : 'Salvar template'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default TemplatesPage;
