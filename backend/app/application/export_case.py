from __future__ import annotations

from app.application.ports import CaseRepository, Exporter, FieldDictionaryProvider


class ExportCase:
    def __init__(
        self,
        *,
        repository: CaseRepository,
        dictionary_provider: FieldDictionaryProvider,
        exporter: Exporter,
    ):
        self.repository = repository
        self.dictionary_provider = dictionary_provider
        self.exporter = exporter

    def execute(self, case_id: str) -> bytes:
        dictionary = self.dictionary_provider.load_field_dictionary()
        results = self.repository.export_results(case_id)
        return self.exporter.build_case_workbook(case_id=case_id, dictionary=dictionary, results=results)
