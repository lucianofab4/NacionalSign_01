import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';

import {
  createArea,
  fetchAreas,
  updateArea,
  type Area,
  type AreaCreatePayload,
  type AreaUpdatePayload,
} from '../../api';

interface SettingsAreasTabProps {
  onAreasChanged?: () => void;
}

interface AreaFormState {
  name: string;
  description: string;
}

const emptyFormState = (): AreaFormState => ({
  name: '',
  description: '',
});

export default function SettingsAreasTab({ onAreasChanged }: SettingsAreasTabProps) {
  const [areas, setAreas] = useState<Area[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState<AreaFormState>(emptyFormState);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<AreaFormState>(emptyFormState);
  const [savingEdit, setSavingEdit] = useState(false);

  useEffect(() => {
    void loadAreas();
  }, []);

  const loadAreas = async () => {
    setLoading(true);
    try {
      const response = await fetchAreas();
      setAreas(response);
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível carregar as áreas da empresa.');
    } finally {
      setLoading(false);
    }
  };

  const sortedAreas = useMemo(
    () => [...areas].sort((a, b) => a.name.localeCompare(b.name, 'pt-BR')),
    [areas],
  );

  const handleCreateArea = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!createForm.name.trim()) {
      toast.error('Informe um nome para a área.');
      return;
    }
    const payload: AreaCreatePayload = {
      name: createForm.name.trim(),
      description: createForm.description.trim() ? createForm.description.trim() : null,
    };
    setCreating(true);
    try {
      const created = await createArea(payload);
      setAreas(prev => [...prev, created]);
      setCreateForm(emptyFormState());
      toast.success('Área criada com sucesso.');
      onAreasChanged?.();
    } catch (error) {
      console.error(error);
      toast.error('Erro ao criar a área.');
    } finally {
      setCreating(false);
    }
  };

  const beginEdit = (area: Area) => {
    setEditingId(area.id);
    setEditForm({
      name: area.name,
      description: area.description ?? '',
    });
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditForm(emptyFormState());
  };

  const handleSaveEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingId) return;
    if (!editForm.name.trim()) {
      toast.error('Informe um nome para a área.');
      return;
    }
    const payload: AreaUpdatePayload = {
      name: editForm.name.trim(),
      description: editForm.description.trim() ? editForm.description.trim() : null,
    };
    setSavingEdit(true);
    try {
      const updated = await updateArea(editingId, payload);
      setAreas(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      toast.success('Área atualizada.');
      handleCancelEdit();
      onAreasChanged?.();
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível atualizar a área.');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleToggleStatus = async (area: Area) => {
    try {
      const updated = await updateArea(area.id, { is_active: !area.is_active });
      setAreas(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      toast.success(updated.is_active ? 'Área reativada.' : 'Área desativada.');
      onAreasChanged?.();
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível alterar o status da área.');
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-slate-800">Cadastrar nova área</h2>
          <p className="text-sm text-slate-500">
            Estruture a organização por áreas para controlar templates, documentos e usuários que cada equipe pode acessar.
          </p>
        </div>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={handleCreateArea}>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Nome da área
            <input
              className="mt-1 rounded border px-3 py-2"
              value={createForm.name}
              onChange={event => setCreateForm(prev => ({ ...prev, name: event.target.value }))}
              placeholder="Ex.: Jurídico"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600 md:col-span-1">
            Descrição (opcional)
            <input
              className="mt-1 rounded border px-3 py-2"
              value={createForm.description}
              onChange={event => setCreateForm(prev => ({ ...prev, description: event.target.value }))}
              placeholder="Resumo do que a equipe faz"
            />
          </label>
          <div className="md:col-span-2 flex justify-end">
            <button
              type="submit"
              className="inline-flex items-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-300"
              disabled={creating}
            >
              {creating ? 'Salvando...' : 'Criar área'}
            </button>
          </div>
        </form>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">Áreas cadastradas</h2>
            <p className="text-sm text-slate-500">
              Ative ou desative áreas conforme a estrutura da empresa mudar. Usuários, templates e documentos herdam as permissões da área vinculada.
            </p>
          </div>
          <button
            className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
            onClick={() => void loadAreas()}
            type="button"
          >
            Atualizar lista
          </button>
        </div>

        {loading ? (
          <p className="text-sm text-slate-500">Carregando áreas...</p>
        ) : sortedAreas.length === 0 ? (
          <p className="text-sm text-slate-500">Nenhuma área cadastrada ainda.</p>
        ) : (
          <div className="space-y-4">
            {sortedAreas.map(area =>
              editingId === area.id ? (
                <form
                  key={area.id}
                  className="rounded-lg border border-slate-200 bg-slate-50 p-4 shadow-inner"
                  onSubmit={handleSaveEdit}
                >
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-slate-700">Editar área</h3>
                    <span className={`text-xs font-semibold ${area.is_active ? 'text-emerald-600' : 'text-amber-600'}`}>
                      {area.is_active ? 'Ativa' : 'Inativa'}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <label className="flex flex-col text-sm font-medium text-slate-600">
                      Nome da área
                      <input
                        className="mt-1 rounded border px-3 py-2"
                        value={editForm.name}
                        onChange={event => setEditForm(prev => ({ ...prev, name: event.target.value }))}
                      />
                    </label>
                    <label className="flex flex-col text-sm font-medium text-slate-600 md:col-span-1">
                      Descrição
                      <input
                        className="mt-1 rounded border px-3 py-2"
                        value={editForm.description}
                        onChange={event => setEditForm(prev => ({ ...prev, description: event.target.value }))}
                      />
                    </label>
                  </div>
                  <div className="mt-4 flex justify-end gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
                      onClick={handleCancelEdit}
                    >
                      Cancelar
                    </button>
                    <button
                      type="submit"
                      className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-300"
                      disabled={savingEdit}
                    >
                      {savingEdit ? 'Salvando...' : 'Salvar alterações'}
                    </button>
                  </div>
                </form>
              ) : (
                <div
                  key={area.id}
                  className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-base font-semibold text-slate-800">{area.name}</h3>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                          area.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        {area.is_active ? 'Ativa' : 'Inativa'}
                      </span>
                    </div>
                    {area.description ? (
                      <p className="text-sm text-slate-500">{area.description}</p>
                    ) : (
                      <p className="text-sm text-slate-400">Sem descrição cadastrada.</p>
                    )}
                    <p className="mt-2 text-xs text-slate-400">
                      ID: {area.id.slice(0, 8)} • Atualizado em{' '}
                      {area.updated_at
                        ? new Date(area.updated_at).toLocaleString('pt-BR')
                        : new Date(area.created_at ?? new Date().toISOString()).toLocaleString('pt-BR')}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2 md:flex-row md:items-center">
                    <button
                      className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100"
                      onClick={() => beginEdit(area)}
                      type="button"
                    >
                      Editar
                    </button>
                    <button
                      className={`rounded-md px-4 py-2 text-sm font-semibold text-white shadow transition ${
                        area.is_active ? 'bg-amber-500 hover:bg-amber-400' : 'bg-emerald-600 hover:bg-emerald-500'
                      }`}
                      onClick={() => void handleToggleStatus(area)}
                      type="button"
                    >
                      {area.is_active ? 'Desativar' : 'Reativar'}
                    </button>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}

