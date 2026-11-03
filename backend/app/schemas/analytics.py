from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class CurrencyTotalOut(BaseModel):
    currency: str | None = Field(description="ISO code; null when the document's currency wasn't found.")
    total: Amount
    document_count: int
    average: Amount
    tax_total: Amount = Field(description="Sum of extracted tax on the same documents.")
    discount_total: Amount = Field(description="Sum of extracted discounts on the same documents.")


class AnalyticsOverview(BaseModel):
    total_documents: int
    processed: int = Field(description="COMPLETED + NEEDS_REVIEW.")
    in_progress: int
    needs_review: int
    failed: int
    status_counts: dict[str, int]
    type_counts: dict[str, int] = Field(description="Processed documents by classified type.")
    spend: list[CurrencyTotalOut] = Field(description="Totals per currency; currencies are never mixed.")
    processed_without_total: int = Field(description="Processed documents with no total found.")
    spend_includes_needs_review: int = Field(description="How many documents in `spend` still need review.")


class MonthTotalOut(BaseModel):
    month: str = Field(description="YYYY-MM of the invoice date.")
    currency: str | None
    total: Amount
    document_count: int


class SpendingResponse(BaseModel):
    months: list[MonthTotalOut]
    processed_without_date: int = Field(
        description="Documents with a total but no invoice date (not charted)."
    )
    outside_window: int = Field(
        description="Dated documents older than the chart window (24 months back from the latest date)."
    )


class VendorTotalOut(BaseModel):
    vendor: str
    currency: str | None
    total: Amount
    document_count: int


class VendorsResponse(BaseModel):
    vendors: list[VendorTotalOut]


class CountOut(BaseModel):
    key: str
    count: int


class CompletenessOut(BaseModel):
    field: str
    found: int = Field(description="Processed documents where a value was found (or entered).")
    processed: int


class QualityResponse(BaseModel):
    processed: int
    latency_ms_median: int | None = Field(
        description="Median processing time of successful runs (most recent 500), in ms."
    )
    latency_ms_p95: int | None
    latency_jobs: int = Field(description="How many runs the latency figures are based on.")
    review_reasons: list[CountOut] = Field(
        description="Warning codes by number of processed documents they appear on (top 10)."
    )
    completeness: list[CompletenessOut] = Field(description="How often each key field was found.")
    corrected_fields: list[CountOut] = Field(description="Fields by number of documents a user corrected.")
    documents_corrected: int
