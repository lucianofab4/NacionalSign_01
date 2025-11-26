import { useEffect, useState } from 'react';
import { fetchUsage, fetchInvoices, type Usage, type Invoice } from '../api';
import axios from 'axios';

export default function DashboardPage() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [docStats, setDocStats] = useState<{ signed: number; pending: number; canceled: number; total: number }>({ signed: 0, pending: 0, canceled: 0, total: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [u, i, d] = await Promise.all([
          fetchUsage(),
          fetchInvoices(),
          axios.get('/api/v1/documents'),
        ]);
        setUsage(u);
        setInvoices(i);
        // Contabilizar status dos documentos
        const docs = d.data;
        const stats = {
          signed: docs.filter((doc: any) => doc.status === 'completed').length,
          pending: docs.filter((doc: any) => doc.status === 'in_progress' || doc.status === 'in_review').length,
          canceled: docs.filter((doc: any) => doc.status === 'rejected').length,
          total: docs.length,
        };
        setDocStats(stats);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold mb-4">Dashboard de Relatórios</h1>
      {loading ? (
        <div>Carregando...</div>
      ) : (
        <>
          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200 mb-4">
            <h2 className="text-lg font-semibold mb-2">Painel de Documentos</h2>
            <ul className="text-sm text-slate-700">
              <li>Total: {docStats.total}</li>
              <li>Assinados: {docStats.signed}</li>
              <li>Pendentes de assinatura: {docStats.pending}</li>
              <li>Cancelados/Rejeitados: {docStats.canceled}</li>
            </ul>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200 mb-4">
            <h2 className="text-lg font-semibold mb-2">Resumo de Consumo</h2>
            {usage && (
              <ul className="text-sm text-slate-700">
                <li>Documentos usados: {usage.documents_used} / {usage.documents_quota ?? '∞'}</li>
                <li>Usuários ativos: {usage.users_used} / {usage.users_quota ?? '∞'}</li>
                <li>Período: {new Date(usage.period_start).toLocaleDateString('pt-BR')} - {new Date(usage.period_end).toLocaleDateString('pt-BR')}</li>
              </ul>
            )}
          </div>
          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-200 mb-4">
            <h2 className="text-lg font-semibold mb-2">Faturamento</h2>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-600">
                  <th className="py-2 pr-4">Data</th>
                  <th className="py-2 pr-4">Valor</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Gateway</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr key={inv.id} className="border-t">
                    <td className="py-2 pr-4">{new Date(inv.due_date).toLocaleDateString('pt-BR')}</td>
                    <td className="py-2 pr-4">R$ {(inv.amount_cents / 100).toFixed(2)}</td>
                    <td className="py-2 pr-4">{inv.status}</td>
                    <td className="py-2 pr-4">{inv.gateway}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Auditoria pode ser expandida com fetch de eventos */}
        </>
      )}
    </div>
  );
}
