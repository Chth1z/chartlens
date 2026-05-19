import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  deleteCase,
  downloadCaseExport,
  getAuthStatus,
  reprocessCase,
  requestVisionFallback,
  updateReview,
  uploadCase
} from "../../shared/api/client";
import { queryKeys } from "../../shared/api/queries";
import type { CaseRecord, FieldResult } from "../../shared/types/api";

interface ActionDeps {
  selectedCase: CaseRecord | undefined;
  selectedId: string;
  cases: CaseRecord[];
  activeResult: FieldResult | undefined;
  reviewCode: string;
  reviewReason: string;
  documentTerm: string;
  setLoading: (v: boolean) => void;
  setError: (v: string | null) => void;
  setSelectedId: (v: string) => void;
}

export function useChartLensActions(deps: ActionDeps) {
  const { selectedCase, selectedId, cases, activeResult, reviewCode, reviewReason, documentTerm, setLoading, setError, setSelectedId } = deps;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function refreshAuthStatus() {
    return queryClient.fetchQuery({ queryKey: queryKeys.auth, queryFn: getAuthStatus });
  }

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const created = await uploadCase(file);
      queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, (old) => [created, ...(old ?? []).filter((item) => item.case_id !== created.case_id)]);
      setSelectedId(created.case_id);
      navigate(`/cases/${encodeURIComponent(created.case_id)}/review`);
      void queryClient.invalidateQueries({ queryKey: queryKeys.caseDiagnostics(created.case_id) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitReprocess() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await reprocessCase(selectedCase.case_id);
      queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, (old) =>
        (old ?? []).map((record) => record.case_id === updated.case_id ? { ...record, ...updated, results: record.results, ocr_blocks: record.ocr_blocks } : record)
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.caseDiagnostics(updated.case_id) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新处理失败");
    } finally {
      setLoading(false);
    }
  }

  async function approveVisionFallback() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      await requestVisionFallback(selectedCase.case_id, {
        field_key: activeResult?.field_key ?? null,
        page: activeResult?.page ?? 1,
        bbox: activeResult?.bbox ?? [],
        reason: "人工确认当前字段页或裁剪区域已脱敏，记录为图像兜底请求。",
        reviewer: "local-reviewer",
        manual_redaction_confirmed: true
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.caseDiagnostics(selectedCase.case_id) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "图像兜底请求记录失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitExport() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      const { blob, filename } = await downloadCaseExport(selectedCase.case_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Excel 导出失败");
    } finally {
      setLoading(false);
    }
  }

  const submitReview = useCallback(async () => {
    if (!selectedCase || !activeResult) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await updateReview(selectedCase.case_id, {
        field_key: activeResult.field_key,
        raw_value: reviewCode === "1" ? "有" : reviewCode === "0" ? "无" : reviewCode,
        normalized_code: reviewCode,
        comment: reviewReason,
        reviewer: "local-reviewer"
      });
      queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, (old) =>
        (old ?? []).map((record) =>
          record.case_id === selectedCase.case_id
            ? {
                ...record,
                audit_count: record.audit_count + 1,
                results: record.results.map((result) => result.field_key === updated.field_key ? updated : result),
                review_required_count: record.results
                  .map((result) => result.field_key === updated.field_key ? updated : result)
                  .filter((result) => result.review_required).length
              }
            : record
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "复核提交失败");
    } finally {
      setLoading(false);
    }
  }, [activeResult, reviewCode, reviewReason, selectedCase, queryClient, setLoading, setError]);

  async function removeCase(caseId: string) {
    const target = cases.find((record) => record.case_id === caseId);
    if (!target) return;
    if (!window.confirm(`从列表移除${documentTerm} ${target.case_id}？原始文件、抽取结果、人工复核和处理日志会保留，用于追溯。`)) return;
    setLoading(true);
    setError(null);
    try {
      await deleteCase(caseId);
      const nextCases = cases.filter((record) => record.case_id !== caseId);
      queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, nextCases);
      if (selectedId === caseId) {
        setSelectedId(nextCases[0]?.case_id ?? "");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除病例失败");
    } finally {
      setLoading(false);
    }
  }

  function clearLocalCases() {
    queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, []);
    setSelectedId("");
    navigate("/cases");
  }

  return { refreshAuthStatus, onUpload, submitReprocess, approveVisionFallback, submitExport, submitReview, removeCase, clearLocalCases };
}
