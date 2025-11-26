import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import toast from "react-hot-toast";

import {
  fetchPublicMeta,
  postPublicSign,
  startPublicAgentSession,
  completePublicAgentSession,
  fetchPublicAgentCertificates,
  type PublicMeta,
  type SigningCertificate,
} from "../api";
import { signPdfWithLocalAgent } from "../utils/agent";
import { resolveApiBaseUrl } from "../utils/env";

const resolveAgentDownloadUrl = () => {
  const envUrl = (import.meta as any).env?.VITE_SIGNING_AGENT_DOWNLOAD_URL as string | undefined;
  return envUrl ? envUrl.trim() : null;
};

const extractErrorMessage = (err: unknown): string => {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "error" in detail) {
      return String(detail.error);
    }
    return err.message || "Falha ao processar a solicitação.";
  }
  return err instanceof Error ? err.message : "Falha inesperada.";
};

const normalizeDigits = (value?: string | null) => (value ?? "").replace(/\D/g, "");

const filterCertificatesByTaxId = (items: SigningCertificate[], taxId?: string | null): SigningCertificate[] => {
  const target = normalizeDigits(taxId);
  if (!target) return items;
  return items.filter(item => {
    const subjectDigits = normalizeDigits(item.subject);
    const issuerDigits = normalizeDigits(item.issuer);
    return subjectDigits.includes(target) || issuerDigits.includes(target);
  });
};

