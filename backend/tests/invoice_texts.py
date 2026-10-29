"""Synthetic document texts for extraction tests and the sample dataset.

Fictional companies, people and numbers only. Each entry: (name, text, expected).
``expected`` lists only what the test should assert; omitted fields aren't checked.
"""

from datetime import date
from decimal import Decimal as D

STANDARD_INVOICE = """\
Northstar Studio LLC
88 Harbor Lane, Suite 4
Portland, OR 97201
INVOICE
Invoice Number: NS-1048
Invoice Date: 18/03/2025
Due Date: 17/04/2025
Bill To:
Meridian Cloud Inc.
1200 Pine Street
Seattle, WA 98101
Description  Qty  Unit Price  Amount
Brand identity refinement  1  2,800.00  2,800.00
Web design consultation  8  212.50  1,700.00
Subtotal  4,500.00
Tax (7.1%)  320.00
Total Due  USD 4,820.00
Payment Method: VISA ****4242
Thank you for your business."""

RECEIPT = """\
FIELDNOTES COFFEE
14 Market Street
Receipt #R-30811
Date: 17 Mar 2025 08:42
Cashier: Dana
Flat white  2  4.50  9.00
Croissant  2  3.75  7.50
Subtotal  16.50
Tax  1.36
TOTAL  $17.86
VISA  17.86
Change  0.00
Thank you!"""

GST_INVOICE = """\
Saffron Supplies Pvt Ltd
TAX INVOICE
Invoice No: SS/24-25/0193
Invoice Date: 05-Feb-2025
Bill To: Kaveri Traders, 12 MG Road, Bengaluru
Description  Qty  Rate  Amount
A4 paper ream  10  250.00  2,500.00
Stapler heavy duty  2  450.00  900.00
Sub Total  3,400.00
CGST 9%  306.00
SGST 9%  306.00
Grand Total  INR 4,012.00
Payment: UPI"""

EU_INVOICE = """\
Brücke Logistik GmbH
Rechnung / Invoice
Invoice No.: 2025-0412
Invoice date: 12.03.2025
Description  Qty  Price  Total
Freight Hamburg-Berlin  1  1.249,50  1.249,50
Subtotal  1.249,50
VAT 19%  237,41
Total  EUR 1.486,91"""

MISSING_NUMBER_AND_TAX = """\
Atlas Office Supplies
INVOICE
Date: 26/02/2025
Description  Qty  Price  Amount
Workspace essentials bundle  1  302.00  302.00
Total  302.00"""

TOTALS_MISMATCH = """\
Harbor Freight Logistics
INVOICE
Invoice #: HFL-7712
Invoice Date: 2025-03-08
Description  Qty  Price  Amount
Domestic freight shipment  1  1,975.00  1,975.00
Fuel surcharge  1  60.00  60.00
Subtotal  2,035.00
Tax  160.00
Total  2,295.00"""

AMBIGUOUS_DATE = """\
Paper & Pine Supply
INVOICE
Invoice No: 30944
Invoice Date: 03/04/2025
Subtotal  630.00
Tax  54.20
Total  684.20"""

MALFORMED = """\
Tandem Research
INVOICE
Invoice No: TR-2503
Invoice Date: 31/02/2025
Subtotal  3,500.00
Tax  175.00
Total: see attached"""

CONFLICTING_TOTALS = """\
Maple Street Creative
INVOICE
Invoice No: MSC-7803
Invoice Date: 2025-02-24
Total  1,200.00
Subtotal  1,000.00
Tax  80.00
Total  1,080.00"""

OCR_NOISY = """\
NORTHWIND TRADING C0
lNVOICE  INV-2041
lnvoice Date: 2O25-O3-18
Widget assembly kit  4 x 12.50  50.00
Subtota1  50.00
Tax  4.0O
T0TAL DUE  54.00"""

NOT_AN_INVOICE = """\
Meeting notes
Attendees: product, design
Discussed the roadmap for next quarter.
Follow up next week."""

