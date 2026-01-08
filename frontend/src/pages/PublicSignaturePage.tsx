import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent,
  type TouchEvent,
} from "react";
import { useParams } from "react-router-dom";
import { Document, Page } from "react-pdf";
import axios from "axios";
import toast from "react-hot-toast";

import {
  fetchPublicMeta,
  fetchPublicDocumentFields,
  postPublicSign,
  groupPublicSign,
  startPublicAgentSession,
  completePublicAgentSession,
  type PublicMeta,
  type PublicGroupSignPayload,
  type SigningCertificate,
  type DocumentField,
} from "../api";
import { fetchLocalAgentCertificates, signPdfWithLocalAgent, type AgentCertificate } from "../utils/agent";
import { resolveApiBaseUrl } from "../utils/env";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "../utils/pdfWorker";

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
const toBase64Payload = (value: string) => (value.includes(",") ? value.split(",")[1] : value);

const mapAgentCertificates = (items: AgentCertificate[]): SigningCertificate[] =>
  items.map((item, index) => ({
    index: item.index ?? index,
    subject: item.subject,
    issuer: item.issuer,
    serial_number: item.serialNumber,
    thumbprint: item.thumbprint,
    not_before: item.notBefore,
    not_after: item.notAfter,
  }));

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
  const [groupSelections, setGroupSelections] = useState<string[]>([]);
  const [groupSigning, setGroupSigning] = useState(false);

  const [certificateModalOpen, setCertificateModalOpen] = useState(false);
  const [certificates, setCertificates] = useState<SigningCertificate[]>([]);
  const [certLoading, setCertLoading] = useState(false);
  const [certError, setCertError] = useState<string | null>(null);
  const [selectedCertIndex, setSelectedCertIndex] = useState<number | null>(null);
  const [agentSigning, setAgentSigning] = useState(false);
  const [fields, setFields] = useState<DocumentField[]>([]);
  const [fieldsLoading, setFieldsLoading] = useState(false);
  const [fieldsError, setFieldsError] = useState<string | null>(null);
  const [pdfScale, setPdfScale] = useState(1);
  const [numPages, setNumPages] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [renderedSize, setRenderedSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [typedName, setTypedName] = useState("");
  const [typedNameTouched, setTypedNameTouched] = useState(false);
  const [confirmEmail, setConfirmEmail] = useState("");
  const [confirmPhoneLast4, setConfirmPhoneLast4] = useState("");
  const [confirmCpf, setConfirmCpf] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [signatureImageData, setSignatureImageData] = useState<string | null>(null);
  const [signatureImageMime, setSignatureImageMime] = useState<string | null>(null);
  const [signatureImageName, setSignatureImageName] = useState<string | null>(null);
  const [signatureImagePreview, setSignatureImagePreview] = useState<string | null>(null);
  const [signatureImageInputKey, setSignatureImageInputKey] = useState(0);
  const [signatureConsent, setSignatureConsent] = useState(false);
  const [signatureModalOpen, setSignatureModalOpen] = useState(false);
  const [drawModalOpen, setDrawModalOpen] = useState(false);
  const drawCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [hasDrawnSignature, setHasDrawnSignature] = useState(false);
  const [currentSigningField, setCurrentSigningField] = useState<DocumentField | null>(null);
  const [fieldSignatureMap, setFieldSignatureMap] = useState<Record<string, { mode: string; preview?: string; value?: string }>>({});

  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const agentDownloadUrl = useMemo(() => resolveAgentDownloadUrl(), []);
  const previewUrl = useMemo(() => {
    if (!token) return null;
    return `${apiBaseUrl}/public/signatures/${encodeURIComponent(token)}/preview`;
  }, [apiBaseUrl, token]);
  const documentSource = useMemo(() => (previewUrl ? { url: previewUrl } : null), [previewUrl]);
  const imageUploadRef = useRef<HTMLInputElement | null>(null);

  const requiresCertificate = Boolean(meta?.requires_certificate);
  const requiresEmailConfirmation = Boolean(meta?.requires_email_confirmation);
  const requiresPhoneConfirmation = Boolean(meta?.requires_phone_confirmation);
  const requiresCpfConfirmation = Boolean(meta?.requires_cpf_confirmation);
  const collectTypedName = Boolean(meta?.collect_typed_name);
  const typedNameIsRequired = Boolean(meta?.typed_name_required);
  const collectSignatureImage = Boolean(meta?.collect_signature_image);
  const signatureImageIsRequired = Boolean(meta?.signature_image_required);
  const requiresConsent = Boolean(meta?.requires_consent);
  const consentText = meta?.consent_text ?? "Autorizo o uso da minha imagem e dados pessoais para fins de assinatura eletrônica.";
  const consentVersion = meta?.consent_version ?? "v1";
  const allowTypedNameOption = Boolean(meta?.allow_typed_name ?? meta?.collect_typed_name);
  const allowSignatureImageOption = Boolean(meta?.allow_signature_image ?? meta?.collect_signature_image);
  const allowSignatureDrawOption = Boolean(meta?.allow_signature_draw ?? meta?.collect_signature_image ?? false);
  const hasQuickSignOptions = allowTypedNameOption || allowSignatureImageOption || allowSignatureDrawOption;
  const availableFields = meta?.available_fields ?? [];
  const pageFields = useMemo(
    () => fields.filter(field => Number(field.page ?? 1) === currentPage),
    [fields, currentPage],
  );
  const hasFields = fields.length > 0;

  useEffect(() => {
    if (collectTypedName) {
      setTypedName(prev => {
        if (typedNameTouched) {
          return prev;
        }
        const fallback = meta?.signer_name?.trim() ?? "";
        if (!prev.trim() && fallback) {
          return fallback;
        }
        return prev;
      });
    } else {
      setTypedName("");
      setTypedNameTouched(false);
    }
  }, [collectTypedName, meta?.signer_name, typedNameTouched]);

  useEffect(() => {
    if (!requiresEmailConfirmation) {
      setConfirmEmail("");
    }
  }, [requiresEmailConfirmation]);

  useEffect(() => {
    if (!requiresPhoneConfirmation) {
      setConfirmPhoneLast4("");
    }
  }, [requiresPhoneConfirmation]);

  useEffect(() => {
    if (!requiresCpfConfirmation) {
      setConfirmCpf("");
    }
  }, [requiresCpfConfirmation]);

  useEffect(() => {
    if (!requiresConsent) {
      setSignatureConsent(false);
    }
  }, [requiresConsent]);

  const reloadMeta = useCallback(async () => {
    if (!token) {
      throw new Error("Token inválido.");
    }
    const data = await fetchPublicMeta(token);
    setMeta(data);
    if (data.group_documents && data.group_documents.length > 0) {
      const availableIds = data.group_documents
        .filter(doc => (doc.status || "").toLowerCase() !== "completed")
        .map(doc => doc.id);
      setGroupSelections(prev => {
        const preserved = prev.filter(id => availableIds.includes(id));
        return preserved.length > 0 ? preserved : availableIds;
      });
    } else {
      setGroupSelections([]);
    }
  }, [token]);

  useEffect(() => {
    if (!token) {
      setError("Token inválido.");
      setLoading(false);
      return;
    }
    setLoading(true);
    reloadMeta()
      .then(() => setError(null))
      .catch(err => {
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          setError("Link de assinatura inválido ou expirado. Solicite um novo e-mail.");
        } else {
          setError("Não foi possível carregar os dados da assinatura.");
        }
      })
      .finally(() => setLoading(false));
  }, [token, reloadMeta]);

  const handleDocumentLoadSuccess = ({ numPages: nextNumPages }: { numPages?: number }) => {
    const resolved = nextNumPages || 1;
    setNumPages(resolved);
    setCurrentPage(prev => (prev > resolved ? resolved : prev));
  };

  const handlePageRender = (page: any) => {
    try {
      const viewport = page.getViewport({ scale: pdfScale });
      setRenderedSize({ width: viewport.width, height: viewport.height });
    } catch {
      setRenderedSize(prev => ({ ...prev }));
    }
  };

  const handlePrevPage = () => setCurrentPage(prev => Math.max(1, prev - 1));
  const handleNextPage = () => setCurrentPage(prev => Math.min(numPages, prev + 1));

  useEffect(() => {
    if (!token) {
      setFields([]);
      return;
    }
    setFieldsLoading(true);
    setFieldsError(null);
    setCurrentPage(1);
    fetchPublicDocumentFields(token)
      .then(response => setFields(response ?? []))
      .catch(() => {
        setFields([]);
        setFieldsError("Não foi possível carregar os campos configurados.");
      })
      .finally(() => setFieldsLoading(false));
  }, [token]);

  const readFileAsBase64 = (file: File) =>
    new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        if (typeof result === "string") {
          const base64 = result.includes(",") ? result.split(",")[1] ?? "" : result;
          resolve(base64);
        } else {
          reject(new Error("Não foi possível ler a imagem."));
        }
      };
      reader.onerror = () => reject(new Error("Não foi possível ler a imagem."));
      reader.readAsDataURL(file);
    });

  useEffect(() => {
    return () => {
      if (signatureImagePreview) {
        URL.revokeObjectURL(signatureImagePreview);
      }
    };
  }, [signatureImagePreview]);

  const handleSignatureImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      handleClearSignatureImage();
      return;
    }
    try {
      if (file.size > 2 * 1024 * 1024) {
        toast.error("Imagem ultrapassa 2 MB. Reduza o tamanho antes de enviar.");
        return;
      }
      const base64 = await readFileAsBase64(file);
      if (signatureImagePreview) {
        URL.revokeObjectURL(signatureImagePreview);
      }
      setSignatureImageData(base64);
      setSignatureImageMime(file.type || "image/png");
      setSignatureImageName(file.name);
      setSignatureImagePreview(URL.createObjectURL(file));
      setFormError(null);
    } catch (err) {
      console.error(err);
      toast.error("Não foi possível carregar a imagem da assinatura.");
    }
  };

  const handleClearSignatureImage = () => {
    if (signatureImagePreview) {
      URL.revokeObjectURL(signatureImagePreview);
    }
    setSignatureImageData(null);
    setSignatureImageMime(null);
    setSignatureImageName(null);
    setSignatureImagePreview(null);
    setSignatureImageInputKey(prev => prev + 1);
  };

  const buildSignaturePayload = (): PublicGroupSignPayload | null => {
    if (requiresCertificate) {
      toast.error("Esta assinatura exige certificado digital.");
      return null;
    }

    setFormError(null);

    const missingFields = fields.filter(field => {
      const isSignatureField = ["signature", "signature_image", "typed_name"].includes(field.field_type);
      const isRequired = Boolean(field.required);
      const isSigned = Boolean(fieldSignatureMap[field.id]);
      return isSignatureField && isRequired && !isSigned;
    });

    if (missingFields.length > 0) {
      const names = missingFields.map(f => f.label || f.field_type).join(", ");
      const message = `Preencha os campos obrigatórios: ${names}`;
      setFormError(message);
      toast.error(message);
      return null;
    }

    const payload: PublicGroupSignPayload = {
      token: token ?? "",
      documents: [],
      action: "sign",
      signature_type: "electronic",
      fields: [] as any[],
    };

    if (collectTypedName) {
      const value = typedName.trim();
      if (typedNameIsRequired && value.length < 3) {
        const message = "Digite seu nome completo para continuar.";
        setFormError(message);
        toast.error(message);
        return null;
      }
      if (value) {
        payload.typed_name = value;
      }
    }

    if (requiresEmailConfirmation) {
      const value = confirmEmail.trim();
      if (!value) {
        const message = "Confirme o e-mail cadastrado para continuar.";
        setFormError(message);
        toast.error(message);
        return null;
      }
      payload.confirm_email = value;
    }

    if (requiresPhoneConfirmation) {
      const digits = confirmPhoneLast4.replace(/\D/g, "").slice(-4);
      if (digits.length < 4) {
        const message = "Informe os 4 últimos dígitos do telefone cadastrado.";
        setFormError(message);
        toast.error(message);
        return null;
      }
      payload.confirm_phone_last4 = digits;
    }

    if (requiresCpfConfirmation) {
      const digits = confirmCpf.replace(/\D/g, "");
      if (digits.length !== 11) {
        const message = "Informe o CPF cadastrado utilizando 11 dígitos.";
        setFormError(message);
        toast.error(message);
        return null;
      }
      payload.confirm_cpf = digits;
    }

    Object.entries(fieldSignatureMap).forEach(([fieldId, sig]) => {
      const field = fields.find(f => f.id === fieldId);
      if (!field) return;

      const fieldPayload: any = {
        field_id: fieldId,
        field_type: field.field_type,
      };

      if (sig.mode === "typed" && sig.value) {
        fieldPayload.typed_name = sig.value;
      } else if (sig.mode === "image" && sig.preview) {
        const base64 = toBase64Payload(sig.preview);
        fieldPayload.signature_image = base64;
        fieldPayload.signature_image_mime = "image/png";
        fieldPayload.signature_image_name = "signature.png";
      } else if (sig.mode === "draw" && sig.preview) {
        const base64 = toBase64Payload(sig.preview);
        fieldPayload.signature_image = base64;
        fieldPayload.signature_image_mime = "image/png";
        fieldPayload.signature_image_name = "signature-draw.png";
      }

      (payload.fields as any[]).push(fieldPayload);
    });

    if (collectSignatureImage) {
      if (signatureImageData) {
        payload.signature_image = signatureImageData;
        if (signatureImageMime) {
          payload.signature_image_mime = signatureImageMime;
        }
        if (signatureImageName) {
          payload.signature_image_name = signatureImageName;
        }
      } else if (signatureImageIsRequired) {
        const message = "Envie a imagem da assinatura para continuar.";
        setFormError(message);
        toast.error(message);
        return null;
      }
    }

    if (requiresConsent) {
      if (!signatureConsent) {
        const message = "Autorize o uso da imagem para concluir a assinatura.";
        setFormError(message);
        toast.error(message);
        return null;
      }
      payload.consent = true;
      if (consentText) {
        payload.consent_text = consentText;
      }
      if (consentVersion) {
        payload.consent_version = consentVersion;
      }
    }

    return payload;
  };

  const handleSignElectronically = async () => {
    if (!token) return;
    const payload = buildSignaturePayload();
    if (!payload) return;

    setBusy(true);
    try {
      await postPublicSign(token, payload);
      setDone(true);
      toast.success("Documento assinado com sucesso!");
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setFormError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const handleSignSelectedDocuments = async () => {
    if (!meta?.group_id) {
      toast.error("Nenhum lote disponível.");
      return;
    }
    if (!token) {
      toast.error("Token de assinatura indisponivel.");
      return;
    }
    if (groupSelections.length === 0) {
      toast.error("Selecione ao menos um documento para assinar.");
      return;
    }
    const payload = buildSignaturePayload();
    if (!payload) return;
    payload.documents = groupSelections;
    setGroupSigning(true);
    try {
      await groupPublicSign(token, payload);
      toast.success("Documentos selecionados assinados.");
      await reloadMeta();
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setFormError(message);
      toast.error(message);
    } finally {
      setGroupSigning(false);
    }
  };

  const toggleGroupSelection = (docId: string, disabled?: boolean) => {
    if (disabled) return;
    setGroupSelections(prev => (prev.includes(docId) ? prev.filter(id => id !== docId) : [...prev, docId]));
  };

  const handleQuickSign = (type: "typed_name" | "draw" | "image", event?: ChangeEvent<HTMLInputElement>) => {
    if (!currentSigningField) return;

    if (type === "typed_name") {
      if (!allowTypedNameOption) {
        toast.error("Assinatura por nome digitado não está habilitada.");
        return;
      }
      const name = prompt("Digite seu nome completo exatamente como deseja assinar:");
      if (name) {
        setFieldSignatureMap(prev => ({
          ...prev,
          [currentSigningField.id]: { mode: "typed", value: name },
        }));
        toast.success("Assinatura textual aplicada ao campo.");
        setSignatureModalOpen(false);
        setCurrentSigningField(null);
      }
      return;
    }

    if (type === "draw") {
      if (!allowSignatureDrawOption) {
        toast.error("A opção de desenhar assinatura não está habilitada.");
        return;
      }
      setSignatureModalOpen(false);
      setDrawModalOpen(true);
      return;
    }

    if (type === "image") {
      if (!allowSignatureImageOption) {
        toast.error("Upload de assinatura não está habilitado.");
        return;
      }
      const file = event?.target?.files?.[0];
      if (!file) {
        toast.error("Selecione uma imagem para continuar.");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = typeof reader.result === "string" ? reader.result : "";
        setFieldSignatureMap(prev => ({
          ...prev,
          [currentSigningField.id]: { mode: "image", preview: base64 },
        }));
        toast.success("Imagem da assinatura vinculada ao campo.");
        setSignatureModalOpen(false);
        setCurrentSigningField(null);
      };
      reader.readAsDataURL(file);
    }
  };

  useEffect(() => {
    if (!drawModalOpen) return;
    const canvas = drawCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#111827";
    setIsDrawing(false);
    setHasDrawnSignature(false);
  }, [drawModalOpen]);

  const getCanvasPoint = (event: MouseEvent<HTMLCanvasElement> | TouchEvent<HTMLCanvasElement>) => {
    const canvas = drawCanvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const source = "touches" in event ? event.touches[0] : event;
    return {
      x: source.clientX - rect.left,
      y: source.clientY - rect.top,
    };
  };

  const handleDrawStart = (event: MouseEvent<HTMLCanvasElement> | TouchEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const ctx = drawCanvasRef.current?.getContext("2d");
    const point = getCanvasPoint(event);
    if (!ctx || !point) return;
    ctx.beginPath();
    ctx.moveTo(point.x, point.y);
    setIsDrawing(true);
  };

  const handleDrawMove = (event: MouseEvent<HTMLCanvasElement> | TouchEvent<HTMLCanvasElement>) => {
    if (!isDrawing) return;
    event.preventDefault();
    const ctx = drawCanvasRef.current?.getContext("2d");
    const point = getCanvasPoint(event);
    if (!ctx || !point) return;
    ctx.lineTo(point.x, point.y);
    ctx.stroke();
    setHasDrawnSignature(true);
  };

  const handleDrawEnd = () => {
    if (!isDrawing) return;
    const ctx = drawCanvasRef.current?.getContext("2d");
    if (ctx) {
      ctx.closePath();
    }
    setIsDrawing(false);
  };

  const handleClearDrawCanvas = () => {
    const canvas = drawCanvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#111827";
    setHasDrawnSignature(false);
    setIsDrawing(false);
  };

  const handleConfirmDrawSignature = () => {
    if (!currentSigningField || !drawCanvasRef.current) return;
    if (!hasDrawnSignature) {
      toast.error("Desenhe sua assinatura antes de confirmar.");
      return;
    }
    const dataUrl = drawCanvasRef.current.toDataURL("image/png");
    setFieldSignatureMap(prev => ({
      ...prev,
      [currentSigningField.id]: { mode: "draw", preview: dataUrl },
    }));
    toast.success("Assinatura desenhada aplicada ao campo.");
    setDrawModalOpen(false);
    setCurrentSigningField(null);
  };

  const handleCancelDrawSignature = () => {
    setDrawModalOpen(false);
    setSignatureModalOpen(true);
  };

  const loadCertificates = useCallback(async () => {
    setCertLoading(true);
    setCertError(null);
    try {
      const agentList = await fetchLocalAgentCertificates();
      const normalized = mapAgentCertificates(agentList);
      const filtered = filterCertificatesByTaxId(normalized, meta?.signer_tax_id);
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
  }, [meta?.signer_tax_id]);

  const handleOpenCertificateModal = () => {
    if (!token) return;
    if (requiresCpfConfirmation) {
      const digits = confirmCpf.replace(/\D/g, "");
      if (digits.length !== 11) {
        toast.error("Informe o CPF cadastrado para prosseguir.");
        return;
      }
    }
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
    const normalizedCpf = confirmCpf.replace(/\D/g, "");
    if (requiresCpfConfirmation && normalizedCpf.length !== 11) {
      setCertError("Informe o CPF cadastrado para continuar.");
      return;
    }
    try {
      const session = await startPublicAgentSession(token, {
        cert_index: selectedCert.index,
        thumbprint: selectedCert.thumbprint ?? undefined,
        confirm_cpf: requiresCpfConfirmation ? normalizedCpf : undefined,
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

  const groupDocuments = meta.group_documents ?? [];
  const hasGroup = Boolean(meta.group_id && groupDocuments.length > 0);

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
          {hasGroup && (
            <div className="mt-6 space-y-3 rounded-2xl border border-indigo-100 bg-indigo-50 p-4 text-xs text-slate-600">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-700">Documentos no lote</h3>
                <span className="text-[11px] text-slate-500">
                  {groupDocuments.length} documento{groupDocuments.length === 1 ? "" : "s"}
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                Selecione os documentos que deseja assinar agora. Os que já foram concluídos aparecem automaticamente como finalizados.
              </p>
              <ul className="space-y-2">
                {groupDocuments.map(doc => {
                  const normalizedStatus = (doc.status || "").toLowerCase();
                  const disabled = normalizedStatus === "completed";
                  const checked = groupSelections.includes(doc.id);
                  return (
                    <li key={doc.id} className="flex items-center justify-between gap-3 rounded border border-white bg-white px-3 py-2">
                      <label className="flex items-center gap-3 text-slate-700">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300"
                          checked={checked || disabled}
                          disabled={disabled}
                          onChange={() => toggleGroupSelection(doc.id, disabled)}
                        />
                        <span className="text-sm font-medium">{doc.name}</span>
                      </label>
                      <span
                        className={`text-[11px] font-semibold uppercase ${
                          disabled ? "text-emerald-600" : "text-slate-500"
                        }`}
                      >
                        {doc.status.replace(/_/g, " ")}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <button
                type="button"
                className="btn btn-primary btn-xs"
                onClick={handleSignSelectedDocuments}
                disabled={groupSigning || groupSelections.length === 0}
              >
                {groupSigning ? "Assinando documentos..." : "Assinar documentos selecionados"}
              </button>
            </div>
          )}

          {(collectTypedName || requiresEmailConfirmation || requiresPhoneConfirmation || requiresCpfConfirmation || collectSignatureImage || requiresConsent) && (
            <div className="mt-6 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <h3 className="text-sm font-semibold text-slate-700">Confirme seus dados</h3>
              <p className="text-xs text-slate-500">
                Preencha as informações abaixo exatamente como foram cadastradas pelo remetente.
              </p>
              {collectTypedName && (
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Nome digitado {typedNameIsRequired ? "(obrigatório)" : "(opcional)"}
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    value={typedName}
                    onChange={event => {
                      setTypedName(event.target.value);
                      setTypedNameTouched(true);
                    }}
                    placeholder="Digite seu nome completo"
                    autoComplete="name"
                    required={typedNameIsRequired}
                  />
                  <span className="mt-1 text-[11px] font-normal text-slate-500">
                    O nome digitado será registrado no protocolo de auditoria.
                  </span>
                </label>
              )}
              {requiresEmailConfirmation && (
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Confirme o e-mail cadastrado
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    type="email"
                    value={confirmEmail}
                    onChange={event => setConfirmEmail(event.target.value)}
                    placeholder="nome@empresa.com"
                    autoComplete="email"
                    required
                  />
                  <span className="mt-1 text-[11px] font-normal text-slate-500">
                    Utilize o mesmo endereço que recebeu o convite ou o código de acesso.
                  </span>
                </label>
              )}
              {requiresPhoneConfirmation && (
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Últimos 4 dígitos do telefone
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    value={confirmPhoneLast4}
                    onChange={event => setConfirmPhoneLast4(event.target.value.replace(/\D/g, "").slice(-4))}
                    placeholder="0000"
                    inputMode="numeric"
                    maxLength={4}
                    required
                  />
                  <span className="mt-1 text-[11px] font-normal text-slate-500">
                    Informe apenas números para confirmar que você tem acesso ao telefone informado.
                  </span>
                </label>
              )}
              {requiresCpfConfirmation && (
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Confirme o CPF cadastrado
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    value={confirmCpf}
                    onChange={event => setConfirmCpf(event.target.value)}
                    placeholder="000.000.000-00"
                    inputMode="numeric"
                    required
                  />
                  <span className="mt-1 text-[11px] font-normal text-slate-500">
                    Utilize o CPF completo cadastrado pelo remetente (somente números).
                  </span>
                </label>
              )}
              {collectSignatureImage && (
                <div className="flex flex-col text-xs font-semibold text-slate-600">
                  Imagem da assinatura {signatureImageIsRequired ? "(obrigatória)" : "(opcional)"}
                  <input
                    key={signatureImageInputKey}
                    type="file"
                    accept="image/png,image/jpeg"
                    className="mt-1 text-sm"
                    onChange={handleSignatureImageChange}
                  />
                  <span className="mt-1 text-[11px] font-normal text-slate-500">
                    Formatos suportados: PNG ou JPG (máx. 2 MB). A imagem ficará registrada junto ao documento.
                  </span>
                  {signatureImagePreview && (
                    <div className="mt-2 flex items-center gap-3 rounded border border-slate-200 bg-white p-2">
                      <img
                        src={signatureImagePreview}
                        alt="Pré-visualização da assinatura"
                        className="h-16 max-w-[160px] rounded border border-slate-100 object-contain"
                      />
                      <div className="flex flex-col gap-1 text-[11px] font-normal text-slate-500">
                        <span>{signatureImageName}</span>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs text-rose-600"
                          onClick={handleClearSignatureImage}
                        >
                          Remover imagem
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {requiresConsent && (
                <label className="flex items-start gap-2 text-xs font-semibold text-slate-600">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={signatureConsent}
                    onChange={event => setSignatureConsent(event.target.checked)}
                    required
                  />
                  <span className="font-normal text-slate-600">
                    {consentText} (versão {consentVersion})
                  </span>
                </label>
              )}
              {formError && <p className="text-xs text-rose-600">{formError}</p>}
            </div>
          )}

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
              Visualizacao do documento
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
          <div className="flex-1 min-h-[420px] rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            {documentSource ? (
              <div className="flex h-full flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-semibold text-slate-600">
                  <div className="flex items-center gap-2">
                    <button type="button" className="btn btn-ghost btn-xs" onClick={handlePrevPage} disabled={currentPage <= 1}>
                      ←
                    </button>
                    <span>
                      Página {currentPage}/{numPages}
                    </span>
                    <button type="button" className="btn btn-ghost btn-xs" onClick={handleNextPage} disabled={currentPage >= numPages}>
                      →
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <span>Zoom</span>
                    <input
                      type="range"
                      min={75}
                      max={200}
                      value={Math.round(pdfScale * 100)}
                      onChange={event => setPdfScale(Number(event.target.value) / 100)}
                    />
                  </div>
                </div>
                <div className="flex-1 overflow-auto rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3">
                  <Document
                    file={documentSource}
                    loading="Carregando PDF..."
                    error="Falha ao carregar PDF."
                    onLoadSuccess={handleDocumentLoadSuccess}
                  >
                    <div className="flex justify-center">
                      <div
                        className="relative inline-block"
                        style={{ width: renderedSize.width || undefined, minWidth: "240px" }}
                      >
                        <Page
                          pageNumber={currentPage}
                          scale={pdfScale}
                          renderAnnotationLayer={false}
                          renderTextLayer={false}
                          onRenderSuccess={handlePageRender}
                        />
                        <div className="absolute inset-0">
                          {pageFields.map(field => {
                            const left = (field.x ?? 0) * 100;
                            const top = (field.y ?? 0) * 100;
                            const width = (field.width ?? 0) * 100;
                            const height = (field.height ?? 0) * 100;
                            const isSignatureField = ["signature", "signature_image", "typed_name"].includes(
                              field.field_type,
                            );
                            const fieldSignature = fieldSignatureMap[field.id];

                            if (!isSignatureField && !fieldSignature) return null;

                            return (
                              <div
                                key={field.id}
                                className={`absolute rounded-lg border-2 transition-all shadow-md z-10 ${
                                  fieldSignature
                                    ? "border-emerald-500 bg-emerald-500/20"
                                    : "cursor-pointer border-rose-500 bg-rose-500/15 hover:bg-rose-500/25 hover:border-rose-600"
                                }`}
                                style={{
                                  left: `${left}%`,
                                  top: `${top}%`,
                                  width: `${width}%`,
                                  height: `${height}%`,
                                }}
                                onClick={() => {
                                  if (!isSignatureField) return;
                                  setCurrentSigningField(field);
                                  setSignatureModalOpen(true);
                                  if (!hasQuickSignOptions) {
                                    toast.error("Nenhuma modalidade de assinatura eletrônica está habilitada para este documento.");
                                  }
                                }}
                              >
                                <div className="flex h-full w-full items-center justify-center p-1 text-center">
                                  {fieldSignature ? (
                                    fieldSignature.preview ? (
                                      <img
                                        src={fieldSignature.preview}
                                        alt="Assinatura aplicada"
                                        className="max-h-full max-w-full object-contain"
                                      />
                                    ) : fieldSignature.value ? (
                                      <span className="text-[10px] font-bold text-emerald-700">
                                        {fieldSignature.value}
                                      </span>
                                    ) : (
                                      <span className="text-[10px] font-bold text-emerald-700">
                                        Assinado ({fieldSignature.mode})
                                      </span>
                                    )
                                  ) : (
                                    <>
                                      <span className="text-[10px] font-bold text-rose-700 uppercase">
                                        {field.label || field.field_type.replace("_", " ")}
                                      </span>
                                      <span className="block text-[8px] text-rose-600 mt-1">clique para assinar</span>
                                    </>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </Document>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white/70 p-3 text-sm text-slate-600">
                  <h3 className="text-xs font-semibold uppercase text-slate-500">Campos configurados</h3>
                  {fieldsLoading ? (
                    <p className="mt-2 text-xs">Carregando campos...</p>
                  ) : fieldsError ? (
                    <p className="mt-2 text-xs text-rose-600">{fieldsError}</p>
                  ) : hasFields ? (
                    <ul className="mt-2 space-y-1 text-xs">
                      {fields.map(field => (
                        <li
                          key={field.id}
                          className="flex flex-wrap items-center gap-2 rounded border border-slate-100 px-2 py-1"
                        >
                          <span className="font-semibold text-slate-800">
                            {field.label || field.field_type.replace(/_/g, " ")}
                          </span>
                          <span className="text-slate-500">Pagina {field.page ?? 1}  {field.field_type}</span>
                          {field.required ? (
                            <span className="text-rose-600">Obrigatorio</span>
                          ) : (
                            <span className="text-slate-400">Opcional</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs">
                      Nenhum campo foi definido para o seu papel. A assinatura sera aplicada automaticamente.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-sm text-slate-500">
                Pre-visualizacao indisponivel.
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
                ??
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
      {signatureModalOpen && currentSigningField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-slate-800">Assinar campo</h3>
            <p className="mt-1 text-sm text-slate-600">
              {currentSigningField.label || currentSigningField.field_type.replace(/_/g, " ")}
            </p>
            <div className="mt-4 space-y-3">
              {!hasQuickSignOptions ? (
                <p className="text-sm text-slate-500">
                  Nenhuma modalidade eletrônica foi habilitada para este documento. Entre em contato com o remetente
                  para ajustar as permissões de assinatura.
                </p>
              ) : (
                <>
                  {allowTypedNameOption && (
                    <button
                      type="button"
                      className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-left hover:bg-slate-50"
                      onClick={() => handleQuickSign("typed_name")}
                    >
                      Digitar meu nome
                    </button>
                  )}
                  {allowSignatureDrawOption && (
                    <button
                      type="button"
                      className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-left hover:bg-slate-50"
                      onClick={() => handleQuickSign("draw")}
                    >
                      Desenhar assinatura
                    </button>
                  )}
                  {allowSignatureImageOption && (
                    <>
                      <button
                        type="button"
                        className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-left hover:bg-slate-50"
                        onClick={() => imageUploadRef.current?.click()}
                      >
                        Fazer upload da imagem
                      </button>
                      <input
                        ref={imageUploadRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={event => handleQuickSign("image", event)}
                      />
                    </>
                  )}
                </>
              )}
            </div>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setSignatureModalOpen(false);
                  setCurrentSigningField(null);
                }}
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
      {drawModalOpen && currentSigningField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-slate-800">Desenhar assinatura</h3>
            <p className="mt-1 text-sm text-slate-600">
              Use o mouse ou o toque para desenhar sua assinatura exatamente como deseja que apareça no documento.
            </p>
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <canvas
                ref={drawCanvasRef}
                width={520}
                height={220}
                className="h-48 w-full rounded-md border border-slate-300 bg-white"
                style={{ touchAction: "none" }}
                onMouseDown={handleDrawStart}
                onMouseMove={handleDrawMove}
                onMouseUp={handleDrawEnd}
                onMouseLeave={handleDrawEnd}
                onTouchStart={handleDrawStart}
                onTouchMove={handleDrawMove}
                onTouchEnd={handleDrawEnd}
              />
              <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                <span>{hasDrawnSignature ? "Assinatura pronta para ser aplicada." : "Desenhe dentro da área acima."}</span>
                <button type="button" className="btn btn-ghost btn-xs" onClick={handleClearDrawCanvas}>
                  Limpar
                </button>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleCancelDrawSignature}>
                Voltar
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleConfirmDrawSignature}
                disabled={!hasDrawnSignature}
              >
                Aplicar assinatura
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}









