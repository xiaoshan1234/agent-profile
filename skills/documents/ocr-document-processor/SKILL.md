---
name: ocr-document-processor
description: "OCR: text/table extraction from scans, images, PDFs"
---

# OCR Document Processor

Handle OCR-heavy inputs where text must be recovered from images or scanned pages.

## When to Use

- OCR on images and scanned PDFs
- Searchable PDF export
- Structured extraction to text, markdown, JSON, or HTML
- Table extraction from scanned material
- Receipt parsing and business card parsing

## Workflow

1. Decide whether plain OCR, structured extraction, or document-specific parsing is needed.
2. Preprocess noisy inputs before extraction when skew, blur, or shadows are present.
3. Use `scripts/ocr_processor.py` for core OCR tasks.
4. Use the focused helpers when the input is specialized:
   - `scripts/business_card_scanner.py`
   - `scripts/receipt_scanner.py`
5. Return confidence caveats when the source is low quality, rotated, handwritten, or multilingual.

## Guardrails

- Prefer explicit language selection when accuracy matters.
- Do not claim fields are exact when OCR confidence is weak.
- Route non-scanned digital PDFs to `document-converter-suite` instead of OCR by default.
