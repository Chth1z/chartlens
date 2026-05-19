"""Tests for multimodal evidence collection context builder."""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.models import (
    DocumentContext,
    DocumentContextPage,
    DocumentIRBlock,
    DocumentPageImage,
)
from app.services.multimodal_context import (
    _load_image_file,
    enrich_context_with_images,
    multimodal_enabled,
    page_image_to_base64_url,
)


def _block(block_id: str = "b1", text: str = "test") -> DocumentIRBlock:
    return DocumentIRBlock(
        block_id=block_id, page=1, reading_order=1, text=text, confidence=0.9
    )


def _context(num_pages: int = 2) -> DocumentContext:
    pages = [
        DocumentContextPage(
            page=i + 1,
            blocks=[_block(f"b{i + 1}", f"text page {i + 1}")],
        )
        for i in range(num_pages)
    ]
    return DocumentContext(
        document_id="doc-001",
        profile_id="test_profile",
        source_filename="test.pdf",
        pages=pages,
        metadata={"context_version": "document-context-v1"},
    )


class TestMultimodalEnabled:
    def test_disabled_by_default(self):
        with patch("app.services.multimodal_context.settings") as mock_settings:
            mock_settings.multimodal_evidence = False
            assert not multimodal_enabled()

    def test_enabled_when_setting_true(self):
        with patch("app.services.multimodal_context.settings") as mock_settings:
            mock_settings.multimodal_evidence = True
            assert multimodal_enabled()


class TestEnrichContextWithImages:
    def test_returns_unchanged_when_disabled(self):
        context = _context()
        with patch("app.services.multimodal_context.multimodal_enabled", return_value=False):
            result = enrich_context_with_images(context, source_file=Path("fake.pdf"))
        assert result is context

    def test_returns_unchanged_when_no_source_file(self):
        context = _context()
        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            result = enrich_context_with_images(context, source_file=None)
        assert result is context

    def test_returns_unchanged_when_source_file_missing(self, tmp_path):
        context = _context()
        missing = tmp_path / "nonexistent.pdf"
        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            result = enrich_context_with_images(context, source_file=missing)
        assert result is context

    def test_returns_unchanged_for_unsupported_suffix(self, tmp_path):
        context = _context()
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("hello")
        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            with patch("app.services.multimodal_context.settings") as mock_settings:
                mock_settings.multimodal_max_pages = 4
                result = enrich_context_with_images(context, source_file=txt_file)
        assert result is context

    def test_enriches_with_image_file(self, tmp_path):
        context = _context(num_pages=1)
        # Create a fake PNG file
        png_file = tmp_path / "scan.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            with patch("app.services.multimodal_context.settings") as mock_settings:
                mock_settings.multimodal_max_pages = 4
                result = enrich_context_with_images(context, source_file=png_file)

        assert result is not context
        assert result.pages[0].image is not None
        assert result.pages[0].image.page == 1
        assert result.pages[0].image.online_allowed is True
        assert result.metadata.get("multimodal_images_attached") == 1

    def test_graceful_fallback_on_render_failure(self, tmp_path):
        context = _context()
        pdf_file = tmp_path / "broken.pdf"
        pdf_file.write_bytes(b"not a real pdf")

        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            with patch("app.services.multimodal_context.settings") as mock_settings:
                mock_settings.multimodal_max_pages = 4
                with patch(
                    "app.services.multimodal_context._render_pdf_pages",
                    side_effect=Exception("render failed"),
                ):
                    result = enrich_context_with_images(context, source_file=pdf_file)

        # Should return unchanged context on failure
        assert result is context

    def test_respects_max_pages_setting(self, tmp_path):
        context = _context(num_pages=6)
        png_file = tmp_path / "scan.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("app.services.multimodal_context.multimodal_enabled", return_value=True):
            with patch("app.services.multimodal_context.settings") as mock_settings:
                mock_settings.multimodal_max_pages = 2
                result = enrich_context_with_images(context, source_file=png_file)

        # Image files only produce page 1, so only 1 page gets an image
        images_attached = result.metadata.get("multimodal_images_attached", 0)
        assert images_attached <= 2


