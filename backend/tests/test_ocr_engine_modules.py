"""Tests for the new OCR engine modules: observability, evaluation, concurrency, preprocessing."""

from __future__ import annotations

import sys
import time

from app.services.ocr_engine.evaluation import (
    character_error_rate,
    word_error_rate,
    evaluate_ocr_output,
    evaluate_page_level,
)
from app.services.ocr_engine.observability import (
    OcrTrace,
    StageMetric,
    trace_stage,
    quality_band,
    confidence_distribution,
)
from app.services.ocr_engine.concurrency import (
    process_pages_parallel,
)
from app.services.ocr_engine.errors import (
    OcrErrorCode,
    OcrEngineError,
    reset_directml_state,
)
from app.services.ocr_engine.preprocessing import (
    preprocess_ocr_image,
    iter_rapidocr_page_inputs,
)
from app.services.ocr_engine.postprocessing import (
    dedupe_ocr_blocks,
)
from app.services.ocr_engine.types import IntelligentOcrBlock


# === Evaluation Tests ===

def test_cer_perfect_match():
    assert character_error_rate("高血压病史5年", "高血压病史5年") == 0.0


def test_cer_single_char_error():
    cer = character_error_rate("高血厌病史5年", "高血压病史5年")
    assert 0.0 < cer < 0.25  # 1/7 ≈ 0.143


def test_cer_empty_reference():
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("some text", "") == 1.0


def test_cer_empty_hypothesis():
    assert character_error_rate("", "参考文本") == 1.0


def test_wer_perfect_match():
    assert word_error_rate("高血压 病史 5年", "高血压 病史 5年") == 0.0


def test_wer_word_error():
    wer = word_error_rate("高血厌 病史 5年", "高血压 病史 5年")
    assert 0.0 < wer < 0.5  # 1/3 ≈ 0.333


def test_evaluate_ocr_output_quality_bands():
    result = evaluate_ocr_output("完美匹配", "完美匹配", document_id="test_doc")
    assert result.cer == 0.0
    assert result.quality_band == "excellent"
    assert result.document_id == "test_doc"


def test_evaluate_page_level_metrics():
    result = evaluate_page_level(
        ocr_pages={1: "第一页内容", 2: "第二页内容"},
        truth_pages={1: "第一页内容", 2: "第二页内容"},
        document_id="multi_page",
    )
    assert result.cer == 0.0
    assert len(result.page_results) == 2
    assert all(p["quality_band"] == "excellent" for p in result.page_results)


# === Observability Tests ===

def test_trace_stage_timing():
    trace = OcrTrace(trace_id="test-001")
    trace.start()
    with trace_stage(trace, "test_stage", "test_engine") as metric:
        time.sleep(0.01)
        metric.block_count = 5
        metric.char_count = 100
    trace.finish()
    assert len(trace.stages) == 1
    assert trace.stages[0].status == "completed"
    assert trace.stages[0].duration_ms > 0
    assert trace.stages[0].block_count == 5
    assert trace.total_duration_ms > 0


def test_trace_stage_failure():
    trace = OcrTrace(trace_id="test-002")
    try:
        with trace_stage(trace, "failing_stage") as metric:
            raise ValueError("test error")
    except ValueError:
        pass
    assert trace.stages[0].status == "failed"
    assert "test error" in trace.stages[0].error


def test_quality_band_classification():
    assert quality_band(0.98) == "excellent"
    assert quality_band(0.92) == "good"
    assert quality_band(0.80) == "fair"
    assert quality_band(0.60) == "poor"
    assert quality_band(0.30) == "very_poor"


def test_confidence_distribution():
    confs = [0.99, 0.96, 0.91, 0.88, 0.70, 0.40]
    dist = confidence_distribution(confs)
    assert dist["0.95+"] == 2
    assert dist["0.90-0.95"] == 1
    assert dist["0.75-0.90"] == 1
    assert dist["0.50-0.75"] == 1
    assert dist["<0.50"] == 1


# === Concurrency Tests ===

def test_process_pages_serial():
    inputs = [1, 2, 3]
    results = process_pages_parallel(inputs, lambda x: x * 10, max_workers=1)
    assert len(results) == 3
    assert all(err is None for _, _, err in results)
    assert [r for _, r, _ in results] == [10, 20, 30]


