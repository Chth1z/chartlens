from __future__ import annotations

from app.application.process_case import ProcessCaseUseCase


class FakeProcessor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def process_case(self, case_id: str) -> None:
        self.calls.append(case_id)


def test_process_case_use_case_delegates_case_id_to_injected_processor() -> None:
    processor = FakeProcessor()
    use_case = ProcessCaseUseCase(processor)

    result = use_case.execute("CASE-1")

    assert result is None
    assert processor.calls == ["CASE-1"]
