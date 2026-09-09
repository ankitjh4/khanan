#!/usr/bin/env python3
"""Render selected PDF pages to PNG for OCR fallback.

This helper is intentionally small because the bundled workspace Python owns the
PDF rendering dependencies, while the project virtualenv owns the geospatial
stack used by the main inventory builder.
"""

import argparse
from pathlib import Path

import pdfplumber


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("pages", nargs="+", type=int, help="Zero-based page indexes")
    parser.add_argument("--resolution", type=int, default=240)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with pdfplumber.open(args.pdf) as document:
        for page_index in args.pages:
            if not 0 <= page_index < len(document.pages):
                raise IndexError(f"Page index {page_index} outside {args.pdf}")
            image = document.pages[page_index].to_image(resolution=args.resolution)
            image.save(args.output_dir / f"page_{page_index + 1:03d}.png")


if __name__ == "__main__":
    main()