def test_process_pages_parallel_threads():
    inputs = [1, 2, 3, 4]
    results = process_pages_parallel(inputs, lambda x: x * 10, max_workers=2)
    assert len(results) == 4
    values = sorted(r for _, r, _ in results if r is not None)
    assert values == [10, 20, 30, 40]


def test_process_pages_handles_errors():
    def fail_on_2(x):
        if x == 2:
            raise ValueError("page 2 failed")
        return x * 10

    results = process_pages_parallel([1, 2, 3], fail_on_2, max_workers=1)
    assert results[0][1] == 10
    assert results[0][2] is None
    assert results[1][1] is None
    assert "failed" in results[1][2]
    assert results[2][1] == 30


def test_process_pages_empty_input():
    results = process_pages_parallel([], lambda x: x)
    assert results == []


# === Error Code Tests ===

def test_error_code_classify_directml():
    exc = RuntimeError("DXGI_ERROR_DEVICE_REMOVED blah")
    assert OcrErrorCode.classify(exc) == OcrErrorCode.DIRECTML_CRASH


def test_error_code_classify_memory():
    exc = RuntimeError("CUDA out of memory")
    assert OcrErrorCode.classify(exc) == OcrErrorCode.MEMORY_EXHAUSTED


def test_error_code_classify_timeout():
    exc = RuntimeError("Operation timed out after 120s")
    assert OcrErrorCode.classify(exc) == OcrErrorCode.TIMEOUT


def test_error_code_classify_network():
    exc = RuntimeError("Connection refused to localhost:8765")
    assert OcrErrorCode.classify(exc) == OcrErrorCode.NETWORK_ERROR


def test_error_code_classify_unknown():
    exc = RuntimeError("something totally random")
    assert OcrErrorCode.classify(exc) == OcrErrorCode.UNKNOWN_ERROR


def test_ocr_engine_error_serializes():
    err = OcrEngineError(
        OcrErrorCode.DIRECTML_CRASH, "GPU crashed",
        engine_name="pp_ocr_v5_directml", stage="detection", page=3, recoverable=True,
    )
    d = err.to_dict()
    assert d["error_code"] == "DIRECTML_CRASH"
    assert d["engine_name"] == "pp_ocr_v5_directml"
    assert d["page"] == 3
    assert d["recoverable"] is True


def test_directml_auto_recovery_resets():
    reset_directml_state()
    from app.services.ocr_engine.errors import directml_disabled_reason
    assert directml_disabled_reason() is None


# === Preprocessing Tests ===

def test_preprocess_none_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color="white")
    result = preprocess_ocr_image(img, preprocess_mode="none")
    assert result.size == (100, 50)


def test_preprocess_autocontrast_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color=(128, 128, 128))
    result = preprocess_ocr_image(img, preprocess_mode="autocontrast")
    assert result.size == (100, 50)


def test_preprocess_denoise_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color="white")
    result = preprocess_ocr_image(img, preprocess_mode="denoise")
    assert result.size == (100, 50)


def test_preprocess_clahe_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color=(80, 80, 80))
    result = preprocess_ocr_image(img, preprocess_mode="clahe")
    assert result.size == (100, 50)


def test_preprocess_full_enhance_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color=(100, 100, 100))
    result = preprocess_ocr_image(img, preprocess_mode="full_enhance")
    assert result.size == (100, 50)


def test_preprocess_invalid_mode():
    from PIL import Image
    img = Image.new("RGB", (100, 50), color="white")
    try:
        preprocess_ocr_image(img, preprocess_mode="nonexistent_mode")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_iter_rapidocr_page_inputs_parallelizes_pdf_render_when_configured(monkeypatch, tmp_path):
    from PIL import Image

    open_calls: list[str] = []

    class FakeBitmap:
        def __init__(self, page: int):
            self._page = page

        def to_pil(self):
            return Image.new("RGB", (32, 32), color=(self._page * 40, 0, 0))

    class FakePage:
        def __init__(self, page: int):
            self._page = page

        def render(self, *, scale):
            return FakeBitmap(self._page)

    class FakePdfDocument:
        def __init__(self, path: str):
            open_calls.append(path)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def __len__(self):
            return 2

        def __getitem__(self, index: int):
            return FakePage(index + 1)

    monkeypatch.setitem(sys.modules, "pypdfium2", type("FakePdfium2", (), {"PdfDocument": FakePdfDocument}))
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")

    inputs = list(
        iter_rapidocr_page_inputs(
            file_path,
            render_scale=2.0,
            preprocess_mode="none",
            directml_safe_mode=False,
            page_render_workers=2,
        )
    )

    assert [item.page for item in inputs] == [1, 2]
    assert [item.image_path.name for item in inputs] == ["page-0001.png", "page-0002.png"]
    assert len(open_calls) == 3  # one page-count open + one open per rendered page


