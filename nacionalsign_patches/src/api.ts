import axios from 'axios';

type Maybe<T> = T | null | undefined;

const apiBase = (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000';
const mockFlag = (import.meta as any).env?.VITE_MOCK ?? (import.meta as any).env?.VITE_USE_MOCKS;
const isMock = String(mockFlag ?? '').toLowerCase() === '1' || String(mockFlag ?? '').toLowerCase() === 'true';

export const api = axios.create({
  baseURL: apiBase,
  headers: { 'Content-Type': 'application/json' },
});

let authToken: string | null = null;
export const TOKEN_STORAGE_KEY = 'nacionalsign.token';

const readTokenFromStorage = (): string | null => {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
};

api.interceptors.request.use(config => {
  const headers = config.headers ?? {};
  const current = (headers as any).Authorization ?? (headers as any).authorization;
  if (!current) {
    const token = authToken ?? readTokenFromStorage();
    if (token) {
      if (typeof (headers as any).set === 'function') {
        (headers as any).set('Authorization', `Bearer ${token}`);
      } else {
        (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
      }
    }
  }
  return config;
});

export const setAuthToken = (token?: string) => {
  authToken = token ?? null;
  if (authToken) {
    api.defaults.headers.common.Authorization = `Bearer ${authToken}`;
  } else {
    delete api.defaults.headers.common.Authorization;
  }
};

export const getAuthToken = () => authToken;

const compactParams = (params: Record<string, unknown>) =>
  Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''));

const mockId = () => (typeof crypto !== 'undefined' && (crypto as any).randomUUID ? (crypto as any).randomUUID() : Math.random().toString(36).slice(2, 10));

export interface Usage {
  tenant_id?: string;
  period_start?: string;
  period_end?: string;
  documents_used: number;
  documents_quota?: number | null;
  users_used: number;
  users_quota?: number | null;
  documents_percent?: number | null;
  users_percent?: number | null;
  near_limit?: boolean;
  message?: string | null;
}

export interface DashboardMetrics {
  pending_for_user: number;
  to_sign: number;
  signed_in_area: number;
  pending_in_area: number;
}

export interface SigningCertificate {
  index: number;
  subject: string;
  issuer: string;
  serial_number?: string | null;
  thumbprint?: string | null;
  not_before?: string | null;
  not_after?: string | null;
}

export interface SignerShareLink {
  token: string;
  url: string;
}

export interface PublicSignature {
  document_name: string;
  signer_name: string;
  status: string;
  expires_at?: string | null;
  can_sign: boolean;
  reason?: string | null;
  requires_email_confirmation: boolean;
  requires_phone_confirmation: boolean;
  supports_certificate: boolean;
  requires_certificate: boolean;
}

export interface PublicSignatureActionPayload {
  action: 'sign' | 'refuse';
  reason?: string | null;
  typed_name?: string | null;
  signature_image?: string | null;
  signature_image_mime?: string | null;
  signature_image_name?: string | null;
  consent?: boolean | null;
  consent_text?: string | null;
  consent_version?: string | null;
  confirm_email?: string | null;
  confirm_phone_last4?: string | null;
  certificate_subject?: string | null;
  certificate_issuer?: string | null;
  certificate_serial?: string | null;
  certificate_thumbprint?: string | null;
  signature_protocol?: string | null;
  signature_type?: string | null;
  signature_authentication?: string | null;
  signed_pdf?: string | null;
  signed_pdf_name?: string | null;
  signed_pdf_mime?: string | null;
  signed_pdf_digest?: string | null;
}

export interface Plan {
  id: string;
  name: string;
  document_quota: number;
  user_quota: number;
  price_monthly: number;
  price_yearly: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string | null;
}

export interface Subscription {
  id: string;
  tenant_id: string;
  plan_id: string;
  status: string;
  valid_until: string | null;
  auto_renew: boolean;
  created_at?: string;
  updated_at?: string | null;
}

export interface Invoice {
  id: string;
  tenant_id: string;
  gateway: string;
  external_id: string;
  amount_cents: number;
  due_date: string;
  status: string;
  paid_at: string | null;
  retry_count?: number | null;
  last_attempt_at?: string | null;
  next_attempt_at?: string | null;
  tax_id?: string | null;
  receipt_url?: string | null;
  fiscal_note_number?: string | null;
  created_at?: string;
  updated_at?: string | null;
}

