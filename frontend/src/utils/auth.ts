export const TOKEN_STORAGE_KEY = "nacionalsign.token";

// Salva token no localStorage
export const saveToken = (token: string) => {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
};

// Lê token do localStorage
export const getToken = (): string | null => {
  if (typeof window !== "undefined") {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  }
  return null;
};

// Remove token (logout)
export const removeToken = () => {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
};
