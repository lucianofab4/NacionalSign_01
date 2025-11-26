import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  fetchDocument,
  fetchDocumentParties,
  fetchAuditEvents,
  fetchSignedArtifacts,
  downloadSignedPackage,
  type DocumentRecord,
  type DocumentParty,
  type AuditEvent,
} from '../api';
import { fetchAsBlob, saveBlob, zipFiles } from '../utils/download';
import PartiesSignatureMethodSelector from '../components/PartiesSignatureMethodSelector';
import toast from 'react-hot-toast';

export default function DocumentSignedView() {
  const { id } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [parties, setParties] = useState<DocumentParty[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    let mounted = true;
    (async () => {
      try {
        const [d, p, e] = await Promise.all([
          fetchDocument(id),
          fetchDocumentParties(id),
          fetchAuditEvents({ documentId: id, eventType: 'document_signed', pageSize: 100 }),
        ]);
        if (!mounted) return;
        setDoc(d);
        setParties(p.sort((a, b) => a.order_index - b.order_index));
        setEvents(e.items);
      } catch (err: any) {
        console.error(err);
        toast.error(err?.message ?? 'Falha ao carregar documento assinado');
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [id]);

  const signedAt = useMemo(() => {
    // tenta pegar do evento de assinatura mais recente
    const last = [...events].sort((a, b) => (a.created_at > b.created_at ? -1 : 1))[0];
    return last?.created_at ?? doc?.updated_at ?? null;
  }, [events, doc]);

  const onDownloadSigned = async () => {
    if (!id) return;
    try {
      setDownloading(true);
      // Tenta baixar pacote zip pronto do backend (melhor performance e confiança)
      try {
        const blob = await downloadSignedPackage(id);
        if (blob && blob.size > 4) {
          saveBlob(blob, `${doc?.name ?? 'documento'}-assinado.zip`);
          return;
        }
      } catch {
        // se o endpoint não existir, tenta fallback via artifacts
      }

      const artifacts = await fetchSignedArtifacts(id);
      if (!artifacts.has_digital_signature) {
        // somente PDF com marca d'água + protocolo
        const pdf = await fetchAsBlob(artifacts.pdf_url);
        saveBlob(pdf, `${doc?.name ?? 'documento'}-assinado.pdf`);
        return;
      }

      // existe pelo menos um .p7s -> zipar client-side
      const files: Record<string, Blob> = {};
      const pdfBlob = await fetchAsBlob(artifacts.pdf_url);
      files[`${doc?.name ?? 'documento'}-assinado.pdf`] = pdfBlob;

      let idx = 1;
      for (const url of artifacts.p7s_urls) {
        const b = await fetchAsBlob(url);
        const nameFromUrl = url.split('/').pop() || `assinatura-${idx}.p7s`;
        files[nameFromUrl] = b;
        idx++;
      }
      const zip = await zipFiles(files);
      saveBlob(zip, `${doc?.name ?? 'documento'}-assinado.zip`);
    } catch (e: any) {
      console.error(e);
      toast.error(e?.message ?? 'Falha ao baixar arquivo assinado');
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return <div className="p-6 text-sm text-gray-500">Carregando…</div>;
  }
  if (!doc) {
    return <div className="p-6 text-sm text-red-600">Documento não encontrado.</div>;
  }

  return (
    <div className="p-6 flex flex-col gap-6">
      {/* Cabeçalho & Ações */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{doc.name}</h1>
          <p className="text-sm text-gray-500">Status: {doc.status}</p>
        </div>
        <div className="flex gap-3">
          <button
            className="px-4 py-2 rounded-xl shadow bg-gray-100 hover:bg-gray-200 text-sm"
            onClick={onDownloadSigned}
            disabled={downloading}
            title="Baixar PDF / ZIP com .p7s conforme tipo de assinatura"
          >
            {downloading ? 'Preparando…' : 'Arquivo Assinado'}
          </button>
        </div>
      </div>

      {/* Detalhes do Documento */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl border p-4">
          <h2 className="font-medium mb-2">Detalhes do Documento</h2>
          <ul className="text-sm space-y-1">
            <li><strong>Nome:</strong> {doc.name}</li>
            <li><strong>Data de criação:</strong> {new Date(doc.created_at).toLocaleString()}</li>
            <li><strong>Data de assinatura:</strong> {signedAt ? new Date(signedAt).toLocaleString() : '—'}</li>
            <li><strong>Status atual:</strong> {doc.status}</li>
            <li><strong>Origem:</strong> {doc.current_version_id ? 'Criado no sistema' : 'Importado'}</li>
            <li><strong>Empresa vinculada:</strong> {/* Preencher quando backend enviar */} — </li>
          </ul>
        </div>

        {/* Eventos / Protocolo (resumo) */}
        <div className="rounded-2xl border p-4">
          <h2 className="font-medium mb-2">Protocolo (resumo)</h2>
          <div className="max-h-60 overflow-auto text-sm space-y-2">
            {events.length === 0 && <div className="text-gray-500">Sem eventos.</div>}
            {events.map(ev => (
              <div key={ev.id} className="border-b pb-2">
                <div className="text-xs text-gray-500">{new Date(ev.created_at).toLocaleString()}</div>
                <div className="font-medium">{ev.event_type}</div>
                {ev.details && <pre className="text-xs bg-gray-50 p-2 rounded">{JSON.stringify(ev.details, null, 2)}</pre>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Informações de Assinaturas */}
      <section className="rounded-2xl border p-4">
        <h2 className="font-medium mb-4">Envolvidos nas Assinaturas</h2>
        <div className="space-y-4">
          {parties.map(p => (
            <div key={p.id} className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 border-b pb-3">
              <div className="text-sm">
                <div className="font-semibold">{p.full_name}</div>
                <div className="text-gray-500">
                  Papel: {p.role} • Empresa: {p.company_name ?? '—'} {p.company_tax_id ? `(${p.company_tax_id})` : ''}
                </div>
                <div className="text-gray-500">
                  Tipo de assinatura: {p.requires_certificate ? 'Digital (A1/A3)' : 'Eletrônica'} • Status: {p.status} • {p.signed_at ? `Assinado em ${new Date(p.signed_at).toLocaleString()}` : '—'}
                </div>
              </div>
              <PartiesSignatureMethodSelector
                documentId={id!}
                party={p}
                onUpdated={(upd) => setParties(prev => prev.map(x => x.id === upd.id ? upd : x))}
              />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