export interface CustomerSummary {
  id: string;
  corporate_name: string;
  trade_name: string | null;
  cnpj: string;
  responsible_name: string;
  responsible_email: string | null;
  responsible_phone: string | null;
  plan_id: string | null;
  document_quota: number | null;
  documents_used: number;
  tenant_id: string | null;
  activation_token: string | null;
  contract_file_name?: string | null;
  contract_uploaded_at?: string | null;
  contract_download_url?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface CustomerCreatePayload {
  corporate_name: string;
  trade_name?: string | null;
  cnpj: string;
  responsible_name: string;
  responsible_email?: string | null;
  responsible_phone?: string | null;
  plan_id?: string | null;
  document_quota?: number | null;
  is_active?: boolean;
}

export interface CustomerUpdatePayload {
  corporate_name?: string;
  trade_name?: string | null;
  cnpj?: string;
  responsible_name?: string;
  responsible_email?: string | null;
  responsible_phone?: string | null;
  plan_id?: string | null;
  document_quota?: number | null;
  documents_used?: number;
  tenant_id?: string | null;
  is_active?: boolean;
}

export interface CustomerActivationLink {
  activation_token: string;
  activation_url: string;
}

export interface UserMe {
  id: string;
  tenant_id: string;
  default_area_id: string | null;
  email: string;
  cpf: string;
  full_name: string;
  phone_number: string | null;
  profile: 'admin' | 'area_manager' | 'user' | 'owner' | string;
  is_active: boolean;
  two_factor_enabled: boolean;
  last_login_at: string | null;
  created_at?: string;
  updated_at?: string | null;
}

export interface UserSummary extends UserMe {
  created_at: string;
  updated_at: string | null;
}

export interface UserCreatePayload {
  email: string;
  cpf: string;
  full_name: string;
  phone_number?: string | null;
  password: string;
  default_area_id?: string | null;
  profile?: 'admin' | 'area_manager' | 'user';
}

export interface UserUpdatePayload {
  full_name?: string;
  phone_number?: string | null;
  password?: string;
  two_factor_enabled?: boolean;
  is_active?: boolean;
  profile?: 'admin' | 'area_manager' | 'user';
  default_area_id?: string | null;
}

export interface UserSettingsPayload {
  full_name?: string;
  phone_number?: string | null;
  password?: string;
  two_factor_enabled?: boolean;
  default_area_id?: string | null;
}

export interface Area {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at?: string;
  updated_at?: string | null;
}

export interface AreaCreatePayload {
  name: string;
  description?: string | null;
}

export interface AreaUpdatePayload {
  name?: string | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface DocumentRecord {
  id: string;
  tenant_id: string;
  area_id: string;
  name: string;
  status: string;
  current_version_id: string | null;
  created_by_id: string;
  created_at: string;
  updated_at: string | null;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  storage_path: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by_id: string;
  created_at: string;
  updated_at: string | null;
  fields?: DocumentField[];
}

export interface DocumentField {
  id: string;
  document_id: string;
  version_id: string;
  role: string;
  field_type: string;
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string | null;
  required: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface DocumentFieldPayload {
  role: string;
  field_type: string;
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
  label?: string | null;
  required?: boolean;
}

export interface DocumentParty {
  id: string;
  document_id: string;
  full_name: string;
  email: string | null;
  cpf: string | null;
  role: string;
  order_index: number;
  two_factor_type: string | null;
  status: string;
  phone_number: string | null;
  notification_channel: string;
  company_name: string | null;
  company_tax_id: string | null;
  require_cpf: boolean;
  require_email: boolean;
  require_phone: boolean;
  allow_typed_name: boolean;
  allow_signature_image: boolean;
  allow_signature_draw: boolean;
  /** NEW: força uso de certificado digital para este participante */
  requires_certificate?: boolean | null;
  /** Data/hora da assinatura (se já assinou) */
  signed_at?: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface DocumentPartyPayload {
  full_name?: string;
  email?: string | null;
  cpf?: string | null;
  phone_number?: string | null;
  role?: string;
  order_index?: number;
  two_factor_type?: string | null;
  notification_channel?: string | null;
  require_cpf?: boolean;
  require_email?: boolean;
  require_phone?: boolean;
  allow_typed_name?: boolean;
  allow_signature_image?: boolean;
  allow_signature_draw?: boolean;
  company_name?: string | null;
  company_tax_id?: string | null;
  /** NEW: força uso de certificado digital para este participante */
  requires_certificate?: boolean | null;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  event_type: string;
  actor_id: string | null;
  actor_role: string | null;
  document_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  details: Record<string, unknown> | null;
}

export interface AuditEventList {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface WorkflowTemplateStep {
  order: number;
  role: string;
  action: string;
  execution: 'sequential' | 'parallel';
  deadline_hours: number | null;
  notification_channel?: string | null;
}

export interface WorkflowTemplate {
  id: string;
  tenant_id: string;
  area_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  steps: WorkflowTemplateStep[];
  created_at: string;
  updated_at: string | null;
}

export interface DocumentSummary {
  id: string;
  name: string;
  area_id: string;
  area_name?: string;
  status: string;
}

export interface TemplateIndexResponse {
  templates: WorkflowTemplate[];
  areas: { id: string; name: string }[];
  documents: DocumentSummary[];
}

export interface WorkflowDispatchPayload {
  template_id?: string | null;
  deadline_at?: string | null;
  steps?: WorkflowTemplateStep[];
}

export interface WorkflowRead {
  id: string;
  document_id: string;
  template_id: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface SignAgentAttempt {
  id: string;
  document_id: string;
  version_id: string;
  actor_id: string | null;
  actor_role: string | null;
  payload: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  protocol: string | null;
  agent_details: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
}

export interface SignAgentResponse {
  version_id: string;
  document_id: string;
  protocol: string;
  signature_type?: string | null;
  authentication?: string | null;
}

export interface SignAgentErrorDetail {
  error?: string;
  attempt_id?: string;
  agent_details?: Record<string, unknown> | null;
}

export const isMockEnvironment = isMock;

// ===== Billing =====

export const fetchUsage = async (): Promise<Usage> => {
  if (isMock) {
    return {
      tenant_id: 'mock-tenant',
      period_start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
      period_end: new Date().toISOString(),
      documents_used: 5,
      documents_quota: 20,
      users_used: 3,
      users_quota: 10,
      documents_percent: 0.25,
      users_percent: 0.3,
      near_limit: false,
      message: null,
    };
  }
  const response = await api.get('/api/v1/billing/usage');
  return response.data as Usage;
};

export const fetchDashboardMetrics = async (params?: { area_id?: string | null }): Promise<DashboardMetrics> => {
  if (isMock) {
    return {
      pending_for_user: 3,
      to_sign: 2,
      signed_in_area: 12,
      pending_in_area: 5,
    };
  }
  const response = await api.get('/api/v1/dashboard/metrics', {
    params: compactParams({ area_id: params?.area_id }),
  });
  return response.data as DashboardMetrics;
};

export const fetchPlans = async (): Promise<Plan[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        id: 'plan-basic',
        name: 'Básico',
        document_quota: 20,
        user_quota: 3,
        price_monthly: 4900,
        price_yearly: 49000,
        is_active: true,
        created_at: now,
        updated_at: now,
      },
      {
        id: 'plan-pro',
        name: 'Pro',
        document_quota: 100,
        user_quota: 10,
        price_monthly: 19900,
        price_yearly: 199000,
        is_active: true,
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get('/api/v1/billing/plans');
  return response.data as Plan[];
};

export const fetchSubscription = async (): Promise<Subscription | null> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      tenant_id: mockId(),
      plan_id: 'plan-basic',
      status: 'active',
      valid_until: now,
      auto_renew: true,
      created_at: now,
      updated_at: now,
    };
  }
  try {
    const response = await api.get('/api/v1/billing/subscription');
    return response.data as Subscription;
  } catch (error: any) {
    if (error?.response?.status === 404) {
      return null;
    }
    throw error;
  }
};

export const createOrUpdateSubscription = async (plan_id: string, payment_method_token: string): Promise<Subscription> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      tenant_id: mockId(),
      plan_id,
      status: 'active',
      valid_until: now,
      auto_renew: true,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post('/api/v1/billing/subscription', { plan_id, payment_method_token });
  return response.data as Subscription;
};

export const fetchInvoices = async (): Promise<Invoice[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        id: mockId(),
        tenant_id: mockId(),
        gateway: 'manual',
        external_id: 'manual-001',
        amount_cents: 4900,
        due_date: now,
        status: 'paid',
        paid_at: now,
        retry_count: 0,
        last_attempt_at: now,
        next_attempt_at: null,
        tax_id: null,
        receipt_url: null,
        fiscal_note_number: null,
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get('/api/v1/billing/invoices');
  return response.data as Invoice[];
};

export const retryInvoice = async (invoiceId: string): Promise<Invoice> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: invoiceId,
      tenant_id: mockId(),
      gateway: 'manual',
      external_id: 'manual-001',
      amount_cents: 4900,
      due_date: now,
      status: 'processing',
      paid_at: null,
      retry_count: 1,
      last_attempt_at: now,
      next_attempt_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      tax_id: null,
      receipt_url: null,
      fiscal_note_number: null,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post(`/api/v1/billing/invoices/${invoiceId}/retry`);
  return response.data as Invoice;
};

export const seedDefaultPlans = async (): Promise<Plan[]> => {
  if (isMock) {
    return fetchPlans();
  }
  const response = await api.post('/api/v1/billing/seed-plans');
  return response.data as Plan[];
};

// ===== Customers =====

export const fetchCustomers = async (): Promise<CustomerSummary[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        id: mockId(),
        corporate_name: 'Empresa Exemplo LTDA',
        trade_name: 'Empresa Exemplo',
        cnpj: '12345678000190',
        responsible_name: 'Maria Responsável',
        responsible_email: 'maria@example.com',
        responsible_phone: '+55 11 98888-0000',
        plan_id: 'plan-basic',
        document_quota: 20,
        documents_used: 5,
        tenant_id: null,
        activation_token: mockId(),
        contract_file_name: null,
        contract_uploaded_at: null,
        contract_download_url: null,
        is_active: true,
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get('/api/v1/customers');
  return response.data as CustomerSummary[];
};

export const createCustomer = async (payload: CustomerCreatePayload): Promise<CustomerSummary> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      corporate_name: payload.corporate_name,
      trade_name: payload.trade_name ?? null,
      cnpj: payload.cnpj,
      responsible_name: payload.responsible_name,
      responsible_email: payload.responsible_email ?? null,
      responsible_phone: payload.responsible_phone ?? null,
      plan_id: payload.plan_id ?? null,
      document_quota: payload.document_quota ?? null,
      documents_used: 0,
      tenant_id: null,
      activation_token: mockId(),
      contract_file_name: null,
      contract_uploaded_at: null,
      contract_download_url: null,
      is_active: payload.is_active ?? true,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post('/api/v1/customers', payload);
  return response.data as CustomerSummary;
};

