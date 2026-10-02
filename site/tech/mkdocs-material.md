---
title: Material for MkDocs
category: Infrastructure & delivery
vendor: Martin Donath (squidfunk) and contributors
docs: https://squidfunk.github.io/mkdocs-material/
aliases: [Material for MkDocs, MkDocs Material]
summary: Documentation and blog site generator — Markdown in, searchable static site out.
---

# Material for MkDocs

Material for MkDocs is a theme and set of plugins for MkDocs that turns a folder of Markdown files into a fast,
searchable static website.

## What it is

MkDocs is a Python static-site generator for documentation: you write pages in Markdown, list navigation in
`mkdocs.yml`, and `mkdocs build` produces plain HTML. Material for MkDocs is the theme most people use with it. It
adds responsive layout, light and dark modes, client-side search, code-block annotations, admonitions, tabs, and a
blog plugin with posts, categories and archives.

The output is static files, so it can be hosted anywhere — GitHub Pages, S3, an internal web server — with nothing to
run or patch at request time. `mkdocs serve` gives a live-reloading preview while you write.

## Typical use cases

- Engineering and API documentation kept in the same repo as the code.
- Internal knowledge bases and runbooks.
- Technical blogs.
- Project sites published to GitHub Pages from CI.
- Data catalogues or model cards rendered from Markdown.

## In AI work

Documentation is part of an AI system's control surface: model cards, data-source notes, evaluation results and
runbooks need to be versioned with the code and readable by people who don't open a terminal. Keeping them in Markdown
next to the code, built by CI into a static site, means the docs change in the same pull request as the behaviour they
describe. Mermaid diagrams render natively, which suits architecture and data-flow pictures.

Static output is also a reasonable base for a search or chat assistant over the content, because the pages are plain,
predictable HTML and Markdown.

## In this portfolio

- This blog is built with Material for MkDocs and published to GitHub Pages by
  [GitHub Actions](github-actions.md).
- Every project post, for example [Governance](../blog/posts/governance.md) and
  [Research Q&A](../blog/posts/research-qa-rag.md), is a Markdown file in the site's blog folder.

## Pros and cons

| Pros | Cons |
|---|---|
| Markdown in, static site out — nothing to run in production | Customizing beyond the theme means template overrides |
| Built-in search, dark mode, blog, Mermaid | Some features have historically been sponsor-only first |
| Lives in the repo and builds in CI | Large sites can build slowly |
| Excellent documentation of its own | Python toolchain needed to build, even for a non-Python team |

## Basic usage

A minimal `mkdocs.yml` using the theme:

```yaml
site_name: Team Docs
theme:
  name: material
  palette:
    scheme: default
nav:
  - Home: index.md
```

Install with `pip install mkdocs-material`, then run `mkdocs serve` and open `http://localhost:8000`.

## Documentation

[Material for MkDocs documentation](https://squidfunk.github.io/mkdocs-material/) — official, from the project
maintainer. Source: [github.com/squidfunk/mkdocs-material](https://github.com/squidfunk/mkdocs-material).