class TestPageImageToBase64Url:
    def test_returns_valid_data_url_for_png(self, tmp_path):
        png_file = tmp_path / "test.png"
        png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        png_file.write_bytes(png_content)

        result = page_image_to_base64_url(str(png_file))

        assert result is not None
        assert result.startswith("data:image/png;base64,")
        # Verify the base64 decodes back to original content
        encoded_part = result.split(",", 1)[1]
        decoded = base64.b64decode(encoded_part)
        assert decoded == png_content

    def test_returns_valid_data_url_for_jpeg(self, tmp_path):
        jpg_file = tmp_path / "test.jpg"
        jpg_content = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        jpg_file.write_bytes(jpg_content)

        result = page_image_to_base64_url(str(jpg_file))

        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_returns_none_for_missing_file(self):
        result = page_image_to_base64_url("/nonexistent/path/image.png")
        assert result is None

    def test_returns_none_for_empty_path(self):
        result = page_image_to_base64_url("")
        assert result is None


class TestLoadImageFile:
    def test_loads_existing_image(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        result = _load_image_file(img)

        assert 1 in result
        assert result[1]["path"] == str(img)
        assert result[1]["sha256"] is not None

    def test_returns_empty_for_missing_file(self, tmp_path):
        missing = tmp_path / "gone.png"
        result = _load_image_file(missing)
        assert result == {}


class TestChatImageContentParts:
    """Test the _chat_image_content_parts helper in payloads_evidence_first."""

    def test_returns_empty_when_no_images(self):
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_image_content_parts,
        )

        context = _context()
        parts = _chat_image_content_parts(context)
        assert parts == []

    def test_returns_empty_when_images_not_online_allowed(self):
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_image_content_parts,
        )

        context = _context(num_pages=1)
        # Attach an image that is NOT online_allowed
        page_image = DocumentPageImage(
            page=1, path="/some/path.png", online_allowed=False
        )
        context = context.model_copy(
            update={
                "pages": [context.pages[0].model_copy(update={"image": page_image})]
            }
        )

        parts = _chat_image_content_parts(context)
        assert parts == []

    def test_returns_image_parts_when_available(self, tmp_path):
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_image_content_parts,
        )

        # Create a real image file
        img_file = tmp_path / "page1.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        context = _context(num_pages=1)
        page_image = DocumentPageImage(
            page=1, path=str(img_file), online_allowed=True
        )
        context = context.model_copy(
            update={
                "pages": [context.pages[0].model_copy(update={"image": page_image})]
            }
        )

        parts = _chat_image_content_parts(context)

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"
        assert parts[0]["image_url"]["detail"] == "low"
        assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


