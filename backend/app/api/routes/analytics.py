from fastapi import APIRouter

from app.api.deps import AnalyticsServiceDep
from app.core.errors import error_responses
from app.schemas.analytics import (
    AnalyticsOverview,
    CurrencyTotalOut,
    MonthTotalOut,
    SpendingResponse,
    VendorsResponse,
    VendorTotalOut,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/overview",
    response_model=AnalyticsOverview,
    summary="Workspace overview",
    description="Document counts by status and type, and spend per currency from processed documents.",
    responses=error_responses(401, 422),
)
def overview(service: AnalyticsServiceDep) -> AnalyticsOverview:
    data = service.overview()
    return AnalyticsOverview(
        **{k: v for k, v in vars(data).items() if k != "spend"},
        spend=[
            CurrencyTotalOut(
                currency=c.currency, total=c.total, document_count=c.document_count, average=c.average
            )
            for c in data.spend
        ],
    )


@router.get(
    "/spending",
    response_model=SpendingResponse,
    summary="Monthly spending",
    description="Totals per month (by invoice date) and currency.",
    responses=error_responses(401, 422),
)
def spending(service: AnalyticsServiceDep) -> SpendingResponse:
    data = service.spending()
    return SpendingResponse(
        months=[MonthTotalOut(**vars(m)) for m in data.months],
        processed_without_date=data.processed_without_date,
    )


@router.get(
    "/vendors",
    response_model=VendorsResponse,
    summary="Top vendors",
    description="Vendors with the highest totals (per currency), top 10.",
    responses=error_responses(401, 422),
)
def vendors(service: AnalyticsServiceDep) -> VendorsResponse:
    return VendorsResponse(vendors=[VendorTotalOut(**vars(v)) for v in service.vendors()])
