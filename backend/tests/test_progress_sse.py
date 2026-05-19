"""Tests for the SSE progress endpoint and CaseProgressBus."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core.database import CaseRecord, SessionLocal
from app.main import app
from app.services.progress import CaseProgressBus, ProgressEvent, progress_bus


# ---------------------------------------------------------------------------
# Unit tests for CaseProgressBus
# ---------------------------------------------------------------------------


class TestCaseProgressBus:
    def test_publish_without_subscribers_does_not_raise(self):
        bus = CaseProgressBus()
        event = ProgressEvent(case_id="CASE-001", stage="ocr", progress=0.1)
        # Should not raise
        bus.publish("CASE-001", event)

    def test_subscribe_receives_published_event(self):
        bus = CaseProgressBus()

        async def _run():
            queue = await bus.subscribe("CASE-002")
            bus.publish("CASE-002", ProgressEvent(case_id="CASE-002", stage="extracting", progress=0.5))
            received = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert received is not None
            assert received.stage == "extracting"
            assert received.progress == 0.5

        asyncio.run(_run())

    def test_close_case_sends_none(self):
        bus = CaseProgressBus()

        async def _run():
            queue = await bus.subscribe("CASE-003")
            bus.close_case("CASE-003")
            received = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert received is None

        asyncio.run(_run())

    def test_unsubscribe_removes_subscription(self):
        bus = CaseProgressBus()

        async def _run():
            queue = await bus.subscribe("CASE-004")
            bus.unsubscribe("CASE-004", queue)
            # Publishing after unsubscribe should not put anything in the queue
            bus.publish("CASE-004", ProgressEvent(case_id="CASE-004", stage="ocr", progress=0.1))
            # Queue should be empty
            assert queue.empty()

        asyncio.run(_run())

    def test_publish_from_thread(self):
        """Verify thread-safety: publish from a worker thread reaches async subscriber."""
        bus = CaseProgressBus()

        async def _run():
            queue = await bus.subscribe("CASE-005")

            def worker():
                time.sleep(0.05)
                bus.publish("CASE-005", ProgressEvent(case_id="CASE-005", stage="ocr", progress=0.2))

            t = threading.Thread(target=worker)
            t.start()
            received = await asyncio.wait_for(queue.get(), timeout=3.0)
            t.join()
            assert received is not None
            assert received.stage == "ocr"

        asyncio.run(_run())

    def test_multiple_subscribers_receive_same_event(self):
        bus = CaseProgressBus()

        async def _run():
            q1 = await bus.subscribe("CASE-006")
            q2 = await bus.subscribe("CASE-006")
            event = ProgressEvent(case_id="CASE-006", stage="completed", progress=1.0)
            bus.publish("CASE-006", event)
            r1 = await asyncio.wait_for(q1.get(), timeout=2.0)
            r2 = await asyncio.wait_for(q2.get(), timeout=2.0)
            assert r1 is not None and r1.stage == "completed"
            assert r2 is not None and r2.stage == "completed"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Integration tests for the SSE endpoint
# ---------------------------------------------------------------------------


def _create_test_case(db, case_id: str = "CASE-SSE-TEST") -> CaseRecord:
    """Insert a minimal case record for testing."""
    record = CaseRecord(
        case_id=case_id,
        filename="test.pdf",
        file_hash="abc123",
        file_path="test.pdf",
        status="queued",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


class TestSSEEndpoint:
    def test_progress_endpoint_returns_event_stream(self):
        db = SessionLocal()
        try:
            case = _create_test_case(db, "CASE-SSE-STREAM")
            client = TestClient(app)

            # Publish a completed event in a background thread so the stream terminates
            def publish_events():
                time.sleep(0.1)
                progress_bus.publish("CASE-SSE-STREAM", ProgressEvent(
                    case_id="CASE-SSE-STREAM",
                    stage="ocr",
                    step="ocr_document_ir",
                    progress=0.3,
                    message="OCR processing...",
                ))
                time.sleep(0.05)
                progress_bus.publish("CASE-SSE-STREAM", ProgressEvent(
                    case_id="CASE-SSE-STREAM",
                    stage="completed",
                    progress=1.0,
                    message="Done.",
                ))

            t = threading.Thread(target=publish_events)
            t.start()

            with client.stream("GET", "/api/cases/CASE-SSE-STREAM/progress") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]

                lines = []
                for chunk in response.iter_text():
                    lines.append(chunk)
                    # Stop after we get the complete event
                    if "event: complete" in chunk:
                        break

            t.join(timeout=5)
            full_output = "".join(lines)
            assert "event: progress" in full_output
            assert "event: complete" in full_output
            assert '"stage":"ocr"' in full_output or '"stage": "ocr"' in full_output
        finally:
            db.query(CaseRecord).filter(CaseRecord.case_id == "CASE-SSE-STREAM").delete()
            db.commit()
            db.close()

    def test_progress_endpoint_404_for_missing_case(self):
        client = TestClient(app)
        response = client.get("/api/cases/CASE-NONEXISTENT/progress")
        assert response.status_code == 404

    def test_progress_event_to_dict(self):
        event = ProgressEvent(
            case_id="CASE-X",
            stage="extracting",
            step="collect_evidence",
            progress=0.6,
            started_at="2026-01-01T00:00:00",
            message="Extracting fields...",
        )
        d = event.to_dict()
        assert d["case_id"] == "CASE-X"
        assert d["stage"] == "extracting"
        assert d["step"] == "collect_evidence"
        assert d["progress"] == 0.6
        assert d["started_at"] == "2026-01-01T00:00:00"
        assert d["message"] == "Extracting fields..."
