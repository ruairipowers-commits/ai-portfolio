---
title: PyMuPDF
category: Search & retrieval
vendor: Artifex Software Inc.
docs: https://pymupdf.readthedocs.io/en/latest/
aliases: [PyMuPDF]
summary: Fast Python library for reading PDFs page by page — text, images, layout, metadata.
---

# PyMuPDF

PyMuPDF is a Python library for opening PDFs and other documents and extracting their text, images and structure, page by page.

## What it is

PyMuPDF is maintained by Artifex Software, the company behind the MuPDF rendering engine it wraps. You open a document with `pymupdf.open()`, iterate over its pages, and call `page.get_text()` for plain text or richer variants for words, blocks and positions. It can also render pages to images, read metadata and annotations, and modify or create PDFs. Besides PDF it reads formats such as EPUB, MOBI and plain text. For scanned pages with no text layer, it can call OCR.

Artifex also publishes PyMuPDF4LLM, a companion package that converts documents to Markdown or JSON for LLM and RAG pipelines.

Licensing needs checking before you ship: the open-source edition is GNU AGPL v3, and Artifex sells commercial licences for proprietary applications.

## Typical use cases

- Extracting text from research reports, filings and prospectuses for search.
- Keeping page numbers with each chunk so answers can cite a page.
- Pulling tables, images or metadata out of document archives.
- Rendering page thumbnails for a review screen.
- Batch conversion of document collections to text or Markdown.

## In AI work

Retrieval quality starts at parsing. If text comes out in the wrong order or loses its page, every later step — chunking, embeddings, citations — inherits the error. Parsing page by page with PyMuPDF keeps a page number on every chunk, so an answer can cite "report X, page 12" and a reviewer can check it. It runs locally with no external service, which matters when the documents are licensed research that cannot be sent to a third-party parser.

## In this portfolio

- [Research Q&A](../blog/posts/research-qa-rag.md): PyMuPDF parses research PDFs page by page; the pages are indexed in one [SQLite](sqlite.md) file for [FTS5](sqlite-fts5.md) keyword search and [sqlite-vec](sqlite-vec.md) vector search.

## Pros and cons

| Pros | Cons |
|---|---|
| Fast, local, no external service | AGPL licence; proprietary use needs a commercial licence |
| Page-level access keeps citations precise | Reading order on complex multi-column layouts can need tuning |
| Handles text, images, metadata and rendering | Scanned documents need an OCR step |
| Companion package for Markdown output | Tables are harder than plain text to extract reliably |

## Basic usage

Open a PDF and print the text of each page with its page number:

```python
import pymupdf

doc = pymupdf.open("report.pdf")
for page in doc:
    text = page.get_text()
    print(f"--- page {page.number + 1} ---")
    print(text[:500])
```

## Documentation

[PyMuPDF documentation](https://pymupdf.readthedocs.io/en/latest/) — official, from Artifex Software. Source and licence: [pymupdf/PyMuPDF on GitHub](https://github.com/pymupdf/pymupdf).
