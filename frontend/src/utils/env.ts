export const resolveApiBaseUrl = (): string => {
  return import.meta.env.VITE_API_BASE_URL;
};