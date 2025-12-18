import { useCallback, useEffect, useMemo, useState } from "react";

import { useNavigate, useParams } from "react-router-dom";

import toast from "react-hot-toast";



import {

  api,

  fetchDocumentDetail,

  fetchDocumentVersion,

  fetchDocumentSignatures,

  fetchSignedArtifacts,

  downloadSignedPackage,

  type DocumentRecord,

  type DocumentVersion,

  type DocumentSignature,

} from "../api";

import { fetchAsBlob, saveBlob, zipFiles } from "../utils/download";

import { resolveApiBaseUrl } from "../utils/env";



const formatDateTime = (value: string | null | undefined) => {

  if (!value) return "-";

  try {

    return new Intl.DateTimeFormat("pt-BR", {

      dateStyle: "short",

      timeStyle: "short",

    }).format(new Date(value));

  } catch {

    return value;

  }

};



export default function DocumentDetailPage() {

  const { id } = useParams<{ id: string }>();

  const navigate = useNavigate();



  const [documentRecord, setDocumentRecord] = useState<DocumentRecord | null>(null);

  const [version, setVersion] = useState<DocumentVersion | null>(null);

  const [signatures, setSignatures] = useState<DocumentSignature[]>([]);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  const [downloadingSignedFile, setDownloadingSignedFile] = useState(false);



  const apiBaseUrl = resolveApiBaseUrl();



  const resolveApiUrl = useCallback(

    (path?: string | null) => {

      if (!path) return null;

      if (/^https?:\/\//i.test(path)) return path;

      if (!apiBaseUrl) return path;

      return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;

    },

    [apiBaseUrl],

  );



  const downloadSignedAsset = useCallback(

    async (url: string | null) => {

      if (!url) return;

      try {

        const cleanUrl = url.startsWith(apiBaseUrl) ? url.replace(apiBaseUrl, "") : url;

        const response = await api.get(cleanUrl, { responseType: "blob" });

        const headers = response.headers ?? {};

        const contentType =

          (headers["content-type"] as string | undefined) ||

          (headers["Content-Type"] as string | undefined) ||

          "application/pdf";

        const disposition =

          (headers["content-disposition"] as string | undefined) ||

          (headers["Content-Disposition"] as string | undefined);

        const extractFilename = (header?: string): string | null => {

          if (!header) return null;

          const utfMatch = header.match(/filename\*=UTF-8''([^;]+)/i);

          if (utfMatch && utfMatch[1]) {

            try {

              return decodeURIComponent(utfMatch[1]);

            } catch {

              return utfMatch[1];

            }

          }

          const simpleMatch = header.match(/filename="?([^";]+)"?/i);

          if (simpleMatch && simpleMatch[1]) {

            return simpleMatch[1];

          }

          return null;

        };

        const suggestedName =

          extractFilename(disposition) ||

          (contentType.includes("zip") ? "documento-assinado.zip" : "documento-assinado.pdf");

        const blob =

          response.data instanceof Blob ? response.data : new Blob([response.data], { type: contentType });

        const objectUrl = window.URL.createObjectURL(blob);

        const anchor = document.createElement("a");

        anchor.href = objectUrl;

        anchor.download = suggestedName.replace(/[\r\n"]/g, "");

        document.body.appendChild(anchor);

        anchor.click();

        document.body.removeChild(anchor);

        window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 2000);

      } catch (err) {

        console.error(err);

        toast.error("Erro ao baixar o arquivo assinado. Verifique sua autenticação.");
      }

    },

    [apiBaseUrl],

  );





  useEffect(() => {

    if (!id) {
      setError("Documento não encontrado.");
      setLoading(false);

      return;

    }

    setLoading(true);

    setError(null);

    (async () => {

      try {

        const doc = await fetchDocumentDetail(id);

        setDocumentRecord(doc);



        if (doc.current_version_id) {

          const versionData = await fetchDocumentVersion(doc.id, doc.current_version_id);

          setVersion(versionData);

        } else {

          setVersion(null);

        }



        const signatureList = await fetchDocumentSignatures(doc.id);

        setSignatures(signatureList);

      } catch (err) {

        console.error(err);

        const message =
          err instanceof Error ? err.message : "Não foi possível carregar as informações do documento.";
        setError(message);

      } finally {

        setLoading(false);

      }

    })();

  }, [id]);



  const downloadPath = useMemo(

    () => version?.icp_report_url ?? version?.icp_public_report_url ?? null,

    [version],

  );

  const finalDownloadUrl = useMemo(() => resolveApiUrl(downloadPath), [downloadPath, resolveApiUrl]);

  const hasDetachedSignatures = Boolean(version?.icp_signature_bundle_available);

  const hasDigitalSignatures = useMemo(

    () => signatures.some(signature => (signature.signature_method ?? "").toLowerCase() === "digital"),

    [signatures],

  );

  const requiresZipDownload = hasDetachedSignatures || hasDigitalSignatures;

  const downloadButtonDisabled = downloadingSignedFile || !documentRecord;

  const safeDocumentName = useMemo(

    () => (documentRecord?.name ?? "documento").replace(/[\\/:*?"<>|]+/g, "-"),

    [documentRecord?.name],

  );



  const handleDownloadSignedFile = useCallback(async () => {

    if (!documentRecord) return;

    setDownloadingSignedFile(true);

    const baseFileName = `${safeDocumentName}-assinado`;

    try {

      const docId = documentRecord.id;

      try {

        const blob = await downloadSignedPackage(docId);

        if (blob && blob.size > 4) {

          saveBlob(blob, `${baseFileName}.zip`);

          return;

        }

      } catch (err) {
        console.debug("Pacote ZIP não disponível, usando fallback.", err);
      }


      const artifacts = await fetchSignedArtifacts(docId);

      const pdfUrl = artifacts.pdf_url ?? finalDownloadUrl;

      if (!pdfUrl) {
        throw new Error("O arquivo assinado ainda não está disponível.");
      }

      const pdfBlob = await fetchAsBlob(pdfUrl);

      const shouldZipArtifacts = artifacts.has_digital_signature || requiresZipDownload || hasDigitalSignatures;

      if (!shouldZipArtifacts) {

        if (finalDownloadUrl) {

          await downloadSignedAsset(finalDownloadUrl);

        } else {

          saveBlob(pdfBlob, `${baseFileName}.pdf`);

        }

        return;

      }



      const files: Record<string, Blob> = {

        [`${baseFileName}.pdf`]: pdfBlob,

      };

      const bundleUrls = artifacts.p7s_urls ?? [];

      let index = 1;

      for (const url of bundleUrls) {

        try {

          const blob = await fetchAsBlob(url);

          const fileName = url.split("/").pop() || `assinatura-${index}.p7s`;

          files[fileName] = blob;

          index += 1;

        } catch (err) {

          console.error("Falha ao baixar P7S", err);

        }

      }



      const zipBlob = await zipFiles(files);

      saveBlob(zipBlob, `${baseFileName}.zip`);

    } catch (err) {

      console.error(err);

      toast.error("Erro ao baixar o arquivo assinado. Tente novamente.");

    } finally {

      setDownloadingSignedFile(false);

    }

  }, [

    documentRecord,

    finalDownloadUrl,

    requiresZipDownload,

    hasDigitalSignatures,

    downloadSignedAsset,

    safeDocumentName,

  ]);



  const createdAt = formatDateTime(documentRecord?.created_at);

  const signedAt = formatDateTime(version?.icp_timestamp ?? documentRecord?.updated_at);

  const statusLabel = (documentRecord?.status ?? "-").replace(/_/g, " ");

  const originLabel =

    version && version.storage_path && !version.storage_path.startsWith("documents/") ? "Importado" : "Sistema";

  const companyReference =
    signatures.find(signature => signature.company_name)?.company_name ?? "Não informado";


  if (loading) {

    return <div className="p-8 text-sm text-slate-500">Carregando informações do documento...</div>;
  }



  if (error) {

    return (

      <div className="max-w-3xl mx-auto px-6 py-10 space-y-4">

        <button

          type="button"

          className="text-sm font-medium text-blue-600 hover:underline"

          onClick={() => navigate("/documentos")}

        >

          ← Voltar

        </button>

        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-700">

          {error}

        </div>

      </div>

    );

  }



  if (!documentRecord) {

    return (

      <div className="max-w-3xl mx-auto px-6 py-10 space-y-4">

        <button

          type="button"

          className="text-sm font-medium text-blue-600 hover:underline"

          onClick={() => navigate("/documentos")}

        >

          ← Voltar

        </button>

        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-700">

          Documento não encontrado.

        </div>

      </div>

    );

  }



  return (

    <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">

      <button

        type="button"

        className="text-sm font-medium text-blue-600 hover:underline"

        onClick={() => navigate("/documentos")}

      >

        ← Voltar para documentos

      </button>



      <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white px-6 py-5 shadow-sm md:flex-row md:items-center md:justify-between">

        <div>

          <h1 className="text-2xl font-semibold text-slate-800">{documentRecord.name}</h1>

          <p className="text-sm text-slate-500">Status: {statusLabel}</p>

        </div>

        <button

          type="button"

          className="btn btn-primary btn-sm"

          onClick={() => void handleDownloadSignedFile()}

          disabled={downloadButtonDisabled}

        >

          {downloadingSignedFile

            ? "Preparando..."

            : requiresZipDownload

              ? "Arquivo assinado (.zip)"

              : "Arquivo assinado (PDF)"}

        </button>

      </div>



      <div className="grid gap-4 md:grid-cols-2">

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">

          <p className="text-xs uppercase text-slate-500">Criado em</p>

          <p className="text-sm font-medium text-slate-700">{createdAt}</p>

        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">

          <p className="text-xs uppercase text-slate-500">Assinado em</p>

          <p className="text-sm font-medium text-slate-700">{signedAt}</p>

        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">

          <p className="text-xs uppercase text-slate-500">Origem</p>

          <p className="text-sm font-medium text-slate-700">{originLabel}</p>

        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">

          <p className="text-xs uppercase text-slate-500">Empresa vinculada</p>

          <p className="text-sm font-medium text-slate-700">{companyReference}</p>

        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">

          <p className="text-xs uppercase text-slate-500">Versão atual</p>
          <p className="text-sm font-medium text-slate-700">
            {version?.original_filename ?? "Não disponível"}
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs uppercase text-slate-500">Carimbo ICP-Brasil</p>
          <p className="text-sm font-medium text-slate-700">
            {version?.icp_authority ? `${version.icp_authority}` : "Não disponível"}
          </p>

        </div>

      </div>



      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">

        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">

          <div>

            <h2 className="text-lg font-semibold text-slate-700">Informações de assinatura</h2>
            <p className="text-sm text-slate-500">
              Veja quem assinou, o tipo de assinatura utilizado e o vínculo com a empresa.
            </p>
          </div>

          <div className="text-sm text-slate-500">

            {signatures.length} {signatures.length === 1 ? "assinatura registrada" : "assinaturas registradas"}

          </div>

        </div>

        {signatures.length === 0 ? (

          <div className="px-6 py-5 text-sm text-slate-500">

            Nenhuma assinatura registrada para este documento ainda.

          </div>

        ) : (

          <div className="overflow-x-auto">

            <table className="min-w-full divide-y divide-slate-200 text-sm">

              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wider text-slate-500">

                <tr>

                  <th className="px-4 py-3">Participante</th>

                  <th className="px-4 py-3">Papel</th>

                  <th className="px-4 py-3">Assinatura</th>

                  <th className="px-4 py-3">Empresa</th>

                  <th className="px-4 py-3">Assinado em</th>

                </tr>

              </thead>

              <tbody className="divide-y divide-slate-100 bg-white">

                {signatures

                  .slice()

                  .sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0))

                  .map((signature, index) => {

                    const method = (signature.signature_method ?? "electronic").toLowerCase();

                    const methodLabel = method === "digital" ? "Certificado digital" : "Assinatura eletrônica";
                    const typeLabel = signature.signature_type

                      ? signature.signature_type.replace(/_/g, " ")

                      : methodLabel;

                    return (

                      <tr key={signature.party_id ?? `${signature.full_name ?? "signature"}-${index}`}>

                        <td className="px-4 py-3">

                          <div className="font-medium text-slate-800">

                            {signature.full_name ?? "Participante"}

                          </div>

                          <div className="text-xs text-slate-500">{signature.email ?? "-"}</div>

                        </td>

                        <td className="px-4 py-3 text-slate-700">

                          {signature.role ? signature.role.replace(/_/g, " ") : "-"}

                        </td>

                        <td className="px-4 py-3 text-slate-700">{typeLabel}</td>

                        <td className="px-4 py-3 text-slate-700">{signature.company_name ?? "-"}</td>

                        <td className="px-4 py-3 text-slate-700">{formatDateTime(signature.signed_at)}</td>

                      </tr>

                    );

                  })}

              </tbody>

            </table>

          </div>

        )}

      </div>

    </div>

  );

}