# === Dedup Tests ===

def test_dedupe_removes_exact_duplicate_blocks():
    blocks = [
        IntelligentOcrBlock(page=1, text="高血压病史", bbox=[10, 10, 100, 30], confidence=0.9),
        IntelligentOcrBlock(page=1, text="高血压病史", bbox=[10, 10, 100, 30], confidence=0.85),
    ]
    result = dedupe_ocr_blocks(blocks)
    assert len(result) == 1
    assert result[0].confidence == 0.9  # Higher confidence kept


def test_dedupe_keeps_different_page_blocks():
    blocks = [
        IntelligentOcrBlock(page=1, text="高血压病史", bbox=[10, 10, 100, 30], confidence=0.9),
        IntelligentOcrBlock(page=2, text="高血压病史", bbox=[10, 10, 100, 30], confidence=0.85),
    ]
    result = dedupe_ocr_blocks(blocks)
    assert len(result) == 2


def test_dedupe_keeps_spatially_distant_same_text():
    blocks = [
        IntelligentOcrBlock(page=1, text="高血压病史", bbox=[10, 10, 100, 30], confidence=0.9),
        IntelligentOcrBlock(page=1, text="高血压病史", bbox=[500, 500, 600, 520], confidence=0.85),
    ]
    result = dedupe_ocr_blocks(blocks)
    assert len(result) == 2  # Different locations, not duplicates


def test_dedupe_containment_removes_nested_block():
    """MinerU-style containment: small block fully inside large block with same text."""
    blocks = [
        IntelligentOcrBlock(page=1, text="高血压病史5年", bbox=[10, 10, 400, 50], confidence=0.85),
        IntelligentOcrBlock(page=1, text="高血压病史5年", bbox=[20, 15, 200, 45], confidence=0.90),
    ]
    result = dedupe_ocr_blocks(blocks)
    assert len(result) == 1
    assert result[0].confidence == 0.90  # Higher confidence kept


# === Model Pool Tests ===

def test_model_pool_get_or_create():
    from app.services.ocr_engine.model_pool import get_or_create, evict_all, pool_status
    evict_all()
    call_count = 0
    def factory():
        nonlocal call_count
        call_count += 1
        return {"model": "test"}
    result1 = get_or_create("test_model", factory)
    result2 = get_or_create("test_model", factory)
    assert result1 is result2  # Same instance
    assert call_count == 1  # Factory called only once
    status = pool_status()
    assert status["model_count"] == 1
    assert status["models"]["test_model"]["hit_count"] == 1
    evict_all()


def test_model_pool_evicts_on_config_change():
    from app.services.ocr_engine.model_pool import get_or_create, evict_all
    evict_all()
    call_count = 0
    def factory():
        nonlocal call_count
        call_count += 1
        return f"model_v{call_count}"
    r1 = get_or_create("cfg_model", factory, config_hash="hash_v1")
    r2 = get_or_create("cfg_model", factory, config_hash="hash_v1")
    assert r1 is r2 and call_count == 1
    r3 = get_or_create("cfg_model", factory, config_hash="hash_v2")
    assert r3 != r1  # New instance because config changed
    assert call_count == 2
    evict_all()


def test_model_pool_evict_single():
    from app.services.ocr_engine.model_pool import get_or_create, evict, evict_all
    evict_all()
    get_or_create("to_evict", lambda: "val")
    assert evict("to_evict") is True
    assert evict("nonexistent") is False
    evict_all()


# === Retry Tests ===

def test_retry_succeeds_on_first_try():
    from app.services.ocr_engine.retry import retry_with_backoff
    result = retry_with_backoff(lambda: 42, max_retries=2, label="test")
    assert result == 42