export default function PublicSignaturePage() {
  const { token } = useParams<{ token: string }>();
  const [meta, setMeta] = useState<PublicMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const [certificateModalOpen, setCertificateModalOpen] = useState(false);
  const [certificates, setCertificates] = useState<SigningCertificate[]>([]);
  const [certLoading, setCertLoading] = useState(false);
  const [certError, setCertError] = useState<string | null>(null);
  const [selectedCertIndex, setSelectedCertIndex] = useState<number | null>(null);
  const [agentSigning, setAgentSigning] = useState(false);

  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const agentDownloadUrl = useMemo(() => resolveAgentDownloadUrl(), []);
  const previewUrl = useMemo(() => {
    if (!token) return null;
    return `${apiBaseUrl}/public/signatures/${encodeURIComponent(token)}/page`;
  }, [apiBaseUrl, token]);

  const requiresCertificate = Boolean(meta?.requires_certificate);

  useEffect(() => {
    if (!token) {
      setError("Token inválido.");
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const data = await fetchPublicMeta(token);
        setMeta(data);
      } catch (err: unknown) {
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          setError("Link de assinatura inválido ou expirado. Solicite um novo e-mail.");
        } else {
          setError("Não foi possível carregar os dados da assinatura.");
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const handleSignElectronically = async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await postPublicSign(token, { action: "sign", signature_type: "electronic" });
      setDone(true);
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const loadCertificates = useCallback(async () => {
    if (!token) return;
    setCertLoading(true);
    setCertError(null);
    try {
      const rawList = await fetchPublicAgentCertificates(token);
      const filtered = filterCertificatesByTaxId(rawList, meta?.signer_tax_id);
      setCertificates(filtered);
      if (filtered.length > 0) {
        setSelectedCertIndex(filtered[0].index ?? 0);
      } else {
        setSelectedCertIndex(null);
      }
    } catch (err: unknown) {
      setCertificates([]);
      setSelectedCertIndex(null);
      const message =
        err instanceof Error
          ? err.message
          : "Não foi possível acessar o agente local. Verifique se ele está instalado e em execução.";
      setCertError(message);
    } finally {
      setCertLoading(false);
    }
  }, [token, meta?.signer_tax_id]);

  const handleOpenCertificateModal = () => {
    if (!token) return;
    setCertificateModalOpen(true);
    setCertificates([]);
    setSelectedCertIndex(null);
    setCertError(null);
    void loadCertificates();
  };

  const handleCloseCertificateModal = () => {
    if (agentSigning) return;
    setCertificateModalOpen(false);
  };

  const handleConfirmCertificate = async () => {
    if (!token) return;
    if (selectedCertIndex === null) {
      setCertError("Selecione um certificado para continuar.");
      return;
    }
    const selectedCert = certificates.find(cert => cert.index === selectedCertIndex);
    if (!selectedCert) {
      setCertError("Certificado selecionado não está mais disponível.");
      return;
    }
    setAgentSigning(true);
    setCertError(null);
    try {
      const session = await startPublicAgentSession(token, {
        cert_index: selectedCert.index,
        thumbprint: selectedCert.thumbprint ?? undefined,
      });
      const agentResponse = await signPdfWithLocalAgent(session.payload);
      await completePublicAgentSession(token, session.attempt_id, agentResponse);
      setCertificateModalOpen(false);
      setDone(true);
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setCertError(message);
      toast.error(message);
    } finally {
      setAgentSigning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6 text-sm text-slate-600">
        Carregando…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-sm text-rose-600 shadow-sm">
          {error}
        </div>
      </div>
    );
  }

  if (!meta) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-sm text-rose-600 shadow-sm">
          Dados não disponíveis.
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <div className="max-w-md rounded-2xl border border-emerald-200 bg-white p-6 text-sm text-emerald-700 shadow-sm">
          Assinatura registrada com sucesso. Você pode fechar esta janela.
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-100 py-10">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 lg:flex-row">
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm lg:w-2/5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Fluxo seguro</p>
            <h1 className="mt-1 text-2xl font-semibold text-slate-900">Assinatura do documento</h1>
            <p className="mt-2 text-sm text-slate-600">
              Confirme os dados e siga o método indicado pelo remetente. O documento pode ser visualizado ao lado.
            </p>
          </div>
          <dl className="mt-6 space-y-3 text-sm text-slate-600">
            <div className="flex flex-col">
              <dt className="text-xs uppercase text-slate-500">Documento</dt>
              <dd className="font-medium text-slate-800">{meta.document_id || "—"}</dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-xs uppercase text-slate-500">Participante</dt>
              <dd className="font-medium text-slate-800">{meta.participant_id || "—"}</dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-xs uppercase text-slate-500">Status</dt>
              <dd className="font-medium text-slate-800">{meta.status}</dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-xs uppercase text-slate-500">Certificado digital obrigatório?</dt>
              <dd className="font-medium text-slate-800">{requiresCertificate ? "Sim" : "Não"}</dd>
            </div>
          </dl>

          <div className="mt-6 space-y-3">
            {requiresCertificate ? (
              <button
                type="button"
                className="btn btn-primary w-full"
                disabled={agentSigning}
                onClick={handleOpenCertificateModal}
              >
                {agentSigning ? "Preparando agente..." : "Assinar com certificado digital"}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-primary w-full"
                  disabled={busy}
                  onClick={handleSignElectronically}
                >
                  {busy ? "Assinando..." : "Assinar eletronicamente"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary w-full"
                  disabled={agentSigning}
                  onClick={handleOpenCertificateModal}
                >
                  {agentSigning ? "Preparando agente..." : "Assinar com certificado digital"}
                </button>
              </>
            )}
            <p className="text-xs text-slate-500">
              Ao continuar você concorda em registrar sua assinatura eletrônica neste documento.
              {agentDownloadUrl ? (
                <>
                  {" "}
                  Caso ainda não tenha o agente instalado,{" "}
                  <a
                    href={agentDownloadUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="font-semibold text-indigo-600 hover:text-indigo-500"
                  >
                    baixe o instalador aqui
                  </a>
                  .
                </>
              ) : null}
            </p>
          </div>
        </section>

        <section className="flex flex-1 flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Visualização do documento
            </h2>
            {previewUrl && (
              <a
                href={previewUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-500"
              >
                Abrir em nova guia
              </a>
            )}
          </div>
          <div className="flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm min-h-[420px]">
            {previewUrl ? (
              <iframe
                key={previewUrl}
                title="Documento para assinatura"
                src={previewUrl}
                className="h-full w-full"
                allow="clipboard-write; fullscreen"
              />
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-sm text-slate-500">
                Pré-visualização indisponível.
              </div>
            )}
          </div>
        </section>
      </div>

      {certificateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-800">Selecionar certificado digital</h3>
                <p className="text-xs text-slate-500">
                  Escolha um certificado instalado nesta máquina para continuar com a assinatura.
                </p>
              </div>
              <button
                type="button"
                className="text-slate-500 transition hover:text-slate-700"
                onClick={handleCloseCertificateModal}
                disabled={agentSigning}
              >
                ×
              </button>
            </div>
            <div className="px-6 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
              {certLoading ? (
                <p className="text-sm text-slate-500">Carregando certificados do agente…</p>
              ) : certError ? (
                <p className="text-sm text-rose-600">{certError}</p>
              ) : certificates.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Nenhum certificado foi encontrado. Verifique se o agente está em execução e tente novamente.
                </p>
              ) : (
                certificates.map(cert => (
                  <label
                    key={`${cert.index}-${cert.thumbprint ?? cert.serial_number ?? cert.subject}`}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2 ${
                      selectedCertIndex === cert.index
                        ? "border-indigo-500 bg-indigo-50"
                        : "border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <input
                      type="radio"
                      className="mt-1"
                      name="public-sign-certificate"
                      value={cert.index}
                      checked={selectedCertIndex === cert.index}
                      onChange={() => setSelectedCertIndex(cert.index)}
                    />
                    <div className="text-sm text-slate-700">
                      <p className="font-semibold">{cert.subject}</p>
                      <p className="text-xs text-slate-500">Emissor: {cert.issuer}</p>
                      {cert.serial_number && (
                        <p className="text-xs text-slate-500">Série: {cert.serial_number}</p>
                      )}
                      {cert.thumbprint && (
                        <p className="text-xs text-slate-500">Thumbprint: {cert.thumbprint}</p>
                      )}
                    </div>
                  </label>
                ))
              )}
              <p className="text-xs text-slate-500">
                O agente de assinatura precisa estar instalado neste computador para listar os certificados.
                {agentDownloadUrl ? (
                  <>
                    {" "}
                    <a
                      href={agentDownloadUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="font-semibold text-indigo-600 hover:text-indigo-500"
                    >
                      Clique aqui para baixar
                    </a>
                    .
                  </>
                ) : null}
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleCloseCertificateModal}
                disabled={agentSigning}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={
                  agentSigning || certLoading || certificates.length === 0 || selectedCertIndex === null
                }
                onClick={handleConfirmCertificate}
              >
                {agentSigning ? "Assinando..." : "Confirmar assinatura"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
