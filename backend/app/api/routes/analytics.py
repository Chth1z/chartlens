"""Cost analytics endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import ModelCallRecord, get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


class CostBreakdownItem(BaseModel):
    group_key: str
    call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_duration_ms: float | None = None


class CostAnalyticsResponse(BaseModel):
    period_days: int
    since: str
    total_call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_duration_ms: float | None = None
    breakdown: list[CostBreakdownItem] = Field(default_factory=list)
    group_by: str


@router.get("/cost", response_model=CostAnalyticsResponse)
def get_cost_analytics(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to look back"),
    group_by: Literal["provider", "model", "case", "stage"] = Query(
        default="provider", description="Group breakdown by"
    ),
    db: Session = Depends(get_db),
) -> CostAnalyticsResponse:
    """Aggregate LLM token usage and cost from model_calls table."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_str = since.isoformat()

    # Totals
    base_filter = ModelCallRecord.created_at >= since

    totals = db.execute(
        select(
            func.count(ModelCallRecord.id).label("call_count"),
            func.coalesce(func.sum(ModelCallRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ModelCallRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(ModelCallRecord.cached_input_tokens), 0).label("cached_tokens"),
            func.coalesce(func.sum(ModelCallRecord.cost_usd), 0.0).label("cost_usd"),
            func.avg(ModelCallRecord.duration_ms).label("avg_duration"),
        ).where(base_filter)
    ).one()

    # Group column
    group_col = {
        "provider": ModelCallRecord.provider,
        "model": ModelCallRecord.model,
        "case": ModelCallRecord.case_id,
        "stage": ModelCallRecord.stage,
    }[group_by]

    # Breakdown
    breakdown_rows = db.execute(
        select(
            group_col.label("group_key"),
            func.count(ModelCallRecord.id).label("call_count"),
            func.coalesce(func.sum(ModelCallRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ModelCallRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(ModelCallRecord.cached_input_tokens), 0).label("cached_tokens"),
            func.coalesce(func.sum(ModelCallRecord.cost_usd), 0.0).label("cost_usd"),
            func.avg(ModelCallRecord.duration_ms).label("avg_duration"),
        )
        .where(base_filter)
        .group_by(group_col)
        .order_by(func.sum(ModelCallRecord.cost_usd).desc())
    ).all()

    breakdown = [
        CostBreakdownItem(
            group_key=str(row.group_key or "unknown"),
            call_count=int(row.call_count),
            total_input_tokens=int(row.input_tokens),
            total_output_tokens=int(row.output_tokens),
            total_cached_tokens=int(row.cached_tokens),
            total_cost_usd=float(row.cost_usd),
            avg_duration_ms=round(float(row.avg_duration), 1) if row.avg_duration is not None else None,
        )
        for row in breakdown_rows
    ]

    return CostAnalyticsResponse(
        period_days=days,
        since=since_str,
        total_call_count=int(totals.call_count),
        total_input_tokens=int(totals.input_tokens),
        total_output_tokens=int(totals.output_tokens),
        total_cached_tokens=int(totals.cached_tokens),
        total_cost_usd=float(totals.cost_usd),
        avg_duration_ms=round(float(totals.avg_duration), 1) if totals.avg_duration is not None else None,
        breakdown=breakdown,
        group_by=group_by,
    )