export const updateCustomer = async (customerId: string, payload: CustomerUpdatePayload): Promise<CustomerSummary> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      ...(await createCustomer({
        corporate_name: payload.corporate_name ?? 'Cliente Mock',
        cnpj: payload.cnpj ?? '00000000000000',
        responsible_name: payload.responsible_name ?? 'Responsável Mock',
      })),
      id: customerId,
      trade_name: payload.trade_name ?? null,
      plan_id: payload.plan_id ?? null,
      document_quota: payload.document_quota ?? null,
      documents_used: payload.documents_used ?? 0,
      is_active: payload.is_active ?? true,
      updated_at: now,
    };
  }
  const response = await api.patch(`/api/v1/customers/${customerId}`, payload);
  return response.data as CustomerSummary;
};

export const generateCustomerActivationLink = async (customerId: string): Promise<CustomerActivationLink> => {
  if (isMock) {
    const token = mockId();
    return {
      activation_token: token,
      activation_url: `https://example.com/activate/${token}`,
    };
  }
  const response = await api.post(`/api/v1/customers/${customerId}/generate-link`);
  return response.data as CustomerActivationLink;
};

// ===== Users & Tenants =====

export const fetchMe = async (): Promise<UserMe> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      tenant_id: mockId(),
      default_area_id: null,
      email: 'owner@example.com',
      cpf: '12345678901',
      full_name: 'Usuário Mock',
      phone_number: '+55 11 90000-0000',
      profile: 'owner',
      is_active: true,
      two_factor_enabled: false,
      last_login_at: now,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.get('/api/v1/users/me');
  return response.data as UserMe;
};

