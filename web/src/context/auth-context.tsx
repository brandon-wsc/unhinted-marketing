import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  apiLogin,
  apiLogout,
  apiRefresh,
  apiRegister,
  type TokenResponse,
  type User,
} from "@/lib/api";
import { rememberFromAuthUser } from "@/lib/remembered-user";

type AuthContextValue = {
  user: User | null;
  accessToken: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    display_name: string;
    organization_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function applySession(
  setAccessToken: (t: string | null) => void,
  setUser: (u: User | null) => void,
  data: TokenResponse,
) {
  setAccessToken(data.access_token);
  setUser(data.user);
  rememberFromAuthUser(data.user);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiRefresh();
        if (!cancelled) applySession(setAccessToken, setUser, data);
      } catch {
        if (!cancelled) {
          setAccessToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiLogin({ email, password });
    applySession(setAccessToken, setUser, data);
  }, []);

  const register = useCallback(
    async (input: {
      email: string;
      password: string;
      display_name: string;
      organization_name?: string;
    }) => {
      const data = await apiRegister(input);
      applySession(setAccessToken, setUser, data);
    },
    [],
  );

  const logout = useCallback(async () => {
    await apiLogout();
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, accessToken, loading, login, register, logout }),
    [user, accessToken, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export async function fetchWithAuth(
  accessToken: string | null,
  input: RequestInfo,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(input, { ...init, headers, credentials: "include" });
  if (res.status === 401 && accessToken) {
    try {
      const refreshed = await apiRefresh();
      headers.set("Authorization", `Bearer ${refreshed.access_token}`);
      return fetch(input, { ...init, headers, credentials: "include" });
    } catch {
      return res;
    }
  }
  return res;
}
