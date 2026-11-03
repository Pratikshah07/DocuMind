from fastapi import APIRouter

from app.api.deps import AnalyticsServiceDep
from app.core.errors import error_responses
from app.schemas.analytics import (
    AnalyticsOverview,
    CompletenessOut,
    CountOut,
    CurrencyTotalOut,
    MonthTotalOut,
    QualityResponse,
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
                currency=c.currency,
                total=c.total,
                document_count=c.document_count,
                average=c.average,
                tax_total=c.tax_total,
                discount_total=c.discount_total,
            )
            for c in data.spend
        ],
    )


@router.get(
    "/spending",
    response_model=SpendingResponse,
    summary="Monthly spending",
    description="Totals per month (by invoice date) and currency, for the 24 months up to the latest "
    "dated document.",
    responses=error_responses(401, 422),
)
def spending(service: AnalyticsServiceDep) -> SpendingResponse:
    data = service.spending()
    return SpendingResponse(
        months=[MonthTotalOut(**vars(m)) for m in data.months],
        processed_without_date=data.processed_without_date,
        outside_window=data.outside_window,
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


@router.get(
    "/quality",
    response_model=QualityResponse,
    summary="Processing and extraction quality",
    description=(
        "Processing latency, the most frequent review reasons, how often key fields are found, and "
        "which fields users corrected. Computed from this workspace's records; no accuracy is implied."
    ),
    responses=error_responses(401, 422),
)
def quality(service: AnalyticsServiceDep) -> QualityResponse:
    data = service.quality()
    return QualityResponse(
        processed=data.processed,
        latency_ms_median=data.latency_ms_median,
        latency_ms_p95=data.latency_ms_p95,
        latency_jobs=data.latency_jobs,
        review_reasons=[CountOut(**vars(c)) for c in data.review_reasons],
        completeness=[CompletenessOut(**vars(c)) for c in data.completeness],
        corrected_fields=[CountOut(**vars(c)) for c in data.corrected_fields],
        documents_corrected=data.documents_corrected,
    )
