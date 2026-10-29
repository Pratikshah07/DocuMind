from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class CurrencyTotalOut(BaseModel):
    currency: str | None = Field(description="ISO code; null when the document's currency wasn't found.")
    total: Amount
    document_count: int
    average: Amount


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


class VendorTotalOut(BaseModel):
    vendor: str
    currency: str | None
    total: Amount
    document_count: int


class VendorsResponse(BaseModel):
    vendors: list[VendorTotalOut]
