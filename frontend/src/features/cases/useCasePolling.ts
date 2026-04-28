import { useEffect } from "react";
import type { AuthStatus } from "../../shared/types/api";

interface UseCasePollingOptions {
  auth: AuthStatus | null;
  hasActiveJobs: boolean;
  selectedId: string;
  refresh: () => void | Promise<void>;
  loadDiagnostics: (caseId: string, quiet?: boolean) => void | Promise<void>;
}

export function useCasePolling({ auth, hasActiveJobs, selectedId, refresh, loadDiagnostics }: UseCasePollingOptions) {
  useEffect(() => {
    if (auth === null || (auth.enabled && !auth.authenticated) || !hasActiveJobs) return;
    const timer = window.setInterval(() => {
      void refresh();
      if (selectedId) {
        void loadDiagnostics(selectedId, true);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [auth, hasActiveJobs, selectedId, refresh, loadDiagnostics]);
}
