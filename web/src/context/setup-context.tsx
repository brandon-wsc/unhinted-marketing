import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { apiGetSetupStatus, type DeploymentMode, type SetupStatus } from "@/features/setup/api";
import { DEPLOYMENT_MODE } from "@/lib/deployment";

type SetupContextValue = {
  /** Null until the first fetch resolves (or fails). */
  status: SetupStatus | null;
  loading: boolean;
  /** Backend deployment mode wins over the baked Vite flag (ADR 0023). */
  deploymentMode: DeploymentMode;
  refresh: () => Promise<void>;
};

const SetupContext = createContext<SetupContextValue | null>(null);

export function SetupProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setStatus(await apiGetSetupStatus());
    } catch {
      // Status unknown — treat as no setup requirement rather than blocking boot.
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({
      status,
      loading,
      deploymentMode: status?.deployment_mode ?? DEPLOYMENT_MODE,
      refresh,
    }),
    [status, loading, refresh],
  );

  return <SetupContext.Provider value={value}>{children}</SetupContext.Provider>;
}

export function useSetup() {
  const ctx = useContext(SetupContext);
  if (!ctx) throw new Error("useSetup must be used within SetupProvider");
  return ctx;
}
