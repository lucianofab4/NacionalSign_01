import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';

import {
  createUserAccount,
  fetchAreas,
  fetchUsers,
  updateUserAccount,
  sendUserCredentials,
  type Area,
  type UserSummary,
  type UserUpdatePayload,
} from '../api';

type ProfileOption = 'admin' | 'area_manager' | 'user';

interface CreateFormState {
  full_name: string;
  email: string;
  cpf: string;
  phone_number: string;
  password: string;
  profile: ProfileOption;
  default_area_id: string | null;
}

const defaultCreateForm = (profile: ProfileOption = 'user', areaId: string | null = null): CreateFormState => ({
  full_name: '',
  email: '',
  cpf: '',
  phone_number: '',
  password: '',
  profile,
  default_area_id: areaId,
});

interface EditFormState {
  full_name: string;
  phone_number: string;
  password: string;
  profile: ProfileOption;
  default_area_id: string | null;
}

interface UsersPageProps {
  currentProfile: ProfileOption | string;
  currentAreaId?: string | null;
}

export default function UsersPage({ currentProfile, currentAreaId }: UsersPageProps) {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const initialProfile: ProfileOption = currentProfile === 'admin' ? 'admin' : currentProfile === 'area_manager' ? 'area_manager' : 'user';
  const [form, setForm] = useState<CreateFormState>(defaultCreateForm(initialProfile, currentAreaId ?? null));
  const [sendingUserId, setSendingUserId] = useState<string | null>(null);
  const [editingUser, setEditingUser] = useState<UserSummary | null>(null);
  const [editForm, setEditForm] = useState<EditFormState | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [togglingUserId, setTogglingUserId] = useState<string | null>(null);

  const isAdmin = useMemo(() => currentProfile === 'admin' || currentProfile === 'owner', [currentProfile]);
  const isAreaManager = useMemo(() => currentProfile === 'area_manager', [currentProfile]);

  useEffect(() => {
    void loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [areasResponse, usersResponse] = await Promise.all([fetchAreas(), fetchUsers()]);
      setAreas(areasResponse);
      setUsers(usersResponse);
    } catch (error) {
      console.error(error);
      toast.error('Falha ao carregar usuários.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setForm(prev => ({
      ...prev,
      profile: isAdmin ? prev.profile : 'user',
      default_area_id: isAdmin ? prev.default_area_id : (currentAreaId ?? null),
    }));
  }, [isAdmin, currentAreaId]);

  const resolveProfileOption = (value: string): ProfileOption => {
    if (value === 'admin' || value === 'area_manager') {
      return value;
    }
    return 'user';
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.full_name.trim() || !form.email.trim() || !form.password.trim()) {
      toast.error('Preencha todos os campos obrigatórios.');
      return;
    }
    if (!isAdmin && !currentAreaId) {
      toast.error('Defina uma área padrão antes de cadastrar usuários.');
      return;
    }
    setCreating(true);
    try {
      const normalizedCpf = form.cpf.trim();
      const normalizedPhone = form.phone_number.trim();
      const payload = {
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        cpf: normalizedCpf || undefined,
        phone_number: normalizedPhone || undefined,
        password: form.password,
        profile: isAdmin ? form.profile : 'user',
        default_area_id: isAdmin ? form.default_area_id : currentAreaId ?? null,
      };
      await createUserAccount(payload);
      toast.success('Usuário cadastrado com sucesso.');
      setForm(defaultCreateForm(isAdmin ? form.profile : 'user', isAdmin ? form.default_area_id : (currentAreaId ?? null)));
      void loadAll();
    } catch (error) {
      console.error(error);
      toast.error('Erro ao criar usuário.');
    } finally {
      setCreating(false);
    }
  };

  const resolveAreaName = (areaId: string | null) => {
    if (!areaId) return '-';
    const area = areas.find(item => item.id === areaId);
    return area ? area.name : 'Área removida';
  };

  const startEditUser = (user: UserSummary) => {
    setEditingUser(user);
    setEditForm({
      full_name: user.full_name,
      phone_number: user.phone_number ?? '',
      password: '',
      profile: resolveProfileOption(user.profile),
      default_area_id: user.default_area_id ?? null,
    });
  };

  const cancelEditUser = () => {
    setEditingUser(null);
    setEditForm(null);
    setSavingEdit(false);
  };

  const handleEditSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser || !editForm) {
      return;
    }
    if (!editForm.full_name.trim()) {
      toast.error('O nome é obrigatório.');
      return;
    }
    setSavingEdit(true);
    try {
      const normalizedPhone = editForm.phone_number.trim();
      const payload: UserUpdatePayload = {
        full_name: editForm.full_name.trim(),
        phone_number: normalizedPhone ? normalizedPhone : null,
        default_area_id: isAdmin ? editForm.default_area_id : editingUser.default_area_id ?? currentAreaId ?? null,
      };
      if (editForm.password.trim()) {
        payload.password = editForm.password;
      }
      if (isAdmin) {
        payload.profile = editForm.profile;
      }
      await updateUserAccount(editingUser.id, payload);
      toast.success('Usuário atualizado com sucesso.');
      cancelEditUser();
      void loadAll();
    } catch (error) {
      console.error(error);
      toast.error('Erro ao atualizar usuário.');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleToggleActive = async (user: UserSummary) => {
    setTogglingUserId(user.id);
    try {
      await updateUserAccount(user.id, { is_active: !user.is_active });
      toast.success(user.is_active ? 'Usuário desativado.' : 'Usuário reativado.');
      void loadAll();
    } catch (error) {
      console.error(error);
      toast.error('Não foi possível alterar o status do usuário.');
    } finally {
      setTogglingUserId(null);
    }
  };

  
  const handleSendCredentials = async (user: UserSummary) => {
    if (!user.email) {
      toast.error('Usurio sem e-mail cadastrado.');
      return;
    }
    setSendingUserId(user.id);
    try {
      const tempPassword =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID().replace(/-/g, '').slice(0, 10)
          : Math.random().toString(36).slice(2, 10);
      await sendUserCredentials({
        user_id: user.id,
        email: user.email,
        full_name: user.full_name,
        username: user.email,
        temp_password: tempPassword,
      });
      toast.success(`Credenciais enviadas para ${user.email}.`);
    } catch (error) {
      console.error(error);
      toast.error('Falha ao enviar credenciais.');
    } finally {
      setSendingUserId(null);
    }
  };

  const sortedUsers = useMemo(
    () => [...users].sort((a, b) => a.full_name.localeCompare(b.full_name, 'pt-BR')),
    [users],
  );

  return (
    <div className="space-y-8">
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
        <h1 className="text-2xl font-semibold text-slate-800 mb-4">Usuários internos</h1>
        <p className="text-sm text-slate-500 mb-6">
          Cadastre pessoas que podem enviar documentos, acompanhar fluxos e assinar pela sua organização.
          Vincule cada usuário a uma área para restringir o acesso somente aos documentos relevantes.
        </p>

        <form className="grid grid-cols-1 md:grid-cols-2 gap-4" onSubmit={handleCreate}>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Nome completo
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.full_name}
              onChange={event => setForm(prev => ({ ...prev, full_name: event.target.value }))}
              placeholder="Ex.: Maria Pereira"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            E-mail corporativo
            <input
              className="mt-1 border rounded px-3 py-2"
              type="email"
              value={form.email}
              onChange={event => setForm(prev => ({ ...prev, email: event.target.value }))}
              placeholder="usuario@empresa.com"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            CPF (opcional)
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.cpf}
              onChange={event => setForm(prev => ({ ...prev, cpf: event.target.value }))}
              placeholder="Somente números"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Telefone celular (opcional)
            <input
              className="mt-1 border rounded px-3 py-2"
              value={form.phone_number}
              onChange={event => setForm(prev => ({ ...prev, phone_number: event.target.value }))}
              placeholder="+55 11 90000-0000"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Senha inicial
            <input
              className="mt-1 border rounded px-3 py-2"
              type="password"
              value={form.password}
              onChange={event => setForm(prev => ({ ...prev, password: event.target.value }))}
              placeholder="Defina uma senha temporária"
            />
          </label>
          <label className="flex flex-col text-sm font-medium text-slate-600">
            Área
            <select
              className="mt-1 border rounded px-3 py-2"
              value={form.default_area_id ?? ''}
              onChange={event => setForm(prev => ({ ...prev, default_area_id: event.target.value || null }))}
              disabled={isAreaManager && !!currentAreaId}
            >
              <option value="">Selecionar área</option>
              {areas.map(area => (
                <option key={area.id} value={area.id}>
                  {area.name}
                </option>
              ))}
            </select>
          </label>
          {isAdmin && (
            <label className="flex flex-col text-sm font-medium text-slate-600">
              Perfil
              <select
                className="mt-1 border rounded px-3 py-2"
                value={form.profile}
                onChange={event => setForm(prev => ({ ...prev, profile: event.target.value as ProfileOption }))}
              >
                <option value="user">Operacional</option>
                <option value="area_manager">Gestor de área</option>
                <option value="admin">Administrador</option>
              </select>
            </label>
          )}
          <div className="md:col-span-2 flex justify-end">
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? 'Cadastrando...' : 'Cadastrar usuário'}
            </button>
          </div>
        </form>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Equipe cadastrada</h2>
          {loading && <span className="text-xs text-slate-500">Carregando...</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Nome</th>
                <th className="px-4 py-3 text-left">Área</th>
                <th className="px-4 py-3 text-left">Perfil</th>
                <th className="px-4 py-3 text-left">Email</th>
                <th className="px-4 py-3 text-left">Telefone</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">šltimo acesso</th>
                <th className="px-4 py-3 text-left">Ações</th>
              </tr>
            </thead>
            <tbody>
              {sortedUsers.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-500" colSpan={8}>
                    Nenhum usuário cadastrado até o momento.
                  </td>
                </tr>
              ) : (
                sortedUsers.map(user => (
                  <tr key={user.id} className="border-t border-slate-100">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{user.full_name}</div>
                      <div className="text-xs text-slate-500">{user.cpf}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{resolveAreaName(user.default_area_id)}</td>
                    <td className="px-4 py-3 capitalize text-slate-600">{user.profile.replace('_', ' ')}</td>
                    <td className="px-4 py-3">{user.email}</td>
                    <td className="px-4 py-3">{user.phone_number ?? '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${user.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-600'}`}>
                        {user.is_active ? 'Ativo' : 'Inativo'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {user.last_login_at ? new Date(user.last_login_at).toLocaleString('pt-BR') : 'Nunca'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          className="btn btn-ghost btn-xs"
                          onClick={() => handleToggleActive(user)}
                          disabled={( ['admin', 'owner'].includes(user.profile) && !isAdmin) || togglingUserId === user.id}
                        >
                          {togglingUserId === user.id ? 'Atualizando...' : user.is_active ? 'Desativar' : 'Reativar'}
                        </button>
                        <button
                          className="btn btn-outline btn-xs"
                          onClick={() => startEditUser(user)}
                        >
                          Editar
                        </button>
                        <button
                          className="btn btn-secondary btn-xs"
                          onClick={() => handleSendCredentials(user)}
                          disabled={sendingUserId === user.id}
                        >
                          {sendingUserId === user.id ? 'Enviando...' : 'Enviar credenciais'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      {editingUser && editForm && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-700">Editar usuário</h2>
              <p className="text-sm text-slate-500">{editingUser.email}</p>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={cancelEditUser}>
              Cancelar
            </button>
          </div>
          <form className="grid grid-cols-1 md:grid-cols-2 gap-4 p-6" onSubmit={handleEditSubmit}>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              Nome completo
              <input
                className="mt-1 border rounded px-3 py-2"
                value={editForm.full_name}
                onChange={event => setEditForm(prev => (prev ? { ...prev, full_name: event.target.value } : prev))}
                placeholder="Nome do usuário"
              />
            </label>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              E-mail (somente leitura)
              <input className="mt-1 border rounded px-3 py-2 bg-slate-100 text-slate-500" value={editingUser.email} disabled />
            </label>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              Telefone celular
              <input
                className="mt-1 border rounded px-3 py-2"
                value={editForm.phone_number}
                onChange={event => setEditForm(prev => (prev ? { ...prev, phone_number: event.target.value } : prev))}
                placeholder="Opcional"
              />
            </label>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              CPF (somente leitura)
              <input className="mt-1 border rounded px-3 py-2 bg-slate-100 text-slate-500" value={editingUser.cpf ?? ''} disabled />
            </label>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              Nova senha
              <input
                className="mt-1 border rounded px-3 py-2"
                type="password"
                value={editForm.password}
                onChange={event => setEditForm(prev => (prev ? { ...prev, password: event.target.value } : prev))}
                placeholder="Deixe em branco para manter"
              />
            </label>
            <label className="flex flex-col text-sm font-medium text-slate-600">
              Área
              <select
                className="mt-1 border rounded px-3 py-2"
                value={editForm.default_area_id ?? ''}
                onChange={event => setEditForm(prev => (prev ? { ...prev, default_area_id: event.target.value || null } : prev))}
                disabled={!isAdmin}
              >
                <option value="">Selecionar área</option>
                {areas.map(area => (
                  <option key={area.id} value={area.id}>
                    {area.name}
                  </option>
                ))}
              </select>
            </label>
            {isAdmin && (
              <label className="flex flex-col text-sm font-medium text-slate-600">
                Perfil
                <select
                  className="mt-1 border rounded px-3 py-2"
                  value={editForm.profile}
                  onChange={event =>
                    setEditForm(prev => (prev ? { ...prev, profile: event.target.value as ProfileOption } : prev))
                  }
                >
                  <option value="user">Operacional</option>
                  <option value="area_manager">Gestor de área</option>
                  <option value="admin">Administrador</option>
                </select>
              </label>
            )}
            <div className="md:col-span-2 flex justify-end gap-3">
              <button className="btn btn-ghost" type="button" onClick={cancelEditUser}>
                Fechar
              </button>
              <button className="btn btn-primary" type="submit" disabled={savingEdit}>
                {savingEdit ? 'Salvando...' : 'Salvar alterações'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}