class TestChatCompletionsPayloadWithImages:
    """Integration test: chat completions payload includes images when conditions are met."""

    def test_payload_includes_images_for_vision_model(self, tmp_path):
        from unittest.mock import MagicMock

        from app.domain.models import RemoteExposurePolicy
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_completions_evidence_first_payload,
        )

        # Create a real image file
        img_file = tmp_path / "page1.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        context = _context(num_pages=1)
        page_image = DocumentPageImage(
            page=1, path=str(img_file), online_allowed=True
        )
        context = context.model_copy(
            update={
                "pages": [context.pages[0].model_copy(update={"image": page_image})]
            }
        )

        # Mock model profile with vision support
        mock_profile = MagicMock()
        mock_profile.input = ["text", "image"]
        mock_profile.structured_output_mode = "json_object"
        mock_profile.temperature = 0.0
        mock_profile.max_output_tokens = 4096
        mock_profile.prompt_cache_key = None
        mock_profile.reasoning_effort = None

        # Mock exposure policy to allow images
        policy = RemoteExposurePolicy(
            allow_full_document_context=True,
            allow_raw_block_text=True,
            allow_page_images=True,
        )

        with patch(
            "app.services.llm_provider.payloads_evidence_first.get_active_model_profile",
            return_value=mock_profile,
        ):
            with patch(
                "app.services.llm_provider.payloads_evidence_first._remote_exposure_policy",
                return_value=policy,
            ):
                with patch(
                    "app.services.llm_provider.payloads_evidence_first._evidence_first_system_prompt",
                    return_value="System prompt",
                ):
                    payload = _chat_completions_evidence_first_payload(
                        document_context=context,
                        fields=[],
                        model="gpt-4o",
                        profile=mock_profile,
                    )

        # User message should be multipart content with text + image
        user_msg = payload["messages"][-1]
        assert isinstance(user_msg["content"], list)
        assert user_msg["content"][0]["type"] == "text"
        assert user_msg["content"][1]["type"] == "image_url"
        assert user_msg["content"][1]["image_url"]["detail"] == "low"

    def test_payload_no_images_when_model_lacks_vision(self, tmp_path):
        from unittest.mock import MagicMock

        from app.domain.models import RemoteExposurePolicy
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_completions_evidence_first_payload,
        )

        # Create a real image file
        img_file = tmp_path / "page1.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        context = _context(num_pages=1)
        page_image = DocumentPageImage(
            page=1, path=str(img_file), online_allowed=True
        )
        context = context.model_copy(
            update={
                "pages": [context.pages[0].model_copy(update={"image": page_image})]
            }
        )

        # Mock model profile WITHOUT vision support
        mock_profile = MagicMock()
        mock_profile.input = ["text"]  # No "image" or "vision"
        mock_profile.structured_output_mode = "json_object"
        mock_profile.temperature = 0.0
        mock_profile.max_output_tokens = 4096
        mock_profile.prompt_cache_key = None
        mock_profile.reasoning_effort = None

        policy = RemoteExposurePolicy(
            allow_full_document_context=True,
            allow_raw_block_text=True,
            allow_page_images=True,
        )

        with patch(
            "app.services.llm_provider.payloads_evidence_first.get_active_model_profile",
            return_value=mock_profile,
        ):
            with patch(
                "app.services.llm_provider.payloads_evidence_first._remote_exposure_policy",
                return_value=policy,
            ):
                with patch(
                    "app.services.llm_provider.payloads_evidence_first._evidence_first_system_prompt",
                    return_value="System prompt",
                ):
                    payload = _chat_completions_evidence_first_payload(
                        document_context=context,
                        fields=[],
                        model="deepseek-chat",
                        profile=mock_profile,
                    )

        # User message should be plain string (no multipart)
        user_msg = payload["messages"][-1]
        assert isinstance(user_msg["content"], str)

    def test_payload_no_images_when_policy_disallows(self, tmp_path):
        from unittest.mock import MagicMock

        from app.domain.models import RemoteExposurePolicy
        from app.services.llm_provider.payloads_evidence_first import (
            _chat_completions_evidence_first_payload,
        )

        # Create a real image file
        img_file = tmp_path / "page1.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        context = _context(num_pages=1)
        page_image = DocumentPageImage(
            page=1, path=str(img_file), online_allowed=True
        )
        context = context.model_copy(
            update={
                "pages": [context.pages[0].model_copy(update={"image": page_image})]
            }
        )

        # Mock model profile with vision support
        mock_profile = MagicMock()
        mock_profile.input = ["text", "image"]
        mock_profile.structured_output_mode = "json_object"
        mock_profile.temperature = 0.0
        mock_profile.max_output_tokens = 4096
        mock_profile.prompt_cache_key = None
        mock_profile.reasoning_effort = None

        # Policy DISALLOWS page images
        policy = RemoteExposurePolicy(
            allow_full_document_context=True,
            allow_raw_block_text=True,
            allow_page_images=False,
        )

        with patch(
            "app.services.llm_provider.payloads_evidence_first.get_active_model_profile",
            return_value=mock_profile,
        ):
            with patch(
                "app.services.llm_provider.payloads_evidence_first._remote_exposure_policy",
                return_value=policy,
            ):
                with patch(
                    "app.services.llm_provider.payloads_evidence_first._evidence_first_system_prompt",
                    return_value="System prompt",
                ):
                    payload = _chat_completions_evidence_first_payload(
                        document_context=context,
                        fields=[],
                        model="gpt-4o",
                        profile=mock_profile,
                    )

        # User message should be plain string (no multipart)
        user_msg = payload["messages"][-1]
        assert isinstance(user_msg["content"], str)