def test_retry_recovers_from_transient_error():
    from app.services.ocr_engine.retry import retry_with_backoff
    attempts = []
    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("DXGI_ERROR_DEVICE_REMOVED")
        return "recovered"
    result = retry_with_backoff(flaky, max_retries=2, base_delay=0.01, label="test")
    assert result == "recovered"
    assert len(attempts) == 2


def test_retry_gives_up_on_permanent_error():
    from app.services.ocr_engine.retry import retry_with_backoff
    attempts = []
    def always_invalid():
        attempts.append(1)
        raise RuntimeError("invalid input format")
    try:
        retry_with_backoff(always_invalid, max_retries=3, base_delay=0.01, label="test")
        assert False, "Should have raised"
    except RuntimeError:
        pass
    assert len(attempts) == 1  # No retry on permanent error


def test_retry_exhausts_all_attempts():
    from app.services.ocr_engine.retry import retry_with_backoff
    attempts = []
    def always_timeout():
        attempts.append(1)
        raise RuntimeError("Operation timed out")
    try:
        retry_with_backoff(always_timeout, max_retries=2, base_delay=0.01, label="test")
        assert False, "Should have raised"
    except RuntimeError:
        pass
    assert len(attempts) == 3  # Initial + 2 retries


def test_is_retryable_classification():
    from app.services.ocr_engine.retry import is_retryable
    assert is_retryable(RuntimeError("DXGI_ERROR_DEVICE_REMOVED")) is True
    assert is_retryable(RuntimeError("Connection refused")) is True
    assert is_retryable(RuntimeError("timed out")) is True
    assert is_retryable(RuntimeError("invalid format")) is False


# === Calibration Tests ===

def test_calibration_identity_at_temperature_1():
    from app.services.ocr_engine.calibration import calibrate_confidence
    assert calibrate_confidence(0.95, temperature=1.0) == 0.95


def test_calibration_reduces_overconfidence():
    from app.services.ocr_engine.calibration import calibrate_confidence
    raw = 0.99
    calibrated = calibrate_confidence(raw, temperature=1.15)
    assert calibrated < raw  # Temperature > 1 reduces confidence


def test_calibration_engine_specific():
    from app.services.ocr_engine.calibration import calibrate_confidence
    raw = 0.95
    dml = calibrate_confidence(raw, engine_name="pp_ocr_v5_onnx_directml")
    docling = calibrate_confidence(raw, engine_name="docling")
    assert dml < docling  # DirectML has T=1.15 > Docling T=1.0


def test_calibration_blocks():
    from app.services.ocr_engine.calibration import calibrate_blocks
    blocks = [
        IntelligentOcrBlock(page=1, text="test", confidence=0.99),
        IntelligentOcrBlock(page=1, text="test2", confidence=0.80),
    ]
    calibrated = calibrate_blocks(blocks, engine_name="pp_ocr_v5_onnx_directml")
    assert all(c.confidence <= b.confidence for b, c in zip(blocks, calibrated))


def test_confidence_gate_routing():
    from app.services.ocr_engine.calibration import confidence_gate
    assert confidence_gate(0.95) == "accept"
    assert confidence_gate(0.82) == "review"
    assert confidence_gate(0.60) == "review"  # Still review, not reject
    assert confidence_gate(0.30) == "reject"


# === Bbox Containment Tests ===

def test_bbox_containment_full():
    from app.services.ocr_engine.bbox_utils import bbox_containment
    outer = [0, 0, 100, 100]
    inner = [10, 10, 50, 50]
    assert bbox_containment(outer, inner) == 1.0  # Fully contained


def test_bbox_containment_partial():
    from app.services.ocr_engine.bbox_utils import bbox_containment
    outer = [0, 0, 100, 100]
    inner = [50, 50, 150, 150]
    containment = bbox_containment(outer, inner)
    assert 0.0 < containment < 1.0  # Partially contained


def test_bbox_containment_no_overlap():
    from app.services.ocr_engine.bbox_utils import bbox_containment
    outer = [0, 0, 50, 50]
    inner = [100, 100, 150, 150]
    assert bbox_containment(outer, inner) == 0.0


def test_bbox_containment_invalid():
    from app.services.ocr_engine.bbox_utils import bbox_containment
    assert bbox_containment([0, 0, 100], [10, 10, 50, 50]) == 0.0
