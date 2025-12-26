
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { isAxiosError } from "axios";

import StepBuilder, { BuilderStep, PartySuggestion } from "../components/StepBuilder";
import PdfFieldDesigner from "../components/PdfFieldDesigner";
import { resolveApiBaseUrl } from "../utils/env";

import {
  api,
  fetchDocuments,
  fetchDocument,
  fetchDocumentVersion,
  createDocumentField,
  deleteDocumentField,
  fetchDocumentParties,
  createDocumentParty,
  updateDocumentParty,
  deleteDocumentParty,
  fetchAuditEvents,
  dispatchWorkflow,
  resendDocumentNotifications,
  fetchSigningCertificates,
  issueSignerShareLink,
  searchContacts,
  listWorkflowTemplates,
  createWorkflowTemplate,
  type DocumentRecord,
  type DocumentVersion,
  type DocumentField,
  type DocumentParty,
  type AuditEvent,
  signDocumentVersionWithAgent,
  retrySignDocumentVersionWithAgent,
  fetchLatestSignAgentAttempt,
  type SignAgentAttempt,
  type SignAgentResponse,
  type SignAgentErrorDetail,
  type Usage,
  type UserMe,
  type WorkflowTemplate,
  type WorkflowTemplateStep,
  type SigningCertificate,
  type DocumentFieldPayload,
  type ContactDirectoryEntry,
} from "../api";

interface DocumentManagerPageProps {
  tenantId: string;
  areaId?: string;
  usage?: Usage | null;
  currentUser?: UserMe | null;
  focusFilter?: DocumentListFilter | null;
  onFocusConsumed?: () => void;
  onCreateNew?: () => void;
  initialDocumentId?: string | null;
  standalone?: boolean;
}

interface PartyFormState {
  full_name: string;
  email: string;
  phone_number: string;
  cpf: string;
  role: string;
  order_index: number;
  notification_channel: "email" | "sms";
  company_name: string;
  company_tax_id: string;
  require_cpf: boolean;
  require_email: boolean;
  require_phone: boolean;
  allow_typed_name: boolean;
  allow_signature_image: boolean;
  allow_signature_draw: boolean;
  signature_method: "electronic" | "digital";
  two_factor_type: string;
}

type SignAttempt = {
  id?: string;
  at: string;
  status: "success" | "error" | "pending";
  protocol?: string;
  message?: string;
};

const percent = (value: number) => `${Math.round(value * 100)}%`;

const formatDateTime = (value: string) =>
  new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));

const formatStatusLabel = (value?: string | null) => (value ? value.replace(/_/g, " ") : "Sem status");

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i;
const normalizeEmail = (value: string) => value.trim().toLowerCase();
const normalizePhone = (value: string) => value.replace(/\D/g, "");
const isEmailValid = (value: string) => emailPattern.test(normalizeEmail(value));
const isPhoneValid = (value: string) => normalizePhone(value).length >= 10;
const formatPhoneDisplay = (value: string) => {
  const digits = normalizePhone(value);
  if (digits.length === 11) {
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
  }
  return value || "-";
};

type DocumentListFilter = "all" | "my_pending" | "area_pending" | "my_documents";
type WorkflowTab = "document" | "flow" | "positions" | "dispatch" | "evidence";

const WORKFLOW_TABS: Array<{
  id: WorkflowTab;
  label: string;
  description: string;
}> = [
  {
    id: "document",
    label: "1. Documento",
    description: "Envie arquivos, cadastre títulos e escolha qual item será configurado agora.",
  },
  {
    id: "flow",
    label: "2. Fluxo",
    description: "Prepare o fluxo manual, cadastre representantes ou aplique um modelo salvo.",
  },
  {
    id: "positions",
    label: "3. Assinaturas",
    description: "Defina onde cada participante deve assinar diretamente sobre o PDF.",
  },
  {
    id: "dispatch",
    label: "4. Revisão e envio",
    description: "Revise o checklist e dispare as notificações para assinatura.",
  },
  {
    id: "evidence",
    label: "5. Protocolo",
    description: "Consulte o histórico, protocolos e evidências geradas pelo sistema.",
  },
];

const normalizeRoleValue = (value: string | null | undefined) => (value ?? "").trim().toLowerCase();

const defaultPartyForm = (order = 1): PartyFormState => ({
  full_name: "",
  email: "",
  phone_number: "",
  cpf: "",
  role: "signer",
  order_index: order,
  notification_channel: "email",
  company_name: "",
  company_tax_id: "",
  require_cpf: true,
  require_email: true,
  require_phone: false,
  allow_typed_name: true,
  allow_signature_image: true,
  allow_signature_draw: true,
  signature_method: "electronic",
  two_factor_type: "",
});