export const updateMySettings = async (payload: UserSettingsPayload): Promise<UserMe> => {
  if (isMock) {
    return { ...(await fetchMe()), ...payload } as UserMe;
  }
  const response = await api.patch('/api/v1/users/me', payload);
  return response.data as UserMe;
};

export const fetchAreas = async (): Promise<Area[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      { id: mockId(), tenant_id: mockId(), name: 'Geral', description: 'Área padrão', is_active: true, created_at: now, updated_at: now },
      { id: mockId(), tenant_id: mockId(), name: 'Financeiro', description: null, is_active: true, created_at: now, updated_at: now },
    ];
  }
  const response = await api.get('/api/v1/tenants/areas');
  return response.data as Area[];
};

export const createArea = async (payload: AreaCreatePayload): Promise<Area> => {
  if (isMock) {
    const now = new Date().toISOString();
    return { id: mockId(), tenant_id: mockId(), name: payload.name, description: payload.description ?? null, is_active: true, created_at: now, updated_at: now };
  }
  const response = await api.post('/api/v1/tenants/areas', payload);
  return response.data as Area;
};

export const updateArea = async (areaId: string, payload: AreaUpdatePayload): Promise<Area> => {
  if (isMock) {
    const base = (await fetchAreas())[0];
    return { ...base, id: areaId, ...payload, updated_at: new Date().toISOString() } as Area;
  }
  const response = await api.patch(`/api/v1/tenants/areas/${areaId}`, payload);
  return response.data as Area;
};

