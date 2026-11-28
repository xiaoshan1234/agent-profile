---
name: ocr-with-python
description: PaddleOCR OCR for scanned PDFs and images (zh/en)
---

# OCR Text Recognition

This skill uses PaddleOCR for text recognition, supporting both Chinese and English.

## Quick Start

### Basic Usage

Perform OCR recognition directly on image or PDF files:

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(lang='ch')
result = ocr.predict("file_path.jpg")
```

## Dependency Installation

Install dependencies before first use:

```bash
pip3 install paddlepaddle paddleocr
```

## Output Format

Recognition results return JSON containing:
- `rec_texts`: List of recognized text
- `rec_scores`: Confidence score for each text

## Typical Use Cases

1. **PDF Scans**: Use PyMuPDF to extract images first, then OCR
2. **Image Text Recognition**: Perform OCR directly on images
3. **Multi-page PDFs**: Process page by page

## Scripts

Common scripts are located in the `scripts/` directory.
