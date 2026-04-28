from __future__ import annotations

from app.application.ports import CaseRepository, SystemConfigProvider
from app.domain.clinical import VisionFallbackRequest


class GetDiagnostics:
    def __init__(self, *, repository: CaseRepository, config_provider: SystemConfigProvider):
        self.repository = repository
        self.config_provider = config_provider

    def execute(self, case_id: str) -> dict:
        return self.repository.diagnostics(case_id, self.config_provider.load_system_config())


class RequestVisionFallback:
    def __init__(self, *, repository: CaseRepository, config_provider: SystemConfigProvider):
        self.repository = repository
        self.config_provider = config_provider

    def execute(self, case_id: str, request: VisionFallbackRequest) -> dict:
        config = self.config_provider.load_system_config()
        if not config.llm.vision_fallback.enabled:
            raise ValueError("Vision fallback is disabled")
        if config.llm.vision_fallback.requires_manual_approval and not request.manual_redaction_confirmed:
            raise ValueError("Manual redaction confirmation is required")
        return self.repository.create_vision_fallback_request(case_id, request)