export const deactivateArea = async (areaId: string): Promise<void> => {
  if (isMock) {
    return;
  }
  await api.delete(`/api/v1/tenants/areas/${areaId}`);
};

export const fetchUsers = async (): Promise<UserSummary[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        ...(await fetchMe()),
        id: mockId(),
        email: 'admin@example.com',
        profile: 'admin',
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get('/api/v1/users');
  return response.data as UserSummary[];
};

export const createUserAccount = async (payload: UserCreatePayload): Promise<UserSummary> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      ...(await fetchMe()),
      id: mockId(),
      email: payload.email,
      cpf: payload.cpf,
      full_name: payload.full_name,
      phone_number: payload.phone_number ?? null,
      profile: payload.profile ?? 'user',
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post('/api/v1/users', payload);
  return response.data as UserSummary;
};

export const updateUserAccount = async (userId: string, payload: UserUpdatePayload): Promise<UserSummary> => {
  if (isMock) {
    return { ...(await fetchMe()), id: userId, ...payload } as UserSummary;
  }
  const response = await api.patch(`/api/v1/users/${userId}`, payload);
  return response.data as UserSummary;
};

// ===== Documents =====

export const fetchDocuments = async (areaId?: string): Promise<DocumentRecord[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        id: mockId(),
        tenant_id: mockId(),
        area_id: areaId ?? mockId(),
        name: 'Contrato Mock',
        status: 'draft',
        current_version_id: null,
        created_by_id: mockId(),
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get('/api/v1/documents', { params: compactParams({ area_id: areaId }) });
  return response.data as DocumentRecord[];
};

export const fetchDocument = async (documentId: string): Promise<DocumentRecord> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: documentId,
      tenant_id: mockId(),
      area_id: mockId(),
      name: 'Contrato Assinado Mock',
      status: 'signed',
      current_version_id: mockId(),
      created_by_id: mockId(),
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.get(`/api/v1/documents/${documentId}`);
  return response.data as DocumentRecord;
};

export const createDocumentRecord = async (payload: { name: string; area_id: string }): Promise<DocumentRecord> => {
  if (isMock) {
    return fetchDocuments(payload.area_id).then(list => ({ ...list[0], name: payload.name }));
  }
  const response = await api.post('/api/v1/documents', payload);
  return response.data as DocumentRecord;
};

export const uploadDocumentVersion = async (documentId: string, file: File): Promise<DocumentVersion> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      document_id: documentId,
      storage_path: 'mock/path.pdf',
      original_filename: file.name,
      mime_type: file.type || 'application/pdf',
      size_bytes: file.size,
      sha256: mockId(),
      uploaded_by_id: mockId(),
      created_at: now,
      updated_at: now,
      fields: [],
    };
  }
  const form = new FormData();
  form.append('file', file);
  const response = await api.post(`/api/v1/documents/${documentId}/versions`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data as DocumentVersion;
};

export const fetchDocumentVersion = async (documentId: string, versionId: string): Promise<DocumentVersion> => {
  if (isMock) {
    return {
      id: versionId,
      document_id: documentId,
      storage_path: 'mock/path.pdf',
      original_filename: 'mock.pdf',
      mime_type: 'application/pdf',
      size_bytes: 1024,
      sha256: mockId(),
      uploaded_by_id: mockId(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      fields: [],
    };
  }
  const response = await api.get(`/api/v1/documents/${documentId}/versions/${versionId}`);
  return response.data as DocumentVersion;
};

export const createDocumentField = async (documentId: string, versionId: string, payload: DocumentFieldPayload): Promise<DocumentField> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      document_id: documentId,
      version_id: versionId,
      role: payload.role,
      field_type: payload.field_type,
      page: payload.page,
      x: payload.x,
      y: payload.y,
      width: payload.width,
      height: payload.height,
      label: payload.label ?? null,
      required: payload.required ?? true,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post(`/api/v1/documents/${documentId}/versions/${versionId}/fields`, payload);
  return response.data as DocumentField;
};

