import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env?.VITE_API_BASE ?? "";

export interface ProgressEvent {
  case_id: string;
  stage: string;
  step: string;
  progress: number;
  started_at: string;
  message: string;
}

export interface CaseProgressState {
  /** Current processing stage (queued, ocr, extracting, completed, failed) */
  stage: string | null;
  /** Progress fraction 0..1 */
  progress: number;
  /** Whether the case is actively being processed */
  isProcessing: boolean;
  /** Accumulated progress events */
  events: ProgressEvent[];
}

/**
 * Subscribe to real-time SSE progress for a case.
 *
 * Connects to GET /api/cases/{caseId}/progress and streams events.
 * Auto-reconnects on disconnect (up to 3 attempts with exponential backoff).
 * Closes automatically when the case reaches a terminal state.
 *
 * Pass `null` to disconnect without subscribing.
 */
export function useCaseProgress(caseId: string | null): CaseProgressState {
  const [state, setState] = useState<CaseProgressState>({
    stage: null,
    progress: 0,
    isProcessing: false,
    events: [],
  });

  const retriesRef = useRef(0);
  const maxRetries = 3;
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!caseId) {
      cleanup();
      setState({ stage: null, progress: 0, isProcessing: false, events: [] });
      return;
    }

    let cancelled = false;
    retriesRef.current = 0;

    function connect() {
      if (cancelled) return;

      const url = `${API_BASE}/api/cases/${encodeURIComponent(caseId!)}/progress`;
      const es = new EventSource(url);
      eventSourceRef.current = es;

      setState((prev) => ({ ...prev, isProcessing: true }));

      es.addEventListener("progress", (e: MessageEvent) => {
        if (cancelled) return;
        retriesRef.current = 0;
        try {
          const data = JSON.parse(e.data) as ProgressEvent;
          setState((prev) => ({
            stage: data.stage,
            progress: data.progress,
            isProcessing: true,
            events: [...prev.events, data],
          }));
        } catch {
          // Ignore malformed events
        }
      });

      es.addEventListener("complete", (e: MessageEvent) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data) as ProgressEvent;
          setState((prev) => ({
            stage: data.stage,
            progress: data.progress,
            isProcessing: false,
            events: [...prev.events, data],
          }));
        } catch {
          setState((prev) => ({ ...prev, isProcessing: false }));
        }
        es.close();
        eventSourceRef.current = null;
      });

      es.onerror = () => {
        if (cancelled) return;
        es.close();
        eventSourceRef.current = null;

        if (retriesRef.current < maxRetries) {
          const delay = Math.min(1000 * 2 ** retriesRef.current, 8000);
          retriesRef.current += 1;
          setTimeout(connect, delay);
        } else {
          setState((prev) => ({ ...prev, isProcessing: false }));
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [caseId, cleanup]);

  return state;
}
