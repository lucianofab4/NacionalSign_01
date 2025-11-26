import { useEffect, useState } from 'react';
import axios from 'axios';

export default function TenantSettingsPage() {
  const [tenant, setTenant] = useState<any>(null);
  const [form, setForm] = useState({
    name: '',
    theme: '',
    max_users: '',
    max_documents: '',
    custom_logo_url: '',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await axios.get('/api/v1/tenants/me');
        setTenant(res.data);
        setForm({
          name: res.data.name || '',
          theme: res.data.theme || '',
          max_users: res.data.max_users?.toString() || '',
          max_documents: res.data.max_documents?.toString() || '',
          custom_logo_url: res.data.custom_logo_url || '',
        });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleChange = (e: any) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSave = async (e: any) => {
    e.preventDefault();
    if (!tenant) return;
    setSaving(true);
    setMessage('');
    try {
      await axios.patch(`/api/v1/tenants/${tenant.id}`, {
        name: form.name,
        theme: form.theme,
        max_users: form.max_users ? parseInt(form.max_users) : null,
        max_documents: form.max_documents ? parseInt(form.max_documents) : null,
        custom_logo_url: form.custom_logo_url,
      });
      setMessage('Configurações salvas com sucesso!');
    } catch {
      setMessage('Erro ao salvar configurações.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-4">Configurações do Tenant</h1>
      {loading ? (
        <div>Carregando...</div>
      ) : (
        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="block text-sm font-medium">Nome</label>
            <input name="name" value={form.name} onChange={handleChange} className="w-full border rounded px-3 py-2" />
          </div>
          <div>
            <label className="block text-sm font-medium">Tema</label>
            <select name="theme" value={form.theme} onChange={handleChange} className="w-full border rounded px-3 py-2">
              <option value="">Padrão</option>
              <option value="light">Claro</option>
              <option value="dark">Escuro</option>
              <option value="custom">Customizado</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Máx. Usuários</label>
            <input name="max_users" type="number" value={form.max_users} onChange={handleChange} className="w-full border rounded px-3 py-2" />
          </div>
          <div>
            <label className="block text-sm font-medium">Máx. Documentos</label>
            <input name="max_documents" type="number" value={form.max_documents} onChange={handleChange} className="w-full border rounded px-3 py-2" />
          </div>
          <div>
            <label className="block text-sm font-medium">Logo Customizado (URL)</label>
            <input name="custom_logo_url" value={form.custom_logo_url} onChange={handleChange} className="w-full border rounded px-3 py-2" />
          </div>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Salvando...' : 'Salvar'}</button>
          {message && <div className="mt-2 text-sm text-emerald-700">{message}</div>}
        </form>
      )}
    </div>
  );
}
