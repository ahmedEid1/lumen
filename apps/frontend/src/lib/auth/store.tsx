"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Auth } from "@/lib/api/endpoints";
import type { UserOut } from "@/lib/api/types";

type AuthState = {
  user: UserOut | null;
  token: string | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: { email: string; password: string; full_name: string }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await Auth.refresh();
      setUser(r.user);
      setToken(r.access_token);
    } catch {
      setUser(null);
      setToken(null);
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setReady(true));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await Auth.login({ email, password });
    setUser(r.user);
    setToken(r.access_token);
  }, []);

  const register = useCallback(
    async (input: { email: string; password: string; full_name: string }) => {
      await Auth.register(input);
      await login(input.email, input.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await Auth.logout();
    } finally {
      setUser(null);
      setToken(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, token, ready, login, register, logout, refresh }),
    [user, token, ready, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
