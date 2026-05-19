"""Tests for Presidio-based PHI detection (optional second layer)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.services.presidio_deidentify import (
    PresidioFinding,
    analyze_text,
    presidio_available,
    presidio_enabled,
    presidio_risk_findings,
    redact_with_presidio,
    reset_analyzer,
    _replacement_for_type,
)


class TestPresidioEnabled:
    def test_disabled_by_default(self):
        with patch("app.services.presidio_deidentify.settings") as mock:
            mock.presidio_enabled = False
            assert not presidio_enabled()

    def test_enabled_when_setting_true(self):
        with patch("app.services.presidio_deidentify.settings") as mock:
            mock.presidio_enabled = True
            assert presidio_enabled()


class TestPresidioAvailable:
    def test_returns_bool(self):
        # This test works whether or not presidio-analyzer is installed
        result = presidio_available()
        assert isinstance(result, bool)


class TestAnalyzeText:
    def test_returns_empty_when_disabled(self):
        with patch("app.services.presidio_deidentify.presidio_enabled", return_value=False):
            result = analyze_text("张三的电话是13812345678")
        assert result == []

    def test_returns_empty_when_analyzer_unavailable(self):
        with patch("app.services.presidio_deidentify.presidio_enabled", return_value=True):
            with patch("app.services.presidio_deidentify._get_analyzer", return_value=None):
                result = analyze_text("张三的电话是13812345678")
        assert result == []

    def test_returns_findings_with_mock_analyzer(self):
        mock_result = MagicMock()
        mock_result.entity_type = "PHONE_NUMBER"
        mock_result.start = 6
        mock_result.end = 17
        mock_result.score = 0.85

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = [mock_result]

        with patch("app.services.presidio_deidentify.presidio_enabled", return_value=True):
            with patch("app.services.presidio_deidentify._get_analyzer", return_value=mock_analyzer):
                result = analyze_text("张三的电话是13812345678")

        assert len(result) == 1
        assert result[0].entity_type == "PHONE_NUMBER"
        assert result[0].text == "13812345678"
        assert result[0].score == 0.85

    def test_handles_analyzer_exception_gracefully(self):
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.side_effect = RuntimeError("engine failure")

        with patch("app.services.presidio_deidentify.presidio_enabled", return_value=True):
            with patch("app.services.presidio_deidentify._get_analyzer", return_value=mock_analyzer):
                result = analyze_text("some text")

        assert result == []


class TestRedactWithPresidio:
    def test_returns_original_when_disabled(self):
        text = "张三的电话是13812345678"
        with patch("app.services.presidio_deidentify.presidio_enabled", return_value=False):
            result = redact_with_presidio(text)
        assert result == text

    def test_redacts_findings(self):
        text = "患者张三，电话13812345678"
        findings = [
            PresidioFinding(entity_type="PERSON", text="张三", start=2, end=4, score=0.8),
            PresidioFinding(entity_type="PHONE_NUMBER", text="13812345678", start=7, end=18, score=0.9),
        ]
        with patch("app.services.presidio_deidentify.analyze_text", return_value=findings):
            result = redact_with_presidio(text)
        assert "[PERSON]" in result
        assert "[PHONE]" in result
        assert "张三" not in result
        assert "13812345678" not in result

    def test_returns_original_when_no_findings(self):
        text = "无敏感信息的文本"
        with patch("app.services.presidio_deidentify.analyze_text", return_value=[]):
            result = redact_with_presidio(text)
        assert result == text


class TestPresidioRiskFindings:
    def test_returns_entity_types(self):
        findings = [
            PresidioFinding(entity_type="PERSON", text="张三", start=0, end=2, score=0.8),
            PresidioFinding(entity_type="PHONE_NUMBER", text="138", start=3, end=6, score=0.7),
        ]
        with patch("app.services.presidio_deidentify.analyze_text", return_value=findings):
            result = presidio_risk_findings("张三 138")
        assert "PERSON" in result
        assert "PHONE_NUMBER" in result

    def test_deduplicates_entity_types(self):
        findings = [
            PresidioFinding(entity_type="PERSON", text="张三", start=0, end=2, score=0.8),
            PresidioFinding(entity_type="PERSON", text="李四", start=3, end=5, score=0.7),
        ]
        with patch("app.services.presidio_deidentify.analyze_text", return_value=findings):
            result = presidio_risk_findings("张三 李四")
        assert result.count("PERSON") == 1

    def test_returns_empty_when_no_findings(self):
        with patch("app.services.presidio_deidentify.analyze_text", return_value=[]):
            result = presidio_risk_findings("无敏感信息")
        assert result == []


class TestReplacementForType:
    def test_known_types(self):
        assert _replacement_for_type("PERSON") == "[PERSON]"
        assert _replacement_for_type("PHONE_NUMBER") == "[PHONE]"
        assert _replacement_for_type("ID_NUMBER") == "[ID]"
        assert _replacement_for_type("LOCATION") == "[ADDRESS]"
        assert _replacement_for_type("MEDICAL_RECORD") == "[MRN]"

    def test_unknown_type(self):
        assert _replacement_for_type("UNKNOWN_TYPE") == "[REDACTED]"


class TestResetAnalyzer:
    def test_reset_clears_state(self):
        reset_analyzer()
        from app.services import presidio_deidentify
        assert presidio_deidentify._analyzer_instance is None
        assert presidio_deidentify._initialization_attempted is False