export const deleteDocumentField = async (documentId: string, versionId: string, fieldId: string): Promise<void> => {
  if (isMock) return;
  await api.delete(`/api/v1/documents/${documentId}/versions/${versionId}/fields/${fieldId}`);
};

export const fetchDocumentParties = async (documentId: string): Promise<DocumentParty[]> => {
  if (isMock) {
    const now = new Date().toISOString();
    return [
      {
        id: mockId(),
        document_id: documentId,
        full_name: 'João Assinante',
        email: 'joao@example.com',
        cpf: '12345678901',
        role: 'signer',
        order_index: 1,
        two_factor_type: null,
        status: 'signed',
        phone_number: '+55 11 98888-0000',
        notification_channel: 'email',
        company_name: 'Empresa X',
        company_tax_id: '11222333000199',
        require_cpf: true,
        require_email: true,
        require_phone: false,
        allow_typed_name: true,
        allow_signature_image: true,
        allow_signature_draw: true,
        requires_certificate: false,
        signed_at: now,
        created_at: now,
        updated_at: now,
      },
      {
        id: mockId(),
        document_id: documentId,
        full_name: 'Maria Certificada',
        email: 'maria@example.com',
        cpf: '98765432100',
        role: 'approver',
        order_index: 2,
        two_factor_type: null,
        status: 'signed',
        phone_number: '+55 21 97777-0000',
        notification_channel: 'email',
        company_name: 'Empresa Y',
        company_tax_id: '00998877000166',
        require_cpf: true,
        require_email: true,
        require_phone: false,
        allow_typed_name: false,
        allow_signature_image: false,
        allow_signature_draw: false,
        requires_certificate: true,
        signed_at: now,
        created_at: now,
        updated_at: now,
      },
    ];
  }
  const response = await api.get(`/api/v1/documents/${documentId}/parties`);
  return response.data as DocumentParty[];
};

export const createDocumentParty = async (documentId: string, payload: DocumentPartyPayload): Promise<DocumentParty> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      ...(await fetchDocumentParties(documentId))[0],
      id: mockId(),
      full_name: payload.full_name ?? 'Novo participante',
      email: payload.email ?? 'novo@example.com',
      requires_certificate: payload.requires_certificate ?? false,
      updated_at: now,
    };
  }
  const response = await api.post(`/api/v1/documents/${documentId}/parties`, payload);
  return response.data as DocumentParty;
};

export const updateDocumentParty = async (documentId: string, partyId: string, payload: DocumentPartyPayload): Promise<DocumentParty> => {
  if (isMock) {
    return {
      ...(await fetchDocumentParties(documentId))[0],
      id: partyId,
      ...payload,
    } as DocumentParty;
  }
  const response = await api.patch(`/api/v1/documents/${documentId}/parties/${partyId}`, payload);
  return response.data as DocumentParty;
};

export const deleteDocumentParty = async (documentId: string, partyId: string): Promise<void> => {
  if (isMock) return;
  await api.delete(`/api/v1/documents/${documentId}/parties/${partyId}`);
};

export const fetchAuditEvents = async (params: { documentId?: string; eventType?: string; page?: number; pageSize?: number }): Promise<AuditEventList> => {
  if (isMock) {
    return {
      items: [
        {
          id: mockId(),
          created_at: new Date().toISOString(),
          event_type: params.eventType ?? 'document_signed',
          actor_id: mockId(),
          actor_role: 'signer',
          document_id: params.documentId ?? mockId(),
          ip_address: '127.0.0.1',
          user_agent: 'mock-agent',
          details: { info: 'Assinatura concluída' },
        },
      ],
      total: 1,
      page: 1,
      page_size: params.pageSize ?? 50,
    };
  }
  const response = await api.get('/api/v1/audit/events', {
    params: compactParams({
      document_id: params.documentId,
      event_type: params.eventType,
      page: params.page,
      page_size: params.pageSize,
    }),
  });
  return response.data as AuditEventList;
};