export default function DocumentManagerPage({
  tenantId,
  areaId,
  usage = null,
  currentUser = null,
  focusFilter = null,
  onFocusConsumed,
  onCreateNew,
  initialDocumentId = null,
  standalone = false,
}: DocumentManagerPageProps) {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [standaloneLoading, setStandaloneLoading] = useState(false);
  const [standaloneError, setStandaloneError] = useState<string | null>(null);
  const standaloneView = standalone ?? Boolean(initialDocumentId);

  const [selectedDocument, setSelectedDocument] = useState<DocumentRecord | null>(null);
  const [activeVersion, setActiveVersion] = useState<DocumentVersion | null>(null);
  const [fields, setFields] = useState<DocumentField[]>([]);
  const [fieldSaving, setFieldSaving] = useState(false);
  const [skipSignaturePlacement, setSkipSignaturePlacement] = useState(false);

  const fieldTypeOptions = useMemo(
    () => [
      { value: "signature", label: "Assinatura" },
      { value: "initials", label: "Rubrica" },
      { value: "text", label: "Texto" },
      { value: "typed_name", label: "Nome digitado" },
      { value: "signature_image", label: "Imagem de assinatura" },
    ],
    [],
  );

  const [parties, setParties] = useState<DocumentParty[]>([]);
  const [partyForm, setPartyForm] = useState<PartyFormState>(() => defaultPartyForm());
  const [partyLoading, setPartyLoading] = useState(false);
  const [partySaving, setPartySaving] = useState(false);
  const [editingPartyId, setEditingPartyId] = useState<string | null>(null);
  const [partyError, setPartyError] = useState<string | null>(null);

  const availableRoles = useMemo(() => {
    const rolesList = parties
      .map(party => (party.role || "").trim().toLowerCase())
      .filter(role => role.length > 0);
    if (!rolesList.includes("signer")) {
      rolesList.push("signer");
    }
    return Array.from(new Set(rolesList));
  }, [parties]);
  const contactSearchTimeout = useRef<number | null>(null);
  const [contactSuggestions, setContactSuggestions] = useState<ContactDirectoryEntry[]>([]);
  const [contactSearching, setContactSearching] = useState(false);

  const [signProtocol, setSignProtocol] = useState("");
  const [signActions, setSignActions] = useState(
    "Documento enviado pelo NacionalSign.\nAssinatura digital aplicada com validade juridica.",
  );
  const [signWatermark, setSignWatermark] = useState("");
  const [signFooterNote, setSignFooterNote] = useState("");
  const [dispatchDeadline, setDispatchDeadline] = useState("");
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);
  const [signError, setSignError] = useState<string | null>(null);
  const [lastSignInfo, setLastSignInfo] = useState<SignAgentResponse | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [signHistory, setSignHistory] = useState<SignAttempt[]>([]);
  const [expandedAuditEvents, setExpandedAuditEvents] = useState<Set<string>>(new Set());
  const [latestAttempt, setLatestAttempt] = useState<SignAgentAttempt | null>(null);
  const [attemptLoading, setAttemptLoading] = useState(false);
  const [retryingAgent, setRetryingAgent] = useState(false);
  const [manualFlowSteps, setManualFlowSteps] = useState<BuilderStep[]>([]);
  const [manualFlowDirty, setManualFlowDirty] = useState(false);
  const [templateOptions, setTemplateOptions] = useState<WorkflowTemplate[]>([]);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [templateSaving, setTemplateSaving] = useState(false);
  const [templateRoleEditing, setTemplateRoleEditing] = useState<string | null>(null);
  const [hashCopied, setHashCopied] = useState(false);
  const [documentFilter, setDocumentFilter] = useState<DocumentListFilter>("all");
  const [shareCopied, setShareCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkflowTab>("document");
  const [resendingNotifications, setResendingNotifications] = useState(false);
  const [certificateModalOpen, setCertificateModalOpen] = useState(false);
  const [certificates, setCertificates] = useState<SigningCertificate[]>([]);
  const [certificatesLoading, setCertificatesLoading] = useState(false);
  const [certificatesError, setCertificatesError] = useState<string | null>(null);
  const [selectedCertificateIndex, setSelectedCertificateIndex] = useState<number | null>(null);
  const [copyingPartyLinkId, setCopyingPartyLinkId] = useState<string | null>(null);
  const auditPanelRef = useRef<HTMLDivElement | null>(null);

  const documentsQuota = usage?.documents_quota ?? null;
  const documentsUsed = usage?.documents_used ?? 0;
  const documentLimitReached = documentsQuota !== null && documentsUsed >= documentsQuota;
  const usingTemplate = Boolean(selectedTemplateId);

  const selectedDocumentId = selectedDocument?.id ?? null;
  const activeVersionId = activeVersion?.id ?? null;
  const apiBaseUrl = resolveApiBaseUrl();
  const windowOrigin = typeof window !== "undefined" ? window.location.origin : "";
  const publicBaseUrl =
    ((import.meta as any).env?.VITE_PUBLIC_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
    apiBaseUrl ||
    windowOrigin;
  const shareUrl = useMemo(
    () => (selectedDocument ? `${publicBaseUrl}/public/verification/${selectedDocument.id}/page` : null),
    [selectedDocument, publicBaseUrl],
  );
  const pendingStatuses = useMemo(() => new Set(["in_review", "in_progress"]), []);

  useEffect(() => {
    setSkipSignaturePlacement(false);
  }, [selectedDocumentId]);

  const resolveApiUrl = useCallback(
    (path?: string | null) => {
      if (!path) return null;
      if (/^https?:\/\//i.test(path)) return path;
      const base = apiBaseUrl || "";
      if (!base) return path;
      return `${base}${path.startsWith('/') ? path : `/${path}`}`;
    },
    [apiBaseUrl],
  );
  const pdfPreviewUrl = useMemo(() => {
    const source = activeVersion?.preview_url || activeVersion?.storage_path;
    if (!source) return null;
    return resolveApiUrl(source);
  }, [activeVersion, resolveApiUrl]);

  const buildStepsFromParties = useCallback(
    (items: DocumentParty[]): BuilderStep[] =>
      items.map((party, index) => ({
        id: `${party.id}-${index + 1}`,
        order: index + 1,
        role: party.role || `papel_${index + 1}`,
        action: "sign",
        execution: "sequential",
        deadline_hours: null,
        notification_channel: party.notification_channel === "sms" ? "sms" : "email",
      })),
    [],
  );

  const requiresCertificateInput = partyForm.signature_method === "digital";
  const mustHaveEmail =
    !requiresCertificateInput && (partyForm.require_email || partyForm.notification_channel === "email");
  const mustHavePhone =
    !requiresCertificateInput && (partyForm.require_phone || partyForm.notification_channel === "sms");
  const normalizedEmail = normalizeEmail(partyForm.email);
  const normalizedPhone = normalizePhone(partyForm.phone_number);
  const emailHasValue = normalizedEmail.length > 0;
  const phoneHasValue = normalizedPhone.length > 0;
  const emailInvalid = emailHasValue && !isEmailValid(normalizedEmail);
  const phoneInvalid = phoneHasValue && !isPhoneValid(normalizedPhone);

  const effectiveAreaId = areaId ?? selectedDocument?.area_id ?? null;
  const areaReady = Boolean(effectiveAreaId);
  const visibleDocuments = useMemo(() => {
    if (documentFilter === "all") return documents;
    return documents.filter(doc => {
      if (documentFilter === "my_pending") {
        if (!currentUser) return false;
        return doc.created_by_id === currentUser.id && pendingStatuses.has(doc.status);
      }
      if (documentFilter === "area_pending") {
        const matchesArea = effectiveAreaId ? doc.area_id === effectiveAreaId : true;
        return matchesArea && pendingStatuses.has(doc.status);
      }
       if (documentFilter === "my_documents") {
         if (!currentUser) return false;
         return doc.created_by_id === currentUser.id;
       }
      return true;
    });
  }, [documents, documentFilter, currentUser, effectiveAreaId, pendingStatuses]);
  const loadAuditEvents = useCallback(
    async (documentId: string) => {
      if (!documentId) {
        setAuditEvents([]);
        return;
      }
      setAuditLoading(true);
      setAuditError(null);
      try {
        const { items } = await fetchAuditEvents({ documentId, pageSize: 100 });
        setAuditEvents(items);
      } catch (error) {
        console.error(error);
        let message = "Não foi possível carregar o protocolo.";
        if (isAxiosError(error)) {
          message = (error.response?.data as any)?.detail ?? message;
        } else if (error instanceof Error) {
          message = error.message;
        }
        setAuditError(message);
      } finally {
        setAuditLoading(false);
      }
    },
    [],
  );
  const loadDocuments = useCallback(async () => {
    if (!tenantId || standaloneView) return [] as DocumentRecord[];
    setLoadingDocs(true);
    try {
      const docs = await fetchDocuments(areaId);
      setDocuments(docs);
      return docs;
    } catch (error) {
      console.error(error);
      toast.error("Erro ao carregar documentos.");
      return [] as DocumentRecord[];
    } finally {
      setLoadingDocs(false);
    }
  }, [tenantId, areaId, standaloneView]);

  const loadCertificates = useCallback(async () => {
    setCertificatesLoading(true);
    setCertificatesError(null);
    try {
      const items = await fetchSigningCertificates();
      setCertificates(items);
      if (items.length > 0) {
        setSelectedCertificateIndex(items[0].index);
      } else {
        setSelectedCertificateIndex(null);
      }
    } catch (error) {
      console.error(error);
      let message = "Falha ao carregar certificados locais.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      setCertificates([]);
      setSelectedCertificateIndex(null);
      setCertificatesError(message);
      toast.error(message);
    } finally {
      setCertificatesLoading(false);
    }
  }, []);

  const appendAttemptToHistory = useCallback((attempt: SignAgentAttempt | null) => {
    if (!attempt) return;
    setSignHistory(prev => {
      if (prev.some(item => item.id === attempt.id)) {
        return prev;
      }
      const entry: SignAttempt = {
        id: attempt.id,
        at: attempt.updated_at ?? attempt.created_at,
        status: attempt.status,
        protocol: attempt.protocol ?? undefined,
        message:
          attempt.status === "error"
            ? attempt.error_message ?? undefined
            : attempt.protocol
            ? `Protocolo ${attempt.protocol}`
            : undefined,
      };
      return [entry, ...prev].slice(0, 8);
    });
  }, []);

  const loadLatestAgentAttempt = useCallback(async () => {
    if (!selectedDocumentId || !activeVersionId) {
      setLatestAttempt(null);
      setSignHistory([]);
      setAttemptLoading(false);
      return;
    }
    setAttemptLoading(true);
    try {
      const attempt = await fetchLatestSignAgentAttempt(selectedDocumentId, activeVersionId);
      setLatestAttempt(attempt);
      appendAttemptToHistory(attempt);
    } catch (error) {
      console.error(error);
    } finally {
      setAttemptLoading(false);
    }
  }, [selectedDocumentId, activeVersionId, appendAttemptToHistory]);

  useEffect(() => {
    if (standaloneView) return;
    void loadDocuments();
  }, [loadDocuments, standaloneView]);

  useEffect(() => {
    if (focusFilter) {
      setDocumentFilter(focusFilter);
      if (focusFilter === "my_pending") {
        toast.success("Mostrando documentos pendentes criados por voc.");
      } else if (focusFilter === "area_pending") {
        toast.success("Mostrando pendentes na sua rea.");
      } else if (focusFilter === "my_documents") {
        toast.success("Mostrando documentos enviados por voc.");
      }
      onFocusConsumed?.();
    }
  }, [focusFilter, onFocusConsumed]);

  useEffect(() => {
    void loadLatestAgentAttempt();
  }, [loadLatestAgentAttempt]);

  useEffect(() => {
    if (certificateModalOpen) {
      void loadCertificates();
    }
  }, [certificateModalOpen, loadCertificates]);

  useEffect(() => {
    return () => {
      if (contactSearchTimeout.current) {
        window.clearTimeout(contactSearchTimeout.current);
        contactSearchTimeout.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!latestAttempt) return;
    if (latestAttempt.status === "error") {
      setSignError(latestAttempt.error_message ?? "Falha ao assinar via agente.");
    } else {
      setSignError(null);
    }
  }, [latestAttempt]);

  const resetPartyForm = useCallback(
    (nextOrder?: number) => {
      const order = nextOrder ?? parties.length + 1;
      setPartyForm(defaultPartyForm(order));
      setEditingPartyId(null);
      setPartyError(null);
      setContactSuggestions([]);
      setContactSearching(false);
      if (contactSearchTimeout.current) {
        window.clearTimeout(contactSearchTimeout.current);
        contactSearchTimeout.current = null;
      }
    },
    [parties.length],
  );

  const loadParties = useCallback(
    async (documentId: string) => {
      setPartyLoading(true);
      try {
        const response = await fetchDocumentParties(documentId);
        const normalized = response.map(party => ({
          ...party,
          signature_method: (party.signature_method ?? "electronic") as "electronic" | "digital" | string,
        }));
        setParties(normalized);
        const maxOrder = normalized.reduce((acc, item) => Math.max(acc, item.order_index ?? 0), 0);
        if (!editingPartyId) {
          resetPartyForm(maxOrder + 1);
        }
      } catch (error) {
        console.error(error);
        toast.error("Falha ao carregar partes.");
      } finally {
        setPartyLoading(false);
      }
    },
    [editingPartyId, resetPartyForm],
  );

  useEffect(() => {
    if (!areaReady) {
      setSelectedDocument(null);
      setActiveVersion(null);
      setFields([]);
      setParties([]);
      resetPartyForm(1);
      setAuditEvents([]);
      setAuditError(null);
      setSignHistory([]);
    }
  }, [areaReady, resetPartyForm]);

  useEffect(() => {
    if (selectedDocument && lastSignInfo) {
      void loadAuditEvents(selectedDocument.id);
    }
  }, [selectedDocument?.id, lastSignInfo, loadAuditEvents]);

  const contactIssues = useMemo(() => {
    if (parties.length === 0) {
      return [] as string[];
    }
    return parties.reduce<string[]>((acc, party) => {
      const channel = (party.notification_channel ?? "email").toLowerCase();
      const displayName = party.full_name || party.role || "Signatario";
      const partyEmail = normalizeEmail(party.email ?? "");
      const partyPhoneDigits = normalizePhone(party.phone_number ?? "");
      const requiresCertificate =
        Boolean((party as any).requires_certificate) ||
        (party.signature_method ?? "").toLowerCase() === "digital";
      const emailNeeded = !requiresCertificate && (Boolean(party.require_email) || channel === "email");
      const phoneNeeded = !requiresCertificate && (Boolean(party.require_phone) || channel === "sms");

      if (emailNeeded) {
        if (!partyEmail) {
          acc.push(displayName + ": e-mail obrigatorio");
        } else if (!isEmailValid(partyEmail)) {
          acc.push(displayName + ": e-mail invalido");
        }
      } else if (partyEmail && !isEmailValid(partyEmail)) {
        acc.push(displayName + ": e-mail invalido");
      }

      if (phoneNeeded) {
        if (!partyPhoneDigits) {
          acc.push(displayName + ": telefone obrigatorio");
        } else if (!isPhoneValid(partyPhoneDigits)) {
          acc.push(displayName + ": telefone invalido");
        }
      } else if (partyPhoneDigits && !isPhoneValid(partyPhoneDigits)) {
        acc.push(displayName + ": telefone invalido");
      }

      return acc;
    }, []);
  }, [parties]);

  const readinessItems = useMemo(() => {
    if (!selectedDocument) return [];
    const hasVersion = Boolean(activeVersion);
    const hasParties = parties.length > 0;
    const hasSignatureFields = fields.some(field =>
      ["signature", "signature_image", "typed_name"].includes(field.field_type),
    );
    const signatureStepSatisfied = skipSignaturePlacement || hasSignatureFields;
    const contactHint = (() => {
      if (contactIssues.length === 0) {
        return "Inclua e-mail e telefone conforme o canal escolhido para cada parte.";
      }
      const summary = contactIssues.slice(0, 2).join(" • ");
      const extra = contactIssues.length > 2 ? " (+" + (contactIssues.length - 2) + ")" : "";
      return "Corrija pendencias: " + summary + extra;
    })();
    return [
      {
        id: "version",
        label: "PDF enviado",
        ok: hasVersion,
        hint: "Envie uma versao em PDF antes de continuar.",
      },
      {
        id: "parties",
        label: "Partes cadastradas",
        ok: hasParties,
        hint: "Adicione pelo menos um signatario responsavel.",
      },
      {
        id: "contacts",
        label: "Contatos para envio",
        ok: hasParties && contactIssues.length === 0,
        hint: contactHint,
      },
      {
        id: "fields",
        label: "Campos de assinatura posicionados",
        ok: signatureStepSatisfied,
        hint: "Inclua os campos de assinatura e evidencias no documento ou habilite o envio sem posicionamento na etapa 3.",
      },
    ];
  }, [selectedDocument, activeVersion, parties, fields, contactIssues, skipSignaturePlacement]);

  const readinessComplete = readinessItems.length > 0 && readinessItems.every(item => item.ok);
  const readinessPendingItems = useMemo(() => readinessItems.filter(item => !item.ok), [readinessItems]);

  const dispatchDisabledReason = useMemo(() => {
    if (documentLimitReached) {
      return `Limite de documentos assinados do plano foi atingido (${documentsUsed}/${documentsQuota} utilizados). Atualize o plano para liberar novos envios.`;
    }
    if (!selectedDocument) return "Selecione um documento.";
    if (["in_progress", "completed"].includes(selectedDocument.status)) {
      return "Este documento ja foi enviado para assinatura.";
    }
    if (!readinessComplete) {
      if (contactIssues.length > 0) {
        return "Corrija pendencias de contato: " + contactIssues[0];
      }
      return "Conclua o checklist antes de enviar o documento.";
    }
    return null;
  }, [documentLimitReached, selectedDocument, readinessComplete, contactIssues]);

  const canDispatch = !dispatchDisabledReason;
  const documentReady = Boolean(selectedDocument && activeVersion);
  const flowConfigured = usingTemplate ? manualFlowSteps.length > 0 : parties.length > 0;
  const signaturePositionsReady = skipSignaturePlacement || fields.length > 0;
  const dispatchReady = readinessComplete;

  useEffect(() => {
    if (readinessComplete) {
      setDispatchError(null);
    }
  }, [readinessComplete]);

  useEffect(() => {
    if (!manualFlowDirty) {
      setManualFlowSteps(buildStepsFromParties(parties));
    }
  }, [parties, manualFlowDirty, buildStepsFromParties]);

  const canRetryFromAttempt = useMemo(
    () => Boolean(latestAttempt && latestAttempt.status === "error" && latestAttempt.payload),
    [latestAttempt],
  );

  const latestAttemptMeta = useMemo(() => {
    if (!latestAttempt) return null;
    const label =
      latestAttempt.status === "success"
        ? "Sucesso"
        : latestAttempt.status === "error"
        ? "Falha"
        : "Pendente";
    const tone =
      latestAttempt.status === "success"
        ? "text-emerald-600"
        : latestAttempt.status === "error"
        ? "text-rose-600"
        : "text-sky-600";
    return { label, tone };
  }, [latestAttempt]);

  const sortedAuditEvents = useMemo(
    () =>
      [...auditEvents].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [auditEvents],
  );

  const tabStatus = useMemo(
    () => ({
      document: { enabled: true, complete: documentReady },
      flow: { enabled: documentReady, complete: flowConfigured },
      positions: { enabled: documentReady && flowConfigured, complete: signaturePositionsReady },
      dispatch: {
        enabled: documentReady && flowConfigured && signaturePositionsReady,
        complete: dispatchReady,
      },
      evidence: {
        enabled: documentReady && flowConfigured && signaturePositionsReady && dispatchReady,
        complete: sortedAuditEvents.length > 0 || signHistory.length > 0,
      },
    }),
    [documentReady, flowConfigured, signaturePositionsReady, dispatchReady, sortedAuditEvents.length, signHistory.length],
  );

  const highlightedTabId = useMemo(() => {
    for (let index = 1; index < WORKFLOW_TABS.length; index += 1) {
      const previousTab = WORKFLOW_TABS[index - 1];
      const currentTab = WORKFLOW_TABS[index];
      const previousStatus = tabStatus[previousTab.id];
      const currentStatus = tabStatus[currentTab.id];
      if (previousStatus?.complete && currentStatus?.enabled && !currentStatus.complete) {
        return currentTab.id;
      }
    }
    return null;
  }, [tabStatus]);

  useEffect(() => {
    const currentStatus = tabStatus[activeTab];
    if (currentStatus && !currentStatus.enabled) {
      const fallback = WORKFLOW_TABS.find(tab => tabStatus[tab.id].enabled)?.id ?? "document";
      if (fallback !== activeTab) {
        setActiveTab(fallback);
      }
    }
  }, [activeTab, tabStatus]);

  useEffect(() => {
    setExpandedAuditEvents(prev => {
      if (prev.size === 0) return prev;
      const validIds = new Set(sortedAuditEvents.map(event => event.id));
      const next = new Set<string>();
      prev.forEach(id => {
        if (validIds.has(id)) {
          next.add(id);
        }
      });
      return next.size === prev.size ? prev : next;
    });
  }, [sortedAuditEvents]);

  const toggleAuditEvent = useCallback((eventId: string) => {
    setExpandedAuditEvents(prev => {
      const next = new Set(prev);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  }, []);

  const partySuggestions = useMemo<PartySuggestion[]>(
    () =>
      parties.map(party => ({
        role: party.role ?? "",
        email: party.email ?? null,
        phone_number: party.phone_number ?? null,
      })),
    [parties],
  );

  const loadTemplates = useCallback(async () => {
    if (!effectiveAreaId) {
      setTemplateOptions([]);
      return;
    }
    setTemplateLoading(true);
    setTemplateError(null);
    try {
      const data = await listWorkflowTemplates({ area_id: effectiveAreaId });
      setTemplateOptions(data ?? []);
    } catch (error) {
      console.error(error);
      let message = "Falha ao carregar modelos.";
      if (isAxiosError(error)) {
        message = ((error.response?.data as any)?.detail as string | undefined) ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      setTemplateError(message);
    } finally {
      setTemplateLoading(false);
    }
  }, [effectiveAreaId]);

  useEffect(() => {
    if (tenantId) {
      void loadTemplates();
    }
  }, [tenantId, loadTemplates]);

  useEffect(() => {
    if (!usingTemplate) {
      setTemplateRoleEditing(null);
    }
  }, [usingTemplate]);

  const manualFlowRoleWarnings = useMemo(() => {
    if (!manualFlowSteps.length) return [];
    const partyRoleCounts = parties.reduce<Record<string, number>>((acc, party) => {
      const key = normalizeRoleValue(party.role);
      if (!key) return acc;
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});
    const usage: Record<string, number> = {};
    const warnings: string[] = [];
    manualFlowSteps.forEach(step => {
      const key = normalizeRoleValue(step.role);
      const total = partyRoleCounts[key] ?? 0;
      usage[key] = (usage[key] ?? 0) + 1;
      if (!key || total === 0) {
        warnings.push(step.role || `Etapa ${step.order}`);
      } else if (usage[key] > total) {
        warnings.push(`${step.role} (#${usage[key]})`);
      }
    });
    return warnings;
  }, [manualFlowSteps, parties]);

  const manualFlowPayload = useMemo<WorkflowTemplateStep[]>(() => {
    if (!manualFlowSteps.length) return [];
    return manualFlowSteps.map((step, index) => ({
      order: index + 1,
      role: normalizeRoleValue(step.role) || `etapa_${index + 1}`,
      action: step.action.trim().toLowerCase() || "sign",
      execution: step.execution,
      deadline_hours: step.deadline_hours ?? null,
    }));
  }, [manualFlowSteps]);


  const handleStartRoleParty = useCallback(
    (role: string) => {
      setTemplateRoleEditing(role);
      setEditingPartyId(null);
      setPartyError(null);
      const normalizedRole = normalizeRoleValue(role);
      const nextOrder =
        parties.filter(item => normalizeRoleValue(item.role) === normalizedRole).length + 1;
      setPartyForm({
        ...defaultPartyForm(),
        role,
        order_index: nextOrder,
      });
      setTimeout(() => {
        document.getElementById("party-form-anchor")?.scrollIntoView({ behavior: "smooth" });
      }, 50);
    },
    [parties],
  );

  const handleOpenTemplateModal = () => {
    if (!manualFlowSteps.length) {
      toast.error("Configure ao menos uma etapa para salvar como modelo.");
      return;
    }
    setTemplateName(selectedDocument ? `${selectedDocument.name} - modelo` : "Novo modelo");
    setTemplateDescription("");
    setTemplateModalOpen(true);
  };

  const handleCloseTemplateModal = () => {
    if (templateSaving) return;
    setTemplateModalOpen(false);
  };

  const handleSubmitTemplate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!effectiveAreaId) {
      toast.error("Defina a área antes de salvar o modelo.");
      return;
    }
    if (!manualFlowPayload.length) {
      toast.error("Adicione etapas ao fluxo antes de salvar o modelo.");
      return;
    }
    const trimmedName = templateName.trim();
    if (!trimmedName) {
      toast.error("Informe um nome para o modelo.");
      return;
    }
    setTemplateSaving(true);
    try {
      await createWorkflowTemplate({
        area_id: effectiveAreaId,
        name: trimmedName,
        description: templateDescription.trim() || undefined,
        steps: manualFlowPayload,
      });
      toast.success("Modelo salvo com sucesso.");
      setTemplateModalOpen(false);
      setTemplateName("");
      setTemplateDescription("");
      await loadTemplates();
    } catch (error) {
      console.error(error);
      let message = "Falha ao salvar modelo.";
      if (isAxiosError(error)) {
        message = ((error.response?.data as any)?.detail as string | undefined) ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      toast.error(message);
    } finally {
      setTemplateSaving(false);
    }
  };

  const normalizedPublicBase = publicBaseUrl.replace(/\/$/, "");
  const isDocumentCompleted = Boolean(selectedDocument && selectedDocument.status === "completed" && activeVersion);
  const downloadPath = activeVersion?.icp_report_url ?? activeVersion?.icp_public_report_url ?? null;
  const finalDownloadUrl = resolveApiUrl(downloadPath);
  const hasDetachedSignatures = Boolean(activeVersion?.icp_signature_bundle_available);
  const verificationUrl = selectedDocument ? `${normalizedPublicBase}/public/verification/${selectedDocument.id}/page` : null;
  const consolidatedAt =
    activeVersion?.icp_timestamp ??
    activeVersion?.updated_at ??
    selectedDocument?.updated_at ??
    selectedDocument?.created_at ??
    null;
  const formattedConsolidatedAt = consolidatedAt ? formatDateTime(consolidatedAt) : null;
  const documentHash = activeVersion?.sha256 ?? null;
  const isInitiator = Boolean(currentUser && selectedDocument && currentUser.id === selectedDocument.created_by_id);
  const canResendNotifications = Boolean(selectedDocument && selectedDocument.status !== "draft");

  const prettyEventType = (eventType: string) => {
    switch (eventType) {
      case "signature_evidence_captured":
        return "Evidências registradas";
      case "document_signed":
        return "Documento finalizado";
      case "document_sign_agent_failed":
        return "Falha no agente local";
      case "icp_warning":
        return "Alerta ICP";
      default:
        return eventType.replace(/_/g, " ");
    }
  };

  const describeAuditDetails = (event: AuditEvent) => {
    const details = (event.details ?? {}) as Record<string, unknown>;
    const rows: { label: string; value: string }[] = [];
    if (event.event_type === "signature_evidence_captured") {
      if (details.typed_name) {
        rows.push({ label: "Nome digitado", value: String(details.typed_name) });
      }
      if (details.typed_name_hash) {
        rows.push({ label: "Hash (SHA-256)", value: String(details.typed_name_hash) });
      }
      const options = details.options as Record<string, unknown> | undefined;
      if (options && typeof options === "object") {
        const enabled = Object.entries(options)
          .filter(([, enabled]) => Boolean(enabled))
          .map(([key]) => key.replace(/_/g, " "));
        if (enabled.length > 0) {
        rows.push({ label: "Modalidades", value: enabled.join(" • ") });
        }
      }
      if (details.image_filename) {
        rows.push({ label: "Arquivo", value: String(details.image_filename) });
      }
      if (details.image_sha256) {
        rows.push({ label: "Hash da imagem", value: String(details.image_sha256) });
      }
      if (details.image_storage_path) {
        rows.push({ label: "Local de armazenamento", value: String(details.image_storage_path) });
      }
      if (details.consent_version || details.consent_text) {
        const consentText = [
          details.consent_version ? `Versão ${details.consent_version}` : null,
          details.consent_text ? String(details.consent_text) : null,
        ]
          .filter(Boolean)
          .join(" • ");
        rows.push({ label: "Consentimento", value: consentText || "Informado" });
      }
      if (details.consent_given_at) {
        rows.push({ label: "Registrado em", value: formatDateTime(String(details.consent_given_at)) });
      }
      return rows;
    }
    if (event.event_type === "document_sign_agent_failed") {
      if (details.error) {
        rows.push({ label: "Erro", value: String(details.error) });
      }
      const agentDetails = details.agent_details;
      if (agentDetails && typeof agentDetails === "object") {
        Object.entries(agentDetails as Record<string, unknown>).forEach(([key, value]) => {
          rows.push({
            label: `Agente · ${key.replace(/_/g, " ")}`,
            value: typeof value === "string" ? value : JSON.stringify(value),
          });
        });
      }
      if (details.version_id) {
        rows.push({ label: "Versão", value: String(details.version_id) });
      }
      return rows;
    }
    if (event.event_type === "document_signed") {
      if (details.sha256) rows.push({ label: "SHA-256", value: String(details.sha256) });
      if (details.version_id) rows.push({ label: "Versão", value: String(details.version_id) });
      if (details.authority) rows.push({ label: "Autoridade", value: String(details.authority) });
      if (details.issued_at) rows.push({ label: "Carimbo", value: formatDateTime(String(details.issued_at)) });
      return rows;
    }
    if (event.event_type === "icp_warning" && details.warning) {
      rows.push({ label: "Aviso", value: String(details.warning) });
      return rows;
    }
    return Object.entries(details).map(([key, value]) => ({
      label: key.replace(/_/g, " "),
      value: typeof value === "string" ? value : JSON.stringify(value),
    }));
  };

  const applyTemplateSteps = useCallback(
    (
      template: WorkflowTemplate,
      {
        resetParties = false,
        silent = false,
        markDirty = true,
      }: { resetParties?: boolean; silent?: boolean; markDirty?: boolean } = {},
    ) => {
      if (!template.steps || template.steps.length === 0) {
        toast.error("Este modelo nao possui etapas configuradas.");
        return false;
      }

      const orderedSteps = [...template.steps].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
      const builderSteps: BuilderStep[] = orderedSteps.map((step, index) => ({
        id: `${template.id}-${index + 1}`,
        order: index + 1,
        role: step.role,
        action: step.action,
        execution: step.execution,
        deadline_hours: step.deadline_hours ?? null,
        notification_channel: "email",
      }));
      setManualFlowSteps(builderSteps);
      if (markDirty) {
        setManualFlowDirty(true);
      }
      if (resetParties) {
        setParties([]);
      }

      const firstRole = builderSteps[0]?.role ?? null;
      const normalizedFirstRole = normalizeRoleValue(firstRole);
      const nextOrderForRole =
        normalizedFirstRole?.length
          ? parties.filter(item => normalizeRoleValue(item.role) === normalizedFirstRole).length + 1
          : parties.length + 1;
      const nextPartyForm = {
        ...defaultPartyForm(nextOrderForRole),
        role: firstRole ?? "signer",
      };

      setTemplateRoleEditing(firstRole);
      setEditingPartyId(null);
      setPartyForm(nextPartyForm);

      if (!silent) {
        toast.success("Modelo aplicado ao fluxo manual.");
      }
      return true;
    },
    [parties],
  );

  const handleApplyTemplate = useCallback(() => {
    if (!selectedTemplateId) {
      toast.error("Selecione um modelo para aplicar.");
      return;
    }
    const template = templateOptions.find(item => item.id === selectedTemplateId);
    if (!template) {
      toast.error("Modelo selecionado nao foi encontrado.");
      return;
    }
    applyTemplateSteps(template, { resetParties: true, silent: false, markDirty: true });
  }, [applyTemplateSteps, selectedTemplateId, templateOptions]);

  const handleTemplateSelection = useCallback(
    (value: string) => {
      setSelectedTemplateId(value);
      if (!value) {
        setTemplateRoleEditing(null);
        setManualFlowSteps([]);
        setManualFlowDirty(false);
        return;
      }
      const template = templateOptions.find(item => item.id === value);
      if (!template) {
        toast.error("Modelo selecionado nao foi encontrado.");
        return;
      }
      applyTemplateSteps(template, { resetParties: false, silent: true, markDirty: true });
    },
    [applyTemplateSteps, templateOptions],
  );

  const refreshVersion = useCallback(
    async (documentId: string, versionId: string | null) => {
      if (!versionId) {
        setActiveVersion(null);
        setFields([]);
        return;
      }
      try {
        const version = await fetchDocumentVersion(documentId, versionId);
        setActiveVersion(version);
        setFields(version.fields ?? []);
      } catch (error) {
        console.error(error);
        toast.error("Falha ao carregar versao do documento.");
      }
    },
    [],
  );

  const handleSelectDocument = useCallback(
    async (doc: DocumentRecord) => {
      const normalizedStatus = (doc.status ?? "").toLowerCase();
      if (normalizedStatus === "signed") {
        navigate(`/documents/${doc.id}/signed`);
        return;
      }
      if (normalizedStatus === "completed") {
        navigate(`/documentos/${doc.id}`);
        return;
      }
      setSelectedDocument(doc);
      setLastSignInfo(null);
      setSignError(null);
      setSignHistory([]);
      setAuditEvents([]);
      setAuditError(null);
      setDispatchDeadline("");
      setDispatchError(null);
      resetPartyForm();
      setManualFlowDirty(false);
      setManualFlowSteps([]);
      handleTemplateSelection("");
      await Promise.all([
        refreshVersion(doc.id, doc.current_version_id),
        loadParties(doc.id),
        loadAuditEvents(doc.id),
      ]);
    },
    [handleTemplateSelection, loadAuditEvents, loadParties, navigate, refreshVersion, resetPartyForm],
  );

  useEffect(() => {
    if (!initialDocumentId) return;
    if (selectedDocument?.id === initialDocumentId) return;
    const target = documents.find(doc => doc.id === initialDocumentId);
    if (target) {
      void handleSelectDocument(target);
      return;
    }
    let cancelled = false;
    const fetchSelectedDocument = async () => {
      setStandaloneLoading(true);
      setStandaloneError(null);
      try {
        const doc = await fetchDocument(initialDocumentId);
        if (cancelled) return;
        setDocuments(prev => (prev.some(item => item.id === doc.id) ? prev : [...prev, doc]));
        await handleSelectDocument(doc);
      } catch (error) {
        if (cancelled) return;
        console.error(error);
        const message =
          isAxiosError(error)
            ? (error.response?.data as any)?.detail ?? "No foi possvel carregar o documento selecionado."
            : error instanceof Error
            ? error.message
            : "No foi possvel carregar o documento selecionado.";
        setStandaloneError(message);
      } finally {
        if (!cancelled) {
          setStandaloneLoading(false);
        }
      }
    };
    void fetchSelectedDocument();
    return () => {
      cancelled = true;
    };
  }, [initialDocumentId, documents, selectedDocument?.id, handleSelectDocument]);

  const handleManualFlowChange = (steps: BuilderStep[]) => {
    setManualFlowDirty(true);
    setManualFlowSteps(steps);
  };

  const handleManualFlowReset = () => {
    setManualFlowDirty(false);
    setManualFlowSteps(buildStepsFromParties(parties));
  };

  const downloadSignedAsset = async (url: string | null) => {
    if (!url) return;
    try {
      const apiBase = resolveApiBaseUrl();
      const cleanUrl = url.startsWith(apiBase) ? url.replace(apiBase, "") : url;
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
        const simpleMatch = header.match(/filename=\"?([^\";]+)\"?/i);
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
      anchor.download = suggestedName.replace(/[\r\n\"]/g, "");
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 2000);
    } catch (error) {
      console.error(error);
      toast.error("Erro ao baixar o documento final. Verifique sua autenticao.");
    }
  };

  const openInNewTab = (url: string | null) => {
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleOpenAuditPanel = () => {
    if (auditPanelRef.current) {
      auditPanelRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const handleCopyHash = async () => {
    if (!documentHash) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(documentHash);
        setHashCopied(true);
        window.setTimeout(() => setHashCopied(false), 2000);
      } else {
        throw new Error("clipboard_unavailable");
      }
    } catch (error) {
      console.error(error);
      toast.error("Nao foi possivel copiar o hash.");
    }
  };

  const handleOpenFinalPdf = () => downloadSignedAsset(finalDownloadUrl);
  const handleOpenVerification = () => openInNewTab(verificationUrl);
  const handleCopyShareLink = async () => {
    if (!shareUrl) {
      toast.error("Selecione um documento antes de copiar o link.");
      return;
    }
    try {
      await navigator.clipboard.writeText(shareUrl);
      setShareCopied(true);
      toast.success("Link copiado para a rea de transferncia.");
      window.setTimeout(() => setShareCopied(false), 2000);
    } catch (error) {
      console.error(error);
      toast.error("Nao foi possivel copiar o link.");
    }
  };

  const handleResendNotifications = async () => {
    if (!selectedDocument) {
      toast.error("Selecione um documento antes de reenviar.");
      return;
    }
    setResendingNotifications(true);
    try {
      const response = await resendDocumentNotifications(selectedDocument.id);
      toast.success(
        response.notified > 0
          ? `Notificacoes reenviadas para ${response.notified} destinatario(s).`
          : "Nenhum destinatario pendente para reenviar.",
      );
    } catch (error) {
      console.error(error);
      let message = "Falha ao reenviar notificacoes.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      toast.error(message);
    } finally {
      setResendingNotifications(false);
    }
  };

  const handleCopySignerLink = async (party: DocumentParty) => {
    setCopyingPartyLinkId(party.id);
    try {
      const response = await issueSignerShareLink(party.id);
      const resolvedUrl = (response.url ?? "").trim();
      const frontBase = window.location.origin.replace(/\/$/, "");
      const fallbackLink = `${frontBase}/public/sign/${response.token}`;
      await navigator.clipboard.writeText(resolvedUrl || fallbackLink);
      toast.success("Link de assinatura copiado.");
    } catch (error) {
      console.error(error);
      let message = "Falha ao gerar link do assinante.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      toast.error(message);
    } finally {
      setCopyingPartyLinkId(null);
    }
  };
  const handleCloseCertificateModal = () => {
    setCertificateModalOpen(false);
  };

  const handleConfirmCertificateSelection = () => {
    if (selectedCertificateIndex === null) {
      toast.error("Selecione um certificado para continuar.");
      return;
    }
    setCertificateModalOpen(false);
    void performSignWithAgent(selectedCertificateIndex);
  };

  const handleCreateField = useCallback(
    async (payload: DocumentFieldPayload) => {
      if (!selectedDocument || !activeVersion) {
        toast.error("Selecione um documento com versão ativa.");
        return false;
      }
      setFieldSaving(true);
      try {
        await createDocumentField(selectedDocument.id, activeVersion.id, payload);
        toast.success("Campo adicionado.");
        await refreshVersion(selectedDocument.id, activeVersion.id);
        return true;
      } catch (error) {
        console.error(error);
        toast.error("Falha ao adicionar campo.");
        return false;
      } finally {
        setFieldSaving(false);
      }
    },
    [selectedDocument, activeVersion, refreshVersion],
  );

  const handleDeleteField = async (fieldId: string) => {
    if (!selectedDocument || !activeVersion) return;
    try {
      await deleteDocumentField(selectedDocument.id, activeVersion.id, fieldId);
      toast.success("Campo removido.");
      await refreshVersion(selectedDocument.id, activeVersion.id);
    } catch (error) {
      console.error(error);
      toast.error("Falha ao remover campo.");
    }
  };
  const handlePartyInput = <K extends keyof PartyFormState>(key: K, value: PartyFormState[K]) => {
    setPartyForm(prev => {
      if (key === 'notification_channel') {
        const nextChannel = value as PartyFormState['notification_channel'];
        return {
          ...prev,
          notification_channel: nextChannel,
          require_email: nextChannel === 'email' ? true : prev.require_email,
          require_phone: nextChannel === 'sms' ? true : prev.require_phone,
        };
      }
      return { ...prev, [key]: value };
    });
    setPartyError(null);
  };

  const scheduleContactLookup = useCallback(
    (rawValue: string) => {
      if (contactSearchTimeout.current) {
        window.clearTimeout(contactSearchTimeout.current);
        contactSearchTimeout.current = null;
      }
      const term = rawValue.trim();
      if (term.length < 3) {
        setContactSuggestions([]);
        setContactSearching(false);
        return;
      }
      contactSearchTimeout.current = window.setTimeout(async () => {
        setContactSearching(true);
        try {
          const results = await searchContacts(term);
          setContactSuggestions(results);
        } catch (error) {
          console.error(error);
        } finally {
          setContactSearching(false);
        }
      }, 300) as unknown as number;
    },
    [],
  );

  const handleContactNameChange = (value: string) => {
    handlePartyInput("full_name", value);
    scheduleContactLookup(value);
  };

  const handleContactNameBlur = () => {
    if (contactSearchTimeout.current) {
      window.clearTimeout(contactSearchTimeout.current);
      contactSearchTimeout.current = null;
    }
    setContactSuggestions([]);
    setContactSearching(false);
  };

  const applyContactSuggestion = (contact: ContactDirectoryEntry) => {
    setPartyForm(prev => ({
      ...prev,
      full_name: contact.full_name ?? prev.full_name,
      email: contact.email ?? prev.email,
      phone_number: contact.phone_number ?? prev.phone_number,
      cpf: contact.cpf ?? prev.cpf,
      company_name: contact.company_name ?? prev.company_name,
      company_tax_id: contact.company_tax_id ?? prev.company_tax_id,
    }));
    setContactSuggestions([]);
    setContactSearching(false);
    if (contactSearchTimeout.current) {
      window.clearTimeout(contactSearchTimeout.current);
      contactSearchTimeout.current = null;
    }
  };

  const handleEditParty = (party: DocumentParty) => {
    setEditingPartyId(party.id);
    setPartyError(null);
    if (usingTemplate) {
      setTemplateRoleEditing(party.role || null);
      setTimeout(() => {
        document.getElementById("party-form-anchor")?.scrollIntoView({ behavior: "smooth" });
      }, 50);
    }
    setPartyForm({
      full_name: party.full_name,
      email: party.email ?? "",
      phone_number: party.phone_number ?? "",
      cpf: party.cpf ?? "",
      role: party.role,
      order_index: party.order_index ?? 1,
      notification_channel: (party.notification_channel as "email" | "sms") ?? "email",
      company_name: party.company_name ?? "",
      company_tax_id: party.company_tax_id ?? "",
      require_cpf: party.require_cpf ?? true,
      require_email: party.require_email ?? true,
      require_phone: party.require_phone ?? false,
      allow_typed_name: party.allow_typed_name ?? true,
      allow_signature_image: party.allow_signature_image ?? true,
      allow_signature_draw: party.allow_signature_draw ?? true,
      signature_method: (party.signature_method as "electronic" | "digital" | string) ?? "electronic",
      two_factor_type: party.two_factor_type ?? "",
    });
    setContactSuggestions([]);
    setContactSearching(false);
  };

  const handleCancelEditParty = () => {
    resetPartyForm();
    setTemplateRoleEditing(null);
  };

  const handleDeleteParty = async (partyId: string) => {
    if (!selectedDocument) return;
    if (!window.confirm('Remover esta parte do documento?')) return;
    try {
      await deleteDocumentParty(selectedDocument.id, partyId);
      toast.success("Parte removida.");
      await loadParties(selectedDocument.id);
      resetPartyForm();
      setTemplateRoleEditing(null);
    } catch (error) {
      console.error(error);
      toast.error("Falha ao remover parte.");
    }
  };

  const handlePartySubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPartyError(null);
    if (!selectedDocument) {
      toast.error("Selecione um documento para cadastrar as partes.");
      return;
    }
    if (!partyForm.full_name.trim()) {
      setPartyError("Informe o nome do representante.");
      return;
    }
    if (!partyForm.role.trim()) {
      setPartyError("Informe o papel do representante.");
      return;
    }

    if (mustHaveEmail && !emailHasValue) {
      setPartyError("Informe um e-mail para notificacao.");
      return;
    }
    if (emailHasValue && emailInvalid) {
      setPartyError("Informe um e-mail valido.");
      return;
    }
    if (mustHavePhone && !phoneHasValue) {
      setPartyError("Informe um telefone para notificacao.");
      return;
    }
    if (phoneHasValue && phoneInvalid) {
      setPartyError("Informe um telefone valido (com DDD).");
      return;
    }

    const sanitizedPhone = phoneHasValue
      ? (partyForm.phone_number.trim().startsWith("+")
          ? "+" + normalizedPhone
          : normalizedPhone)
      : undefined;

    const payload = {
      full_name: partyForm.full_name.trim(),
      email: emailHasValue ? normalizedEmail : undefined,
      phone_number: sanitizedPhone,
      cpf: partyForm.cpf.trim() || undefined,
      role: partyForm.role.trim().toLowerCase(),
      order_index: partyForm.order_index || undefined,
      notification_channel: partyForm.notification_channel,
      company_name: partyForm.company_name.trim() || undefined,
      company_tax_id: partyForm.company_tax_id.replace(/\D/g, '') || undefined,
      require_cpf: partyForm.require_cpf,
      require_email: partyForm.require_email,
      require_phone: partyForm.require_phone,
      allow_typed_name: partyForm.allow_typed_name,
      allow_signature_image: partyForm.allow_signature_image,
      allow_signature_draw: partyForm.allow_signature_draw,
      signature_method: partyForm.signature_method,
      two_factor_type: partyForm.two_factor_type.trim() || undefined,
    };

    setPartySaving(true);
    try {
      if (editingPartyId) {
        await updateDocumentParty(selectedDocument.id, editingPartyId, payload);
        toast.success("Parte atualizada.");
      } else {
        await createDocumentParty(selectedDocument.id, payload);
        toast.success("Parte cadastrada.");
      }
      await loadParties(selectedDocument.id);
      resetPartyForm();
    } catch (error) {
      console.error(error);
      let message = "Falha ao salvar a parte.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      setPartyError(message);
      toast.error(message);
    } finally {
      setPartySaving(false);
    }
  };

  const applySignAgentSuccess = useCallback(
    async (docId: string, response: SignAgentResponse, successMessage: string) => {
      setLastSignInfo(response);
      toast.success(successMessage);
      setSelectedDocument(prev =>
        prev && prev.id === docId
          ? { ...prev, current_version_id: response.version_id, status: "completed" }
          : prev,
      );
      setDocuments(prev =>
        prev.map(doc =>
          doc.id === docId
            ? { ...doc, current_version_id: response.version_id, status: "completed" }
            : doc,
        ),
      );
      await refreshVersion(docId, response.version_id);
      await loadAuditEvents(docId);
      await loadLatestAgentAttempt();
      setSignError(null);
    },
    [refreshVersion, loadAuditEvents, loadLatestAgentAttempt],
  );

  const retrySignWithAgent = useCallback(async () => {
    if (!selectedDocumentId || !activeVersionId) {
      toast.error("Selecione um documento antes de reenviar.");
      return;
    }
    setRetryingAgent(true);
    setSignError(null);
    try {
      const response = await retrySignDocumentVersionWithAgent(selectedDocumentId, activeVersionId);
      await applySignAgentSuccess(
        selectedDocumentId,
        response,
        "Reenvio ao agente concluido com sucesso.",
      );
    } catch (error) {
      console.error(error);
      let message = "Falha ao reenviar via agente.";
      if (isAxiosError(error)) {
        const detailPayload = error.response?.data?.detail ?? error.response?.data;
        if (typeof detailPayload === "string") {
          message = detailPayload || message;
        } else if (detailPayload && typeof detailPayload === "object") {
          const detail = detailPayload as SignAgentErrorDetail;
          if (detail.error) {
            message = detail.error;
          }
        }
      } else if (error instanceof Error) {
        message = error.message;
      }
      setSignError(message);
      toast.error(message);
      await loadLatestAgentAttempt();
      await loadAuditEvents(selectedDocumentId);
    } finally {
      setRetryingAgent(false);
    }
  }, [selectedDocumentId, activeVersionId, applySignAgentSuccess, loadLatestAgentAttempt, loadAuditEvents]);

  const performSignWithAgent = useCallback(async (certIndex?: number | null) => {
    if (!selectedDocumentId || !activeVersionId) {
      toast.error("Selecione um documento antes de assinar.");
      return;
    }
    setSigning(true);
    setSignError(null);
    try {
      const actionsList = signActions
        .split(/\r?\n|;/)
        .map(item => item.trim())
        .filter(Boolean);
      const payload = {
        protocol: signProtocol.trim() || undefined,
        actions: actionsList.length > 0 ? actionsList : undefined,
        watermark: signWatermark.trim() || undefined,
        footer_note: signFooterNote.trim() || undefined,
        cert_index: certIndex ?? undefined,
      };
      const response = await signDocumentVersionWithAgent(selectedDocumentId, activeVersionId, payload);
      await applySignAgentSuccess(selectedDocumentId, response, "Documento assinado com sucesso.");
    } catch (error) {
      console.error(error);
      let message = "Falha ao assinar via agente.";
      if (isAxiosError(error)) {
        const detailPayload = error.response?.data?.detail ?? error.response?.data;
        if (typeof detailPayload === "string") {
          message = detailPayload || message;
        } else if (detailPayload && typeof detailPayload === "object") {
          const detail = detailPayload as SignAgentErrorDetail;
          if (detail.error) {
            message = detail.error;
          }
        } else if (error.message) {
          message = error.message;
        }
      } else if (error instanceof Error) {
        message = error.message;
      }
      setSignError(message);
      toast.error(message);
      await loadLatestAgentAttempt();
      await loadAuditEvents(selectedDocumentId);
    } finally {
      setSigning(false);
    }
  }, [selectedDocumentId, activeVersionId, applySignAgentSuccess, loadLatestAgentAttempt, loadAuditEvents, signActions, signFooterNote, signProtocol, signWatermark]);


  const handleDispatchDocument = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedDocument) {
      toast.error("Selecione um documento antes de enviar.");
      return;
    }
    if (!readinessComplete) {
      const message = "Conclua o checklist antes de enviar o documento.";
      setDispatchError(message);
      toast.error(message);
      return;
    }
    if (["in_progress", "completed"].includes(selectedDocument.status)) {
      toast.error("O documento j foi enviado para assinatura.");
      return;
    }

    if (documentLimitReached) {
      const message = "Limite de documentos assinados do plano foi atingido. Atualize o plano para enviar novos documentos.";
      setDispatchError(message);
      toast.error(message);
      return;
    }

    if (manualFlowPayload.length > 0 && manualFlowRoleWarnings.length > 0) {
      const message = "Sincronize o fluxo manual com as partes cadastradas antes de enviar.";
      setDispatchError(message);
      toast.error(message);
      return;
    }

    setDispatching(true);
    setDispatchError(null);
    try {
      const payload: { template_id?: string | null; deadline_at?: string | null; steps?: WorkflowTemplateStep[] } = {};
      if (dispatchDeadline) {
        const deadline = new Date(dispatchDeadline);
        if (!Number.isNaN(deadline.getTime())) {
          payload.deadline_at = deadline.toISOString();
        }
      }
      if (manualFlowPayload.length > 0) {
        payload.steps = manualFlowPayload.map(step => ({
          order: step.order,
          role: step.role,
          action: step.action,
          execution: step.execution,
          deadline_hours: step.deadline_hours ?? null,
        }));
      } else if (selectedTemplateId) {
        payload.template_id = selectedTemplateId;
      }
      await dispatchWorkflow(selectedDocument.id, payload);
      toast.success("Solicitacoes de assinatura enviadas.");
      setSelectedDocument(prev => (prev ? { ...prev, status: "in_progress" } : prev));
      setDocuments(prev =>
        prev.map(doc => (doc.id === selectedDocument.id ? { ...doc, status: "in_progress" } : doc)),
      );
      await loadAuditEvents(selectedDocument.id);
      setDispatchDeadline("");
    } catch (error) {
      console.error(error);
      let message = "Falha ao enviar solicitacoes.";
      if (isAxiosError(error)) {
        message = (error.response?.data as any)?.detail ?? message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      setDispatchError(message);
      toast.error(message);
    } finally {
      setDispatching(false);
    }
  };

  const handleSignWithAgent = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedDocument || !activeVersion) {
      toast.error("Selecione um documento antes de assinar.");
      return;
    }
    setCertificateModalOpen(true);
  };

  const handleRetrySign = () => {
    void retrySignWithAgent();
  };

  const handleRefreshAttempt = () => {
    void loadLatestAgentAttempt();
  };

  const icpStatus = useMemo(() => {
    if (!activeVersion) return null;
    if (!activeVersion.icp_signed) {
      return { label: "Aguardando assinatura digital", tone: "text-amber-600" };
    }
    return { label: "Assinado com ICP-Brasil", tone: "text-emerald-600" };
  }, [activeVersion]);

  const requiredSummary = (party: DocumentParty) => {
    const items: string[] = [];
    if (party.require_cpf) items.push("CPF");
    if (party.require_email) items.push("Email");
    if (party.require_phone) items.push("Telefone");
    return items.length > 0 ? items.join(" • ") : "-";
  };

  const signatureSummary = (party: DocumentParty) => {
    const items: string[] = [];
    const method = (party.signature_method ?? "electronic").toLowerCase();
    items.push(method === "digital" ? "Certificado digital" : "Assinatura eletrônica");
    if (party.allow_typed_name) items.push("Nome digitado");
    if (party.allow_signature_image) items.push("Imagem");
    if (party.allow_signature_draw) items.push("Desenho");
    return items.length > 0 ? items.join(" • ") : "-";
  };
  const wrapperClassName = standaloneView ? "mx-auto flex max-w-6xl flex-col gap-6" : "space-y-6";
  const headerContent = standaloneView || focusMode ? (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Fluxo do documento</p>
          <h1 className="text-2xl font-semibold text-slate-900">
            {selectedDocument?.name ?? "Carregando documento..."}
          </h1>
          <p className="text-sm text-slate-500">
            {selectedDocument
              ? `ltima atualizao ${formatDateTime(selectedDocument.updated_at ?? selectedDocument.created_at)}`
              : "Buscando informaes do documento selecionado."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {selectedDocument && (
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
              Status: {formatStatusLabel(selectedDocument.status)}
            </span>
          )}
          {icpStatus && (
            <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${icpStatus.tone}`}>
              {icpStatus.label}
            </span>
          )}
        </div>
      </div>
      {standaloneError && standaloneView && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {standaloneError}
        </div>
      )}
    </div>
  ) : (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Documentos</h1>
        {icpStatus && (
          <span className={`text-sm font-medium ${icpStatus.tone}`}>
            {icpStatus.label}
          </span>
        )}
      </div>
    </div>
  );

  const focusMode = Boolean(selectedDocument) && !standaloneView;
  const limitBanner = documentLimitReached ? (
    <div className="rounded-md border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      Limite de documentos assinados do plano foi atingido ({documentsUsed}/{documentsQuota} utilizados). Atualize o plano ou contrate um pacote adicional para enviar novos documentos.
    </div>
  ) : null;
  const showDocumentList = !standaloneView && !focusMode && documents.length > 0;

  const renderDocumentTab = () => (
    <div className={`grid grid-cols-1 gap-6 ${showDocumentList ? "lg:grid-cols-2" : ""}`}>
      {showDocumentList && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200">
          <div className="px-6 py-4 border-b border-slate-200 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-slate-700">Lista de documentos</h2>
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span>Filtro:</span>
              <select
                className="border border-slate-300 rounded-md px-2 py-1 text-sm"
                value={documentFilter}
                onChange={event => setDocumentFilter(event.target.value as DocumentListFilter)}
              >
                <option value="all">Todos</option>
                <option value="my_pending">Pendentes (meus)</option>
                <option value="my_documents">Enviados por mim</option>
                <option value="area_pending">Pendentes na área</option>
              </select>
            </div>
          </div>
          {loadingDocs ? (
            <div className="px-6 py-4 text-sm text-slate-500">Carregando...</div>
          ) : visibleDocuments.length === 0 ? (
            <div className="px-6 py-4 text-sm text-slate-500">
              {documentFilter === "all"
                ? "Nenhum documento cadastrado nesta área."
                : "Nenhum documento encontrado para o filtro selecionado."}
            </div>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="text-left text-slate-500">
                <tr>
                  <th className="px-6 py-3">Nome</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Atualizado</th>
                </tr>
              </thead>
              <tbody>
                {visibleDocuments.map(doc => {
                  const isSelected = selectedDocument?.id === doc.id;
                  return (
                    <tr
                      key={doc.id}
                      className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${isSelected ? "bg-slate-100/70" : ""}`}
                      onClick={() => handleSelectDocument(doc)}
                    >
                      <td className="px-6 py-3 font-medium text-slate-700">{doc.name}</td>
                      <td className="px-6 py-3 capitalize">{doc.status.replace("_", " ")}</td>
                      <td className="px-6 py-3">{new Date(doc.updated_at ?? doc.created_at).toLocaleString("pt-BR")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
      {!showDocumentList && !standaloneView && !focusMode && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
          Sem documentos para exibir neste filtro. Clique em "Novo documento" para iniciar um cadastro.
        </div>
      )}
      <div className="space-y-6">
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-700">Cadastro do documento</h2>
            {selectedDocument && (
              <span className="text-xs font-medium text-slate-500">
                Status: <span className="capitalize">{selectedDocument.status.replace("_", " ")}</span>
              </span>
            )}
          </div>
          <div className="p-6 space-y-4 text-sm text-slate-600">
            {selectedDocument ? (
              <>
                <div>
                  <p className="text-xs uppercase text-slate-500">Documento atual</p>
                  <p className="text-base font-semibold text-slate-800">{selectedDocument.name}</p>
                </div>
                <dl className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs uppercase text-slate-500">Versão carregada</dt>
                    <dd className="text-sm font-semibold text-slate-700">{activeVersion ? activeVersion.id : "Carregando..."}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-slate-500">Hash (SHA-256)</dt>
                    <dd className="text-sm font-semibold text-slate-700 break-all">
                      {activeVersion?.sha256 ?? "Disponivel apos o upload"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-slate-500">Última atualização</dt>
                    <dd className="text-sm font-semibold text-slate-700">
                      {new Date(selectedDocument.updated_at ?? selectedDocument.created_at).toLocaleString("pt-BR")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-slate-500">Participantes</dt>
                    <dd className="text-sm font-semibold text-slate-700">{parties.length}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-slate-500">Campos posicionados</dt>
                    <dd className="text-sm font-semibold text-slate-700">{fields.length}</dd>
                  </div>
                </dl>
                <p className="text-xs text-slate-500">
                  Avance para a próxima guia para configurar o fluxo de representantes e as posições de assinatura.
                </p>
              </>
            ) : (
              <p className="text-sm text-slate-500">Selecione um documento da lista ou crie um novo para iniciar o fluxo.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  const renderFlowTab = () => (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Partes e representantes</h2>
          {partyLoading && <span className="text-xs text-slate-500">Carregando...</span>}
        </div>
        {selectedDocument ? (
          <div className="p-6 space-y-6">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-2">
              <label className="text-xs font-semibold text-slate-600" htmlFor="template-select-top">
                Modelos salvos
              </label>
              <div className="flex flex-wrap gap-2">
                <select
                  id="template-select-top"
                  className="flex-1 min-w-[200px] border border-slate-300 rounded-md px-3 py-2 text-sm"
                  value={selectedTemplateId}
                  onChange={event => handleTemplateSelection(event.target.value)}
                  disabled={templateLoading || templateOptions.length === 0}
                >
                  <option value="">Selecione um modelo</option>
                  {templateOptions.map(template => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleApplyTemplate}
                  disabled={!selectedTemplateId || templateLoading}
                >
                  Aplicar modelo
                </button>
              </div>
              <p className="text-[11px] text-slate-400">
                Os modelos ficam visíveis apenas para colaboradores da mesma área. Ajuste qualquer dado antes de prosseguir.
              </p>
              {templateLoading ? (
                <p className="text-xs text-slate-500">Carregando modelos disponíveis...</p>
              ) : templateError ? (
                <p className="text-xs text-rose-600">{templateError}</p>
              ) : templateOptions.length === 0 ? (
                <p className="text-xs text-slate-500">Nenhum modelo configurado para esta área.</p>
              ) : usingTemplate ? (
                <p className="text-xs text-slate-500">
                  O modelo define os papéis e a ordem do fluxo. Cadastre os representantes abaixo com os dados corretos.
                </p>
              ) : (
                <p className="text-xs text-slate-500">
                  Escolha um modelo para preencher o fluxo automaticamente ou siga com o cadastro manual.
                </p>
              )}
            </div>
            {usingTemplate && manualFlowSteps.length > 0 && (
              <div className="space-y-4">
                {manualFlowSteps.map((step, index) => {
                  const roleLabel = step.role || `papel_${index + 1}`;
                  const normalizedRole = normalizeRoleValue(step.role);
                  const roleParties = parties.filter(
                    party => normalizeRoleValue(party.role) === normalizedRole,
                  );
                  return (
                    <div key={step.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-800">Papel: {roleLabel}</p>
                          <p className="text-xs text-slate-500">
                            Ação: {step.action} • Execução: {step.execution === "parallel" ? "Paralela" : "Sequencial"}
                          </p>
                        </div>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          onClick={() => handleEditTemplateRole(step.id)}
                        >
                          Ajustar pares
                        </button>
                      </div>
                      <div className="border-t border-dashed border-slate-200 mt-3 pt-3 space-y-1 text-xs text-slate-500">
                        <p>
                          Participantes pareados:{" "}
                          {roleParties.length > 0
                            ? roleParties.map(party => party.full_name || party.email || party.role || "participante").join(", ")
                            : "Nenhum participante pareado"}
                        </p>
                        <p>
                          Tipo de execução: <span className="font-medium">{step.execution === "parallel" ? "Paralela" : "Sequencial"}</span>
                        </p>
                      </div>
                      {templateRoleEditing === step.id && (
                        <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50/60 px-3 py-2">
                          <p className="text-xs font-semibold text-slate-700">Vincular participantes</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {parties.length === 0 ? (
                              <span className="text-[11px] text-slate-500">Cadastre participantes para fazer o pareamento.</span>
                            ) : (
                              parties.map(party => (
                                <label key={party.id} className="text-xs text-slate-600 flex items-center gap-1">
                                  <input
                                    type="checkbox"
                                    checked={normalizeRoleValue(party.role) === normalizedRole}
                                    onChange={event => handleTemplateRoleAssignment(step.id, party.id, event.target.checked)}
                                  />
                                  {party.full_name || party.email || party.role || "Participante"}
                                </label>
                              ))
                            )}
                          </div>
                          <div className="mt-3 flex justify-end gap-2">
                            <button type="button" className="btn btn-ghost btn-xs" onClick={() => setTemplateRoleEditing(null)}>
                              Fechar
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <form className="grid grid-cols-1 md:grid-cols-2 gap-4" onSubmit={handlePartySubmit} id="party-form-anchor">
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Nome completo
                <div className="relative">
                  <input
                    className="mt-1 border rounded px-2 py-1 text-sm w-full"
                    value={partyForm.full_name}
                    onChange={event => handleContactNameChange(event.target.value)}
                    onBlur={handleContactNameBlur}
                    placeholder="Nome e sobrenome"
                    required
                  />
                  {partyForm.full_name.trim().length >= 3 && (contactSearching || contactSuggestions.length > 0) && (
                    <div className="absolute top-full left-0 right-0 z-20 mt-1 rounded-md border border-slate-200 bg-white shadow-lg">
                      {contactSearching && (
                        <div className="px-3 py-2 text-xs text-slate-500">Buscando contatos...</div>
                      )}
                      {!contactSearching &&
                        contactSuggestions.map(contact => (
                          <button
                            type="button"
                            key={contact.id}
                            className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-xs hover:bg-slate-50"
                            onMouseDown={event => event.preventDefault()}
                            onClick={() => applyContactSuggestion(contact)}
                          >
                            <span className="text-sm font-semibold text-slate-800">{contact.full_name}</span>
                            <span className="text-[11px] text-slate-500">
                              {[contact.email, contact.phone_number, contact.company_name].filter(Boolean).join(" • ")}
                            </span>
                          </button>
                        ))}
                    </div>
                  )}
                </div>
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                E-mail
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  type="email"
                  value={partyForm.email}
                  onChange={event => handlePartyInput("email", event.target.value)}
                  placeholder="exemplo@empresa.com"
                  required={partyForm.require_email || partyForm.notification_channel === "email"}
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Telefone
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.phone_number}
                  onChange={event => handlePartyInput("phone_number", event.target.value)}
                  placeholder="(11) 99999-0000"
                  required={partyForm.require_phone || partyForm.notification_channel === "sms"}
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Documento (CPF)
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.cpf}
                  onChange={event => handlePartyInput("cpf", event.target.value)}
                  placeholder="000.000.000-00"
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Papel / função
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.role}
                  onChange={event => handlePartyInput("role", event.target.value)}
                  placeholder="Ex.: assinante, testemunha"
                  required
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Ordem no fluxo
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  type="number"
                  min={1}
                  value={partyForm.order_index}
                  onChange={event => handlePartyInput("order_index", Number(event.target.value))}
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Canal de notificação
                <select
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.notification_channel}
                  onChange={event =>
                    handlePartyInput("notification_channel", event.target.value as PartyFormState["notification_channel"])
                  }
                >
                  <option value="email">Email</option>
                  <option value="sms">SMS</option>
                </select>
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Empresa
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.company_name}
                  onChange={event => handlePartyInput("company_name", event.target.value)}
                  placeholder="Opcional"
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                CNPJ / Doc. Empresa
                <input
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.company_tax_id}
                  onChange={event => handlePartyInput("company_tax_id", event.target.value)}
                  placeholder="Opcional"
                />
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Tipo de assinatura
                <select
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.signature_method}
                  onChange={event => handlePartyInput("signature_method", event.target.value as PartyFormState["signature_method"])}
                >
                  <option value="electronic">Eletrônica</option>
                  <option value="digital">Digital ICP-Brasil</option>
                </select>
              </label>
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Token 2FA
                <select
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={partyForm.two_factor_type}
                  onChange={event => handlePartyInput("two_factor_type", event.target.value)}
                >
                  <option value="">Sem verificação adicional</option>
                  <option value="sms">Token via SMS</option>
                  <option value="email">Token via email</option>
                </select>
              </label>
              <div className="md:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="flex flex-col text-xs font-semibold text-slate-500">
                  Permitir assinatura
                  <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm text-slate-600">
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input
                        type="checkbox"
                        checked={partyForm.allow_typed_name}
                        onChange={event => handlePartyInput("allow_typed_name", event.target.checked)}
                      />
                      Nome digitado
                    </label>
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input
                        type="checkbox"
                        checked={partyForm.allow_signature_image}
                        onChange={event => handlePartyInput("allow_signature_image", event.target.checked)}
                      />
                      Upload de imagem
                    </label>
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input
                        type="checkbox"
                        checked={partyForm.allow_signature_draw}
                        onChange={event => handlePartyInput("allow_signature_draw", event.target.checked)}
                      />
                      Assinatura desenhada
                    </label>
                  </div>
                </div>
              </div>
              <div className="flex flex-col text-xs font-semibold text-slate-500">
                Campos opcionais
                <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-3 text-sm text-slate-600">
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={partyForm.allow_typed_name}
                      onChange={event => handlePartyInput("allow_typed_name", event.target.checked)}
                    />
                    Nome digitado
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={partyForm.allow_signature_image}
                      onChange={event => handlePartyInput("allow_signature_image", event.target.checked)}
                    />
                    Upload de imagem
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={partyForm.allow_signature_draw}
                      onChange={event => handlePartyInput("allow_signature_draw", event.target.checked)}
                    />
                    Assinatura desenhada
                  </label>
                </div>
              </div>
              {partyError && <div className="md:col-span-2 text-xs text-rose-600">{partyError}</div>}
              <div className="md:col-span-2 flex justify-between items-center">
                {editingPartyId && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={handleCancelEditParty}>
                    Cancelar edição
                  </button>
                )}
                <button type="submit" className="btn btn-primary btn-sm" disabled={partySaving}>
                  {partySaving ? "Salvando..." : editingPartyId ? "Atualizar parte" : "Adicionar parte"}
                </button>
              </div>
            </form>

            {!usingTemplate && (
              <div className="border border-slate-200 rounded-lg overflow-hidden">
                {partyLoading ? (
                  <div className="px-4 py-4 text-sm text-slate-500">Carregando partes...</div>
                ) : parties.length === 0 ? (
                  <div className="px-4 py-4 text-sm text-slate-500">Nenhuma parte cadastrada para este documento.</div>
                ) : (
                  <table className="min-w-full text-xs">
                    <thead className="bg-slate-50 text-slate-500 uppercase tracking-wide">
                      <tr>
                        <th className="px-3 py-2 text-left">Representante</th>
                        <th className="px-3 py-2 text-left">Empresa</th>
                        <th className="px-3 py-2 text-left">Canal</th>
                        <th className="px-3 py-2 text-left">Contato</th>
                        <th className="px-3 py-2 text-left">Obrigatórios</th>
                        <th className="px-3 py-2 text-left">Assinatura</th>
                        <th className="px-3 py-2 text-left">Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parties.map(party => {
                        const channel = (party.notification_channel ?? "email").toLowerCase();
                        const channelLabel = channel === "sms" ? "SMS" : "Email";
                        const emailValue = party.email ?? "";
                        const emailNormalizedValue = normalizeEmail(emailValue);
                        const emailNeeded = Boolean(party.require_email) || channel === "email";
                        const emailValid = emailValue ? isEmailValid(emailNormalizedValue) : false;
                        const phoneValue = party.phone_number ?? "";
                        const phoneDigits = normalizePhone(phoneValue);
                        const phoneNeeded = Boolean(party.require_phone) || channel === "sms";
                        const phoneValid = phoneDigits ? isPhoneValid(phoneDigits) : false;
                        const phoneDisplay = phoneDigits ? formatPhoneDisplay(phoneDigits) : "-";
                        return (
                          <tr key={party.id} className="border-t border-slate-100">
                            <td className="px-3 py-2 font-semibold text-slate-700">
                              <div className="flex flex-col">
                                <span>{party.full_name || "Sem nome"}</span>
                                <span className="text-xs text-slate-500">{party.role || "Papel não definido"}</span>
                              </div>
                            </td>
                            <td className="px-3 py-2 text-slate-600">{party.company_name || "-"}</td>
                            <td className="px-3 py-2 text-slate-600">{channelLabel}</td>
                            <td className="px-3 py-2 text-slate-600">
                              <div className="text-xs">
                                <p className={emailNeeded && !emailValid ? "text-rose-600" : ""}>{emailValue || "-"}</p>
                                <p className={`${phoneNeeded && !phoneValid ? "text-rose-600" : ""}`}>{phoneDisplay}</p>
                              </div>
                            </td>
                            <td className="px-3 py-2 text-slate-600">{requiredSummary(party)}</td>
                            <td className="px-3 py-2 text-slate-600">{signatureSummary(party)}</td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-2">
                                <button className="btn btn-ghost btn-xs" onClick={() => handleEditParty(party)}>
                                  Editar
                                </button>
                                <button
                                  className="btn btn-ghost btn-xs text-rose-600"
                                  onClick={() => handleDeleteParty(party.id)}
                                >
                                  Remover
                                </button>
                                <button
                                  className="btn btn-ghost btn-xs"
                                  onClick={() => handleCopySignerLink(party)}
                                  disabled={copyingPartyLinkId === party.id}
                                >
                                  {copyingPartyLinkId === party.id ? "Copiando..." : "Copiar link"}
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="px-6 py-8 text-sm text-slate-500">Selecione um documento para configurar as partes e representantes.</div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Fluxo manual de assinatura</h2>
          {selectedDocument && (
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={handleManualFlowReset}
              disabled={!manualFlowDirty || parties.length === 0}
            >
              Sincronizar com as partes
            </button>
          )}
        </div>
        {selectedDocument ? (
          <div className="p-6 space-y-4">
            {parties.length === 0 && (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                Cadastre ao menos um participante para que o modelo consiga parear automaticamente com os papéis. Você ainda pode selecionar ou ajustar um modelo agora e concluir o pareamento depois.
              </div>
            )}
            <p className="text-sm text-slate-600">
              Ajuste a sequência dos papéis quando optar por enviar este documento sem um modelo pré-definido. As etapas abaixo serão consideradas no envio.
            </p>
            {!usingTemplate && (
              <div className="flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-white/70 px-4 py-3 text-xs text-slate-600">
                <span>Depois de definir o fluxo, salve-o como modelo para reutilizar em outros documentos.</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleOpenTemplateModal}
                  disabled={manualFlowSteps.length === 0}
                >
                  Salvar fluxo como modelo
                </button>
              </div>
            )}
            <StepBuilder value={manualFlowSteps} onChange={handleManualFlowChange} partySuggestions={partySuggestions} />
            {manualFlowRoleWarnings.length > 0 && (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                Algumas etapas ainda não possuem partes compatíveis: {manualFlowRoleWarnings.join(" • ")}
              </div>
            )}
            <p className="text-xs text-slate-500">
              Dica: mantenha o nome do papel igual ao configurado na seção de partes para fazer o pareamento automaticamente.
            </p>
          </div>
        ) : (
          <div className="px-6 py-8 text-sm text-slate-500">Selecione um documento para configurar o fluxo manual.</div>
        )}
      </div>
    </div>
  );

  const renderPositionsTab = () => (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col">
      <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-700">Campos de assinatura</h2>
        {activeVersion?.icp_signed && (
          <button
            type="button"
            className="text-primary-600 text-sm font-medium hover:underline disabled:opacity-50"
            onClick={handleOpenFinalPdf}
            disabled={!finalDownloadUrl}
          >
            {hasDetachedSignatures ? "Baixar pacote (.zip)" : "Baixar PDF assinado"}
          </button>
        )}
      </div>
      {selectedDocument && activeVersion ? (
        <div className="p-6 space-y-6">
          <PdfFieldDesigner
            fileUrl={pdfPreviewUrl}
            roles={availableRoles}
            fieldTypes={fieldTypeOptions}
            fields={fields}
            onCreateField={handleCreateField}
            isSaving={fieldSaving}
            skipSignaturePlacement={skipSignaturePlacement}
            onSkipSignaturePlacementChange={value => setSkipSignaturePlacement(value)}
          />

          <div className="border border-slate-200 rounded-lg overflow-hidden">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50 text-slate-500 uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left">Papel</th>
                  <th className="px-3 py-2 text-left">Tipo</th>
                  <th className="px-3 py-2 text-left">Página</th>
                  <th className="px-3 py-2 text-left">Posição</th>
                  <th className="px-3 py-2 text-left">Dimensões</th>
                  <th className="px-3 py-2 text-left">Ações</th>
                </tr>
              </thead>
              <tbody>
                {fields.length === 0 ? (
                  <tr>
                    <td className="px-3 py-3 text-slate-500" colSpan={6}>
                      Nenhum campo configurado.
                    </td>
                  </tr>
                ) : (
                  fields.map(field => (
                    <tr key={field.id} className="border-t border-slate-100">
                      <td className="px-3 py-2 font-medium text-slate-700">{field.role}</td>
                      <td className="px-3 py-2 capitalize">{field.field_type}</td>
                      <td className="px-3 py-2 text-center">{field.page}</td>
                      <td className="px-3 py-2">
                        X {percent(field.x)} / Y {percent(field.y)}
                      </td>
                      <td className="px-3 py-2">
                        {percent(field.width)} x {percent(field.height)}
                      </td>
                      <td className="px-3 py-2">
                        <button className="btn btn-ghost btn-xs text-rose-600" onClick={() => handleDeleteField(field.id)}>
                          Remover
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="px-6 py-8 text-sm text-slate-500">Selecione um documento para configurar os campos de assinatura.</div>
      )}
    </div>
  );

  const renderDispatchTab = () => (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Checklist de preparação</h2>
          {selectedDocument && (
            <span className={`text-xs font-medium ${readinessComplete ? "text-emerald-600" : "text-amber-600"}`}>
              {readinessComplete ? "Pronto para envio" : "Ações pendentes"}
            </span>
          )}
        </div>
        {selectedDocument ? (
          <div className="p-6">
            {readinessItems.length === 0 ? (
              <div className="text-sm text-slate-500">Carregando checklist...</div>
            ) : (
              <ul className="space-y-3">
                {readinessItems.map(item => (
                  <li key={item.id} className="flex items-start gap-3">
                    <span className={`mt-0.5 text-base font-semibold ${item.ok ? "text-emerald-600" : "text-amber-500"}`}>
                      {item.ok ? "✓" : "!"}
                    </span>
                    <div>
                      <div className="text-sm font-medium text-slate-700">{item.label}</div>
                      {!item.ok && <div className="text-xs text-slate-500">{item.hint}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="px-6 py-6 text-sm text-slate-500">Selecione um documento para visualizar o checklist.</div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-700">Envio aos signatários</h2>
          {selectedDocument && (
            <span
              className={`text-xs font-medium ${
                selectedDocument.status === "completed"
                  ? "text-emerald-600"
                  : selectedDocument.status === "in_progress"
                  ? "text-sky-600"
                  : "text-slate-500"
              }`}
            >
              Status atual: {selectedDocument.status.replace(/_/g, " ")}
            </span>
          )}
        </div>
        {selectedDocument ? (
          <form className="p-6 space-y-4" onSubmit={handleDispatchDocument}>
            {contactIssues.length > 0 && (
              <div className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700">
                <div className="font-semibold">Pendências de contato</div>
                <ul className="mt-1 list-disc space-y-1 pl-4">
                  {contactIssues.slice(0, 4).map(issue => (
                    <li key={issue}>{issue}</li>
                  ))}
                  {contactIssues.length > 4 && (
                    <li className="list-none text-amber-700">... e mais {contactIssues.length - 4} pendências</li>
                  )}
                </ul>
              </div>
            )}
            <p className="text-sm text-slate-600">
              Envie o documento para os signatários conforme os canais configurados. O checklist deve estar completo antes do envio.
            </p>
            {selectedDocument && (
              <div className="rounded border border-indigo-100 bg-indigo-50 px-4 py-3 text-xs text-slate-600 space-y-2">
                <p className="text-sm font-semibold text-slate-700">Compartilhar rapidamente</p>
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
                  <input
                    className="flex-1 border border-indigo-200 rounded-md px-3 py-2 text-sm text-slate-700 bg-white"
                    value={shareUrl ?? ""}
                    readOnly
                  />
                  <div className="flex gap-2">
                    <button type="button" className="btn btn-secondary btn-xs" onClick={handleCopyShareLink} disabled={!shareUrl}>
                      {shareCopied ? "Link copiado" : "Copiar link"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={handleResendNotifications}
                      disabled={!canResendNotifications || resendingNotifications}
                    >
                      {resendingNotifications ? "Reenviando..." : "Reenviar notificações"}
                    </button>
                  </div>
                </div>
                <p className="text-[11px] text-slate-500">
                  Compartilhe o link público com os participantes ou reenvie as notificações automáticas quando precisar.
                </p>
              </div>
            )}
            <div className="rounded border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
              O e-mail enviado inclui automaticamente o status atual do documento, o prazo configurado e o botão "Assinar agora". Quando o canal for SMS, um link curto é enviado sempre que disponível.
            </div>
            {readinessPendingItems.length > 0 && (
              <div className="border border-amber-200 bg-amber-50 text-xs text-amber-700 rounded-lg px-3 py-2">
                <div className="font-semibold">Etapas pendentes:</div>
                <ul className="list-disc list-inside mt-1 space-y-1">
                  {readinessPendingItems.map(item => (
                    <li key={item.id}>{item.label}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="flex flex-col text-xs font-semibold text-slate-500">
                Prazo limite (opcional)
                <input
                  type="datetime-local"
                  className="mt-1 border rounded px-2 py-1 text-sm"
                  value={dispatchDeadline}
                  onChange={event => setDispatchDeadline(event.target.value)}
                />
              </label>
            </div>
            {dispatchError && <div className="text-xs text-rose-600">{dispatchError}</div>}
            <div className="flex items-center justify-end">
              <button type="submit" className="btn btn-primary" disabled={!canDispatch || dispatching}>
                {dispatching ? "Enviando..." : "Enviar para assinatura"}
              </button>
            </div>
          </form>
        ) : (
          <div className="px-6 py-6 text-sm text-slate-500">Selecione um documento para configurar o envio.</div>
        )}
      </div>
    </div>
  );

  const renderEvidenceTab = () => (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200">
      <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-700">Protocolo e evidências</h2>
        {selectedDocument && (
          <div className="flex items-center gap-2">
            {auditLoading && <span className="text-xs text-slate-500">Carregando...</span>}
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => selectedDocument && loadAuditEvents(selectedDocument.id)}
              disabled={auditLoading}
            >
              Atualizar
            </button>
          </div>
        )}
      </div>
      {selectedDocument ? (
        <div className="p-6 space-y-4">
          {auditError && <div className="text-xs text-rose-600">{auditError}</div>}
          {!auditError && !auditLoading && sortedAuditEvents.length === 0 && (
            <div className="text-sm text-slate-500">Nenhuma evidência registrada até o momento.</div>
          )}
          {sortedAuditEvents.map(event => {
            const details = describeAuditDetails(event);
            const isExpanded = expandedAuditEvents.has(event.id);
            return (
              <div key={event.id} className="border border-slate-200 rounded-lg px-4 py-3">
                <div className="flex items-start gap-3">
                  <button
                    type="button"
                    aria-expanded={isExpanded}
                    aria-controls={`audit-details-${event.id}`}
                    onClick={() => toggleAuditEvent(event.id)}
                    className={`mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold transition ${
                      isExpanded ? "border-indigo-200 bg-indigo-50 text-indigo-600" : "border-slate-200 text-slate-500"
                    }`}
                  >
                    {isExpanded ? "▾" : "▸"}
                  </button>
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-slate-700">{prettyEventType(event.event_type)}</div>
                      <div className="text-xs text-slate-500">{formatDateTime(event.created_at)}</div>
                    </div>
                    {isExpanded && (
                      <div id={`audit-details-${event.id}`} className="mt-2 space-y-3">
                        <div className="text-[11px] text-slate-400 flex flex-wrap gap-3">
                          {event.ip_address && <span>IP {event.ip_address}</span>}
                          {event.user_agent && <span className="truncate">{event.user_agent}</span>}
                        </div>
                        {details.length > 0 ? (
                          <ul className="text-sm text-slate-600 space-y-1">
                            {details.map(detail => (
                              <li key={`${event.id}-${detail.label}`}>
                                <span className="font-medium text-slate-700">{detail.label}: </span>
                                <span>{detail.value}</span>
                              </li>
                            ))}
                          </ul>
                        ) : event.details ? (
                          <pre className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded p-3 overflow-x-auto">
                            {JSON.stringify(event.details, null, 2)}
                          </pre>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {signHistory.length > 0 && (
            <div className="border border-slate-200 rounded-lg px-4 py-3">
              <div className="text-sm font-semibold text-slate-700">Tentativas recentes via agente local</div>
              <ul className="mt-2 space-y-1">
                {signHistory.map((attempt, index) => {
                  const statusLabel =
                    attempt.status === "success" ? "Sucesso" : attempt.status === "error" ? "Falha" : "Pendente";
                  const statusClass =
                    attempt.status === "success"
                      ? "text-emerald-600 font-semibold"
                      : attempt.status === "error"
                      ? "text-rose-600 font-semibold"
                      : "text-sky-600 font-semibold";
                  return (
                    <li key={attempt.id ?? `${attempt.at}-${index}`} className="text-xs text-slate-600">
                      <span className={statusClass}>{statusLabel}</span>
                      <span className="ml-2">{formatDateTime(attempt.at)}</span>
                      {attempt.protocol && <span className="ml-2 text-slate-500">Protocolo {attempt.protocol}</span>}
                      {attempt.message && (
                        <div className={`text-[11px] ${attempt.status === "error" ? "text-rose-600" : "text-slate-500"}`}>
                          {attempt.message}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="px-6 py-6 text-sm text-slate-500">Selecione um documento para visualizar o protocolo.</div>
      )}
    </div>
  );

  const renderTabHeader = (sticky: boolean) => (
    <div className={sticky ? "sticky top-4 z-30 space-y-3" : ""}>
      <div
        className={`rounded-2xl border border-slate-200 p-4 shadow-sm ${
          sticky ? "bg-white/95 backdrop-blur supports-[backdrop-filter]:backdrop-blur shadow-md" : "bg-white"
        }`}
      >
        <ol className="flex flex-col gap-3 lg:flex-row">
          {WORKFLOW_TABS.map((tab, index) => {
            const status = tabStatus[tab.id];
            const isActive = activeTab === tab.id;
            const shouldPulse = highlightedTabId === tab.id && !isActive;
            const stepNumber = index + 1;
            return (
              <li key={tab.id} className="flex-1">
                <button
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  disabled={!status.enabled}
                  className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition ${
                    isActive
                      ? "border-indigo-500 bg-indigo-50 shadow-sm"
                      : status.enabled
                      ? "border-slate-200 bg-white hover:border-indigo-200"
                      : "border-slate-100 bg-slate-50 text-slate-400 cursor-not-allowed"
                  } ${shouldPulse ? "ring-2 ring-offset-2 ring-orange-200 animate-pulse" : ""}`}
                >
                  <span
                    className={`mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
                      status.complete ? "bg-emerald-50 text-emerald-600 border border-emerald-200" : "border border-slate-300 text-slate-500"
                    }`}
                  >
                    {status.complete ? "✔" : stepNumber}
                  </span>
                  <div>
                    <p className={`text-sm font-semibold ${isActive ? "text-slate-900" : ""}`}>{tab.label}</p>
                    <p className="text-xs text-slate-500">{tab.description}</p>
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );

  const renderActiveTabContent = () => {
    switch (activeTab) {
      case "document":
        return renderDocumentTab();
      case "flow":
        return renderFlowTab();
      case "positions":
        return renderPositionsTab();
      case "dispatch":
        return renderDispatchTab();
      case "evidence":
        return renderEvidenceTab();
      default:
        return null;
    }
  };

  const renderModals = () => (
    <>
      {templateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-xl">
            <form onSubmit={handleSubmitTemplate} className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
                <h3 className="text-lg font-semibold text-slate-800">Salvar como modelo</h3>
                <button
                  type="button"
                  className="text-slate-500 transition hover:text-slate-700"
                  onClick={handleCloseTemplateModal}
                  disabled={templateSaving}
                >
                  ×
                </button>
              </div>
              <div className="px-6 space-y-3">
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Nome do modelo
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    value={templateName}
                    onChange={event => setTemplateName(event.target.value)}
                    required
                  />
                </label>
                <label className="flex flex-col text-xs font-semibold text-slate-600">
                  Descrição (opcional)
                  <input
                    className="mt-1 border rounded px-3 py-2 text-sm"
                    value={templateDescription}
                    onChange={event => setTemplateDescription(event.target.value)}
                  />
                </label>
                <p className="text-xs text-slate-500">
                  As etapas atuais do fluxo manual serão salvas para reutilização futura. Você ainda poderá ajustar o modelo ao aplicar.
                </p>
                <p className="text-xs text-slate-500">
                  O modelo ficará visível somente para as pessoas da sua área, conforme solicitado na especificação.
                </p>
              </div>
              <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
                <button type="button" className="btn btn-secondary btn-sm" onClick={handleCloseTemplateModal} disabled={templateSaving}>
                  Cancelar
                </button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={templateSaving || manualFlowPayload.length === 0}>
                  {templateSaving ? "Salvando..." : "Salvar modelo"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {certificateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <h3 className="text-lg font-semibold text-slate-800">Selecionar certificado</h3>
              <button type="button" className="text-slate-500 transition hover:text-slate-700" onClick={handleCloseCertificateModal}>
                ×
              </button>
            </div>
            <div className="px-6 py-4 space-y-3">
              {certificatesLoading ? (
                <p className="text-sm text-slate-500">Carregando certificados do agente...</p>
              ) : certificatesError ? (
                <p className="text-sm text-rose-600">{certificatesError}</p>
              ) : certificates.length === 0 ? (
                <p className="text-sm text-slate-500">Nenhum certificado com chave privada foi encontrado nesta máquina.</p>
              ) : (
                <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                  {certificates.map(cert => (
                    <label
                      key={cert.index}
                      className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2 ${
                        selectedCertificateIndex === cert.index ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="radio"
                        className="mt-1"
                        name="selected-certificate"
                        value={cert.index}
                        checked={selectedCertificateIndex === cert.index}
                        onChange={() => setSelectedCertificateIndex(cert.index)}
                      />
                      <div className="text-sm text-slate-700">
                        <p className="font-semibold">{cert.subject}</p>
                        <p className="text-xs text-slate-500">Emissor: {cert.issuer}</p>
                        {cert.serial_number && <p className="text-xs text-slate-500">Série: {cert.serial_number}</p>}
                        {cert.thumbprint && <p className="text-xs text-slate-500">Thumbprint: {cert.thumbprint}</p>}
                      </div>
                    </label>
                  ))}
                </div>
              )}
              <p className="text-xs text-slate-500">
                O certificado deve estar instalado neste computador e habilitado para assinatura digital.
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleCloseCertificateModal}>
                Cancelar
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={
                  certificatesLoading || certificates.length === 0 || selectedCertificateIndex === null || signing
                }
                onClick={handleConfirmCertificateSelection}
              >
                {signing ? "Processando..." : "Assinar agora"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );

  if (standaloneView && !selectedDocument) {
    return (
      <div className={wrapperClassName}>
        {headerContent}
        {limitBanner}
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
          {standaloneError ?? (standaloneLoading ? "Carregando documento selecionado..." : "Preparando painel do documento...")}
        </div>
        {renderModals()}
      </div>
    );
  }

  if (standaloneView || focusMode) {
    const focusedWrapperClass = standaloneView ? wrapperClassName : "mx-auto flex max-w-6xl flex-col gap-6";
    return (
      <div className={focusedWrapperClass}>
        {standaloneView ? headerContent : null}
        {standaloneView && limitBanner}
        {!standaloneView && limitBanner}
        {renderTabHeader(true)}
        <div className="space-y-6">{renderActiveTabContent()}</div>
        {renderModals()}
      </div>
    );
  }

  return (
    <div className={wrapperClassName}>
      {headerContent}
      {!standaloneView && limitBanner}
      {!standaloneView && onCreateNew && (
        <div className="flex justify-end">
          <button type="button" className="btn btn-primary btn-sm" onClick={onCreateNew}>
            Novo documento
          </button>
        </div>
      )}
      {!areaReady && !standaloneView && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Selecione uma area para visualizar e criar documentos.
        </div>
      )}
      {renderTabHeader(false)}
      <div className="space-y-6 mt-2">{renderActiveTabContent()}</div>
      {renderModals()}
    </div>
  );
}



