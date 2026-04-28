from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.application.export_case import ExportCase
from app.application.ports import CaseRepository, Exporter, FieldDictionaryProvider
from app.composition.dependencies import get_case_repository, get_dictionary_provider, get_exporter
from app.domain.auth import AuthUser
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/export.xlsx")
def export_case(
    case_id: str,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
    dictionary_provider: FieldDictionaryProvider = Depends(get_dictionary_provider),
    exporter: Exporter = Depends(get_exporter),
) -> Response:
    content = ExportCase(
        repository=repository,
        dictionary_provider=dictionary_provider,
        exporter=exporter,
    ).execute(case_id)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.xlsx"'},
    )