export const dispatchWorkflow = async (documentId: string, payload: WorkflowDispatchPayload): Promise<WorkflowRead> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      document_id: documentId,
      template_id: payload.template_id ?? null,
      status: 'pending',
      started_at: now,
      completed_at: null,
      created_at: now,
      updated_at: now,
    };
  }
  const response = await api.post(`/api/v1/workflows/documents/${documentId}`, payload);
  return response.data as WorkflowRead;
};

export const resendDocumentNotifications = async (documentId: string): Promise<{ notified: number }> => {
  if (isMock) {
    return { notified: 0 };
  }
  const response = await api.post(`/api/v1/workflows/documents/${documentId}/resend`);
  return response.data as { notified: number };
};

export const fetchSigningCertificates = async (): Promise<SigningCertificate[]> => {
  if (isMock) {
    return [
      {
        index: 0,
        subject: 'CN=Certificado Mock',
        issuer: 'Autoridade Mock',
        serial_number: '123456',
        thumbprint: 'ABCDEF',
      },
    ];
  }
  const response = await api.get('/api/v1/documents/signing-agent/certificates');
  return response.data as SigningCertificate[];
};

export const issueSignerShareLink = async (partyId: string): Promise<SignerShareLink> => {
  if (isMock) {
    return {
      token: 'mock-token',
      url: `https://example.com/public/signatures/mock-token`,
    };
  }
  const response = await api.post(`/api/v1/workflows/signatures/${partyId}/share-link`);
  return response.data as SignerShareLink;
};

export const fetchPublicSignature = async (token: string): Promise<PublicSignature> => {
  const response = await api.get(`/public/signatures/${encodeURIComponent(token)}`);
  return response.data as PublicSignature;
};

export const actOnPublicSignature = async (token: string, payload: PublicSignatureActionPayload): Promise<PublicSignature> => {
  const response = await api.post(`/public/signatures/${encodeURIComponent(token)}`, payload);
  return response.data as PublicSignature;
};

// ===== Signing agent =====

export const signDocumentVersionWithAgent = async (
  documentId: string,
  versionId: string,
  payload: Record<string, unknown>,
): Promise<SignAgentResponse> => {
  if (isMock) {
    return {
      version_id: versionId,
      document_id: documentId,
      protocol: 'MOCK-123',
      signature_type: 'mock',
      authentication: null,
    };
  }
  const response = await api.post(`/api/v1/documents/${documentId}/versions/${versionId}/sign-agent`, payload);
  return response.data as SignAgentResponse;
};

export const retrySignDocumentVersionWithAgent = async (documentId: string, versionId: string): Promise<SignAgentResponse> => {
  if (isMock) {
    return {
      version_id: versionId,
      document_id: documentId,
      protocol: 'MOCK-RETRY',
      signature_type: 'mock',
      authentication: null,
    };
  }
  const response = await api.post(`/api/v1/documents/${documentId}/versions/${versionId}/sign-agent/retry`);
  return response.data as SignAgentResponse;
};

export const fetchLatestSignAgentAttempt = async (documentId: string, versionId: string): Promise<SignAgentAttempt | null> => {
  if (isMock) {
    const now = new Date().toISOString();
    return {
      id: mockId(),
      document_id: documentId,
      version_id: versionId,
      actor_id: mockId(),
      actor_role: 'admin',
      payload: { protocol: 'MOCK-123' },
      status: 'success',
      error_message: null,
      protocol: 'MOCK-123',
      agent_details: null,
      created_at: now,
      updated_at: now,
    };
  }
  try {
    const response = await api.get(`/api/v1/documents/${documentId}/versions/${versionId}/sign-agent/attempts/latest`);
    return response.data as SignAgentAttempt;
  } catch (error: any) {
    if (error?.response?.status === 404) {
      return null;
    }
    throw error;
  }
};

// ===== Templates =====

const templatesEndpoint = '/admin/templates';

