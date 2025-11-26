let cachedApiBaseUrl: string | null = null;

const normalizeBaseUrl = (value: string) => value.replace(/\/$/, "");
const DEFAULT_API_BASE = "http://localhost:8000";
const DEFAULT_DEV_API_PORT = "8000";
const DEV_PORTS = new Set(["5173", "4173"]);

export const resolveApiBaseUrl = (): string => {
  if (cachedApiBaseUrl) {
    return cachedApiBaseUrl;
  }

  const metaEnv = (import.meta as any)?.env;
  const envValue = typeof metaEnv?.VITE_API_BASE_URL === "string" ? metaEnv.VITE_API_BASE_URL.trim() : "";

  if (envValue) {
    cachedApiBaseUrl = normalizeBaseUrl(envValue);
    return cachedApiBaseUrl;
  }

  if (typeof window !== "undefined" && window.location) {
    const { origin, port, protocol, hostname } = window.location;
    if (!DEV_PORTS.has(port) && origin) {
      cachedApiBaseUrl = normalizeBaseUrl(origin);
      return cachedApiBaseUrl;
    }

    if (DEV_PORTS.has(port)) {
      const guessed = `${protocol}//${hostname}:${DEFAULT_DEV_API_PORT}`;
      cachedApiBaseUrl = normalizeBaseUrl(guessed);
      return cachedApiBaseUrl;
    }
  }

  cachedApiBaseUrl = DEFAULT_API_BASE;
  return cachedApiBaseUrl;
};
