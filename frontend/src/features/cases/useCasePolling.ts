import { useEffect, useRef } from "react";
import type { AuthStatus } from "../../shared/types/api";

interface UseCasePollingOptions {
  auth: AuthStatus | null;
  hasActiveJobs: boolean;
  selectedId: string;
  refresh: () => void | Promise<void>;
  loadDiagnostics: (caseId: string, quiet?: boolean) => void | Promise<void>;
}

export function useCasePolling({ auth, hasActiveJobs, selectedId, refresh, loadDiagnostics }: UseCasePollingOptions) {
  const refreshRef = useRef(refresh);
  const loadDiagnosticsRef = useRef(loadDiagnostics);

  useEffect(() => {
    refreshRef.current = refresh;
    loadDiagnosticsRef.current = loadDiagnostics;
  }, [refresh, loadDiagnostics]);

  useEffect(() => {
    if (auth === null || (auth.enabled && !auth.authenticated) || !hasActiveJobs) return;
    const timer = window.setInterval(() => {
      void refreshRef.current();
      if (selectedId) {
        void loadDiagnosticsRef.current(selectedId, true);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [auth, hasActiveJobs, selectedId]);
}
