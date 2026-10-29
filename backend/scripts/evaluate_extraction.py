"""Measure extraction quality (and timings) on the labelled synthetic samples.

Runs the production text path (PDF text layer, or preprocessing + Tesseract OCR) and the
deterministic extractor on every sample in samples/ground_truth.json, then scores the
result with app.services.evaluation. No database is used.

    cd backend
    python scripts/evaluate_extraction.py                 # print a report
    python scripts/evaluate_extraction.py --out ../docs/EVALUATION.md

The numbers describe these synthetic samples only. Timings are wall-clock on the machine
running the script; Tesseract runs as a subprocess, so its memory is not in "peak MB".
"""

import argparse
import json
import platform
import sys
import time
import tracemalloc
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.evaluation import resolve_truth, score_sample, summarize  # noqa: E402
from app.services.extraction_service import ExtractionEngine, extraction_config  # noqa: E402
from app.services.ocr import TesseractOCR  # noqa: E402
from app.services.pipeline import DocumentProcessor, ProcessorConfig  # noqa: E402

SAMPLES = BACKEND / "samples"
MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _json(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def run(only: list[str] | None = None) -> tuple[list, list[dict]]:
    settings = get_settings()
    ocr = TesseractOCR(cmd=settings.tesseract_cmd, language=settings.ocr_language)
    engine = ExtractionEngine(extraction_config(settings))
    processor = DocumentProcessor(
        session_factory=None,  # read_pages never touches the database
        storage=None,  # type: ignore[arg-type]
        ocr=ocr,
        config=ProcessorConfig(
            pdf_steps=tuple(settings.preprocess_pdf_steps), image_steps=tuple(settings.preprocess_image_steps)
        ),
        extraction=engine,
    )
    truth_all = json.loads((SAMPLES / "ground_truth.json").read_text(encoding="utf-8"))
    scores, timings = [], []
    for name in sorted(k for k in truth_all if not k.startswith("_")):
        if only and name not in only:
            continue
        content = (SAMPLES / name).read_bytes()
        tracemalloc.start()
        t0 = time.perf_counter()
        pages = processor.read_pages(content, MIME[Path(name).suffix.lower()])
        t1 = time.perf_counter()
        from app.services.extraction.types import PageText

        outcome = engine.validate(
            engine.extract([PageText(p.page_number, p.text, p.text_source, p.ocr_confidence) for p in pages])
        )
        t2 = time.perf_counter()
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        fields = {n: _json(f.normalized) for n, f in outcome.fields.items()}
        items = [
            {"description": i.description, "quantity": i.quantity, "unit_price": i.unit_price,
             "total": i.total}  # fmt: skip
            for i in outcome.line_items
        ]
        scores.append(
            score_sample(
                name,
                resolve_truth(truth_all, name),
                document_type=outcome.document_type.value,
                fields=fields,
                line_items=items,
            )
        )
        timings.append(
            {
                "sample": name,
                "bytes": len(content),
                "pages": len(pages),
                "ocr_pages": sum(p.text_source.value == "OCR" for p in pages),
                "read_ms": round((t1 - t0) * 1000),
                "extract_ms": round((t2 - t1) * 1000, 1),
                "peak_mb": round(peak / 1_048_576, 1),
                "status": outcome.status.value,
            }
        )
    return scores, timings


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def report(scores, timings) -> str:
    s = summarize(scores)
    lines = [
        "| Metric | Result |",
        "|---|---|",
        f"| Samples | {s.samples} |",
        f"| Document type correct | {_pct(s.type_accuracy)} |",
        f"| Fields correct (all scored) | {s.fields_correct}/{s.fields_scored} "
        f"({_pct(s.fields_correct / s.fields_scored)}) |",
        f"| Fields present in the document and read correctly | {s.present_correct}/{s.present_fields} "
        f"({_pct(s.present_correct / s.present_fields)}) |",
        f"| False positives (value extracted where the document has none) | {s.false_positives} |",
        f"| Line-item row precision / recall | {_pct(s.row_precision)} / {_pct(s.row_recall)} |",
        f"| Line-item cell accuracy (matched rows) | {_pct(s.cell_accuracy)} |",
        "",
        "| Sample | Pages (OCR) | Fields wrong | Rows matched/expected/extracted | Read ms | Extract ms "
        "| Peak MB | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for score, t in zip(scores, timings, strict=True):
        wrong = ", ".join(f"{f.name} ({f.kind})" for f in score.field_errors) or "—"
        if not score.type_correct:
            wrong = "document type; " + wrong
        lines.append(
            f"| {score.sample} | {t['pages']} ({t['ocr_pages']}) | {wrong} | "
            f"{score.rows_matched}/{score.rows_expected}/{score.rows_extracted} | {t['read_ms']} | "
            f"{t['extract_ms']} | {t['peak_mb']} | {t['status']} |"
        )
    lines += [
        "",
        f"Environment: {platform.platform()}, Python {platform.python_version()}, "
        f"{platform.processor() or platform.machine()}, Tesseract {TesseractOCR().check_available()}.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="Write the markdown report to this file.")
    parser.add_argument("--details", action="store_true", help="Print each wrong field with values.")
    parser.add_argument("samples", nargs="*")
    args = parser.parse_args()
    scores, timings = run(args.samples or None)
    text = report(scores, timings)
    print(text)
    if args.details:
        for score in scores:
            for f in score.field_errors:
                print(f"{score.sample}: {f.name}: expected {f.expected!r}, got {f.got!r}")
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
