import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAuthStatus,
  getCaseDiagnostics,
  getCaseDocumentIr,
  getCaseResults,
  getCaseSourceOcr,
  getProjectConfig,
  getRuntimeSettings,
  listCases,
} from "./client";
import type { CaseRecord, FieldResult, OcrBlock } from "../types/api";
import { mergeCaseRecord } from "../../features/app/caseSwitching.js";

export const queryKeys = {
  auth: ["auth"] as const,
  cases: ["cases"] as const,
  projectConfig: ["projectConfig"] as const,
  runtime: ["runtime"] as const,
  caseDiagnostics: (caseId: string) => ["caseDiagnostics", caseId] as const,
};

export function useAuthQuery() {
  return useQuery({
    queryKey: queryKeys.auth,
    queryFn: getAuthStatus,
    staleTime: 30_000,
  });
}

export function useCasesQuery(enabled = true) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.cases,
    queryFn: async () => {
      const remoteCases = await listCases();
      const existing = queryClient.getQueryData<CaseRecord[]>(queryKeys.cases);
      if (!existing) return remoteCases;
      return remoteCases.map((remote) =>
        mergeCaseRecord(remote, existing.find((item) => item.case_id === remote.case_id))
      );
    },
    enabled,
  });
}

export function useProjectConfigQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.projectConfig,
    queryFn: getProjectConfig,
    enabled,
    staleTime: 60_000,
  });
}

export function useRuntimeQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.runtime,
    queryFn: getRuntimeSettings,
    enabled,
    staleTime: 30_000,
  });
}

export interface CaseDiagnosticsData {
  results: FieldResult[];
  ocrBlocks: OcrBlock[];
  payload: ReturnType<typeof getCaseDiagnostics> extends Promise<infer T> ? T : never;
}

export function useCaseDiagnosticsQuery(caseId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.caseDiagnostics(caseId ?? ""),
    queryFn: async () => {
      if (!caseId) throw new Error("no case");
      const [results, _documentIr, sourceOcr, payload] = await Promise.all([
        getCaseResults(caseId),
        getCaseDocumentIr(caseId),
        getCaseSourceOcr(caseId),
        getCaseDiagnostics(caseId),
      ]);
      const ocrBlocks = sourceOcr.blocks.map((block, index) => ({
        ...block,
        reading_order: block.reading_order ?? index + 1,
      }));
      return { results, ocrBlocks, payload };
    },
    enabled: enabled && Boolean(caseId),
    staleTime: 10_000,
  });
}
