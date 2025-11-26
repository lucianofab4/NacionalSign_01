import axios from "axios";

const DEFAULT_AGENT_BASE = "http://127.0.0.1:9250";
const REQUEST_TIMEOUT_MS = 8000;

export interface AgentCertificate {
  index: number;
  subject: string;
  issuer: string;
  serialNumber?: string;
  thumbprint?: string;
  notBefore?: string;
  notAfter?: string;
}

const agentClient = axios.create({
  timeout: REQUEST_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

export const resolveSigningAgentBaseUrl = (): string => {
  const envValue = (import.meta as any)?.env?.VITE_SIGNING_AGENT_BASE_URL;
  const normalized = (envValue && typeof envValue === "string" ? envValue.trim() : "") || DEFAULT_AGENT_BASE;
  return normalized.replace(/\/$/, "");
};

const buildAgentUrl = (path: string) => {
  const base = resolveSigningAgentBaseUrl();
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
};

const normalizeAgentError = (error: unknown): Error => {
  if (axios.isAxiosError(error)) {
    return new Error(error.message || "Não foi possível comunicar com o agente local.");
  }
  if (error instanceof Error) {
    return error;
  }
  return new Error("Falha desconhecida ao acessar o agente local.");
};

export const fetchLocalAgentCertificates = async (): Promise<AgentCertificate[]> => {
  try {
    const response = await agentClient.get(buildAgentUrl("/certificates"), {
      headers: { Accept: "application/json" },
    });
    const data = response.data;
    if (Array.isArray(data)) return data;
    if (data?.items && Array.isArray(data.items)) return data.items;
    return [];
  } catch (error) {
    throw normalizeAgentError(error);
  }
};

export const signPdfWithLocalAgent = async (payload: Record<string, unknown>): Promise<Record<string, any>> => {
  try {
    const response = await agentClient.post(buildAgentUrl("/sign/pdf"), payload);
    return response.data as Record<string, any>;
  } catch (error) {
    throw normalizeAgentError(error);
  }
};