const submitTemplateForm = async (form: URLSearchParams) => {
  await api.post(templatesEndpoint, form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
};

export const fetchTemplates = async (tenantId: Maybe<string>, areaId?: Maybe<string>): Promise<TemplateIndexResponse> => {
  if (!tenantId) {
    return { templates: [], areas: [], documents: [] };
  }
  if (isMock) {
    return {
      templates: [
        {
          id: mockId(),
          tenant_id: tenantId,
          area_id: areaId ?? mockId(),
          name: 'Fluxo Padrão',
          description: 'Template de exemplo',
          is_active: true,
          steps: [
            { order: 1, role: 'signer', action: 'sign', execution: 'sequential', deadline_hours: null, notification_channel: 'email' },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      areas: [{ id: areaId ?? mockId(), name: 'Geral' }],
      documents: [],
    };
  }
  const response = await api.get('/admin/templates', {
    params: compactParams({ tenant_id: tenantId, area_id: areaId }),
    headers: { Accept: 'application/json' },
  });
  return response.data as TemplateIndexResponse;
};

export const createTemplate = async (tenantId: string, payload: { area_id: string; name: string; description?: string; steps: WorkflowTemplateStep[] }) => {
  if (isMock) return;
  const form = new URLSearchParams();
  form.append('action', 'create');
  form.append('tenant_id', tenantId);
  form.append('area_id', payload.area_id);
  form.append('name', payload.name);
  if (payload.description) form.append('description', payload.description);
  form.append('steps_json', JSON.stringify(payload.steps));
  await submitTemplateForm(form);
};

export const updateTemplate = async (tenantId: string, templateId: string, payload: { name?: string; description?: string | null; steps?: WorkflowTemplateStep[] }, areaId?: string) => {
  if (isMock) return;
  const form = new URLSearchParams();
  form.append('action', 'update');
  form.append('tenant_id', tenantId);
  if (areaId) form.append('area_id', areaId);
  form.append('template_id', templateId);
  if (payload.name) form.append('name', payload.name);
  if (payload.description !== undefined) form.append('description', payload.description ?? '');
  if (payload.steps) form.append('steps_json', JSON.stringify(payload.steps));
  await submitTemplateForm(form);
};

export const toggleTemplate = async (tenantId: string, templateId: string, areaId?: string) => {
  if (isMock) return;
  const form = new URLSearchParams();
  form.append('action', 'toggle');
  form.append('tenant_id', tenantId);
  if (areaId) form.append('area_id', areaId);
  form.append('template_id', templateId);
  await submitTemplateForm(form);
};

export const duplicateTemplate = async (tenantId: string, templateId: string, name: string, targetAreaId?: string, areaId?: string) => {
  if (isMock) return;
  const form = new URLSearchParams();
  form.append('action', 'duplicate');
  form.append('tenant_id', tenantId);
  if (areaId) form.append('area_id', areaId);
  form.append('template_id', templateId);
  form.append('duplicate_name', name);
  if (targetAreaId) form.append('target_area_id', targetAreaId);
  await submitTemplateForm(form);
};

/** ========================
 *  NOVO: downloads pós-assinatura
 *  Endpoints sugeridos (ajuste se seu backend usar caminhos diferentes):
 *   - GET /api/v1/documents/:id/signed-artifacts  -> { pdf_url, p7s_urls[], has_digital_signature }
 *   - GET /api/v1/documents/:id/downloads/signed-package (responseType: blob zip)
 * ======================== */
export interface SignedArtifacts {
  pdf_url: string;                 // URL para baixar o PDF com marca d'água + protocolo
  p7s_urls: string[];              // URLs dos .p7s (pode ser vazio se não houver assinatura digital)
  has_digital_signature: boolean;  // true se houver ao menos 1 assinatura A1/A3
}

export const fetchSignedArtifacts = async (documentId: string): Promise<SignedArtifacts> => {
  if (isMock) {
    return {
      pdf_url: 'https://example.com/mock/signed.pdf',
      p7s_urls: [
        'https://example.com/mock/maria.p7s'
      ],
      has_digital_signature: true,
    };
  }
  const response = await api.get(`/api/v1/documents/${documentId}/signed-artifacts`);
  return response.data as SignedArtifacts;
};

export const downloadSignedPackage = async (documentId: string): Promise<Blob> => {
  if (isMock) {
    // simula um zip vazio
    return new Blob([new Uint8Array([80, 75, 3, 4])], { type: 'application/zip' });
  }
  const response = await api.get(`/api/v1/documents/${documentId}/downloads/signed-package`, {
    responseType: 'blob',
  });
  return response.data as Blob;
};

// ===== Auth =====

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export const login = async (email: string, password: string, otp?: string): Promise<LoginResponse> => {
  if (isMock) {
    return {
      access_token: 'mock-token',
      refresh_token: 'mock-refresh',
      token_type: 'bearer',
    };
  }
  const payload: Record<string, string> = { username: email, password };
  if (otp) payload.otp = otp;
  const response = await api.post('/api/v1/auth/login', payload);
  return response.data as LoginResponse;
};
