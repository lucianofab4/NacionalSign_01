import { useState } from "react";
import toast from "react-hot-toast";
import { isAxiosError } from "axios";

import { api, createDocumentRecord, uploadDocumentVersion, type DocumentGroupUploadResponse } from "../api";

interface DocumentCreatePageProps {
  tenantId: string;
  areaId?: string;
  onFinished: (documentId?: string) => void;
}

export default function DocumentCreatePage({ areaId, onFinished }: DocumentCreatePageProps) {
  const areaReady = Boolean(areaId);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [separateDocuments, setSeparateDocuments] = useState(false);
  const [saving, setSaving] = useState(false);
  const MAX_UNIFIED_FILES = 10;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!areaReady) {
      toast.error("Selecione uma area antes de criar um documento.");
      return;
    }
    if (!name.trim()) {
      toast.error("Informe um nome para o documento.");
      return;
    }
    if (files.length === 0) {
      toast.error("Selecione ao menos um arquivo para upload.");
      return;
    }

    setSaving(true);
    try {
      if (separateDocuments) {
        const form = new FormData();
        form.append("title", name.trim());
        form.append("area_id", areaId as string);
        form.append("separate_documents", "true");
        files.forEach(file => form.append("files", file));
        const response = await api.post("/api/v1/documents/groups", form);
        const responseData = response.data as DocumentGroupUploadResponse;
        toast.success("Grupo de documentos criado. Configure o fluxo em seguida.");
        setName("");
        setFiles([]);
        setSeparateDocuments(false);
        const groupId = responseData?.group_id ?? responseData?.group?.id;
        onFinished(groupId || undefined);
        return;
      }

      const doc = await createDocumentRecord({ name: name.trim(), area_id: areaId as string });
      if (files.length > 0) {
        await uploadDocumentVersion(doc.id, files);
      } else {
        throw new Error("Nenhum arquivo selecionado.");
      }
      toast.success("Documento criado. Configure o fluxo a seguir.");
      setName("");
      setFiles([]);
      onFinished(doc.id);
    } catch (error) {
      console.error(error);
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (detail) {
          toast.error(typeof detail === "string" ? detail : JSON.stringify(detail));
        } else {
          toast.error("Falha ao criar ou enviar o documento.");
        }
      } else {
        toast.error("Falha ao criar ou enviar o documento.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <h1 className="text-2xl font-semibold text-slate-800">Enviar documento para assinatura</h1>
        <p className="text-sm text-slate-500">
          Preencha as informações abaixo para registrar o arquivo na área selecionada.
        </p>
      </div>
      {!areaReady && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Selecione uma área para visualizar e criar documentos.
        </div>
      )}
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col text-sm font-medium text-slate-600">
          Nome do documento
          <input
            type="text"
            className="mt-1 border rounded px-3 py-2"
            placeholder="Ex.: Contrato de Prestacao"
            value={name}
            onChange={event => setName(event.target.value)}
          />
        </label>
        <label className="flex flex-col text-sm font-medium text-slate-600">
          Arquivos
          <input
            type="file"
            className="mt-1 border rounded px-3 py-2"
            multiple
            onChange={event => {
              const selected = Array.from(event.target.files ?? []);
              if (selected.length === 0) {
                return;
              }
              setFiles(prev => {
                const combined = [...prev, ...selected];
                if (!separateDocuments && combined.length > MAX_UNIFIED_FILES) {
                  toast.error(`Máximo ${MAX_UNIFIED_FILES} arquivos para unificação.`);
                  return prev;
                }
                return combined;
              });
              // Libera o input para permitir selecionar o mesmo arquivo novamente depois.
              event.target.value = "";
            }}
            accept=".pdf,.docx,.png,.jpg,.jpeg,.gif,.webp,.tiff"
          />
          {files.length > 0 && (
            <span className="mt-2 text-xs text-slate-500">
              {files.length} arquivo{files.length > 1 ? "s" : ""} selecionado{files.length > 1 ? "s" : ""}.
            </span>
          )}
        </label>
        <label className="flex items-center gap-3 rounded border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={separateDocuments}
            onChange={event => {
              const nextValue = event.target.checked;
              if (!nextValue && files.length > MAX_UNIFIED_FILES) {
                toast.error(`Máximo ${MAX_UNIFIED_FILES} arquivos para unificação.`);
                setFiles(prev => prev.slice(0, MAX_UNIFIED_FILES));
              }
              setSeparateDocuments(nextValue);
            }}
          />
          <div>
            <p className="font-medium text-slate-700">Criar documentos independentes (lote)</p>
            <p className="text-xs text-slate-500">
              Cada arquivo vira um documento separado, com protocolo e assinatura individuais. Todos ficam vinculados
              ao mesmo fluxo.
            </p>
          </div>
        </label>
        <div className="flex items-center justify-between">
          <small className="text-slate-500">
            {separateDocuments
              ? "Arquivos DOCX e imagens serão convertidos em PDFs individuais. Cada documento terá protocolo próprio, mas compartilhará o mesmo fluxo."
              : "Arquivos DOCX e imagens serão convertidos automaticamente para PDF padrão. Você pode enviar vários arquivos; eles serão unificados em um único PDF antes da assinatura."}
          </small>
          <button type="submit" className="btn btn-primary" disabled={saving || files.length === 0 || !areaReady}>
            {saving ? "Processando..." : "Enviar"}
          </button>
        </div>
      </form>
      <div className="flex justify-end">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onFinished()}>
          Voltar para documentos
        </button>
      </div>
    </div>
  );
}