MULTI_PAGE = (
    """\
Granite Peak Hardware
INVOICE
Invoice Number: GPH-5521
Invoice Date: 2025-01-15
Due Date: 2025-02-14
Description  Qty  Unit Price  Amount
Hex bolts M8 (box of 100)  3  14.00  42.00
Wood screws assorted  5  6.50  32.50
Cordless drill 18V  1  129.00  129.00""",
    """\
Description  Qty  Unit Price  Amount
Safety goggles  4  8.25  33.00
Work gloves  6  4.50  27.00
Subtotal  263.50
Discount  -13.50
Tax  20.00
Total  270.00
Payment Method: Bank transfer""",
)

# --- Harder layouts (Part 7 fixtures; ground truth in backend/samples/ground_truth.json) ---

# Separate VAT column, a wrapped description line containing numbers, PO number, VAT ID, buyer block.
TAX_COLUMN_INVOICE = """Bluewater Analytics Ltd
VAT No: GB 284 7731 06
INVOICE
Invoice Number: BWA-2291
Invoice Date: 2025-04-02
Due Date: 2025-05-02
PO Number: PO-55120
Bill To:
Corvid Health Partners
41 Elm Row, Leeds LS1 4AB
Description  Qty  Unit Price  VAT  Net Amount
Quarterly data platform licence  1  1,200.00  240.00  1,200.00
(April to June 2025, 25 seats)
Onboarding workshop  2  350.00  140.00  700.00
Subtotal  1,900.00
VAT 20%  380.00
Total  GBP 2,280.00
Payment Method: Bank transfer"""

# Vendor and buyer side by side: the text layer interleaves the two columns on each line.
TWO_COLUMN_INVOICE = """Quillon Print Works                          Bill To: Ostara Bakery
22 Foundry Road                              9 Mill Lane
Bristol BS1 6QA                              Bath BA1 2HN
INVOICE
Invoice No: QPW-0087          Invoice Date: 2025-05-14
Description  Qty  Unit Price  Amount
Menu cards A5  500  0.36  180.00
Window decals  4  12.50  50.00
Subtotal  230.00
VAT  46.00
Total  GBP 276.00"""

# Compact till receipt: "qty x item @ price" lines, a weighed item, single-price lines, no table header.
COMPACT_RECEIPT = """GREEN LEAF MARKET
Store 0142  Till 3
12/05/2025 18:21
2 x Oat milk 1L @ 2.10  4.20
Bananas 1.24 kg @ 1.10/kg  1.36
Sourdough loaf  3.80
TOTAL  GBP 9.36
CARD  9.36
VAT included  0.78"""

CASES = {
    "standard_invoice": (
        STANDARD_INVOICE,
        {
            "type": "INVOICE",
            "vendor_name": "Northstar Studio LLC",
            "invoice_number": "NS-1048",
            "invoice_date": date(2025, 3, 18),
            "due_date": date(2025, 4, 17),
            "currency": "USD",
            "subtotal": D("4500.00"),
            "tax": D("320.00"),
            "total": D("4820.00"),
            "payment_method": "Visa",
            "items": 2,
            "status": "COMPLETED",
        },
    ),
    "receipt": (
        RECEIPT,
        {
            "type": "RECEIPT",
            "vendor_name": "FIELDNOTES COFFEE",
            "invoice_number": "R-30811",
            "invoice_date": date(2025, 3, 17),
            "subtotal": D("16.50"),
            "tax": D("1.36"),
            "total": D("17.86"),
            "currency": "USD",
            "payment_method": "Visa",
            "items": 2,
        },
    ),
    "gst_invoice": (
        GST_INVOICE,
        {
            "type": "INVOICE",
            "invoice_number": "SS/24-25/0193",
            "invoice_date": date(2025, 2, 5),
            "currency": "INR",
            "subtotal": D("3400.00"),
            "tax": D("612.00"),
            "total": D("4012.00"),
            "payment_method": "UPI",
            "items": 2,
        },
    ),
    "eu_invoice": (
        EU_INVOICE,
        {
            "type": "INVOICE",
            "invoice_number": "2025-0412",
            "invoice_date": date(2025, 3, 12),
            "currency": "EUR",
            "subtotal": D("1249.50"),
            "tax": D("237.41"),
            "total": D("1486.91"),
            "items": 1,
        },
    ),
}
