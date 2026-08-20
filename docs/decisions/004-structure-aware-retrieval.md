# ADR 004: Combine lexical, symbol, path, and reference evidence

**Status:** accepted for the Python milestone

## Context

Fixed-size text chunks split functions and mix unrelated symbols. Pure semantic similarity can
retrieve an older implementation with similar wording, while exact keyword search misses naming
variations such as `submitOrder` and `submit_order`.

Tree-sitter produces a concrete syntax tree and remains useful when source contains syntax errors.
The official Python binding and grammar ship prebuilt wheels, so the parser does not require a
local compiler. See the [official Python binding](https://github.com/tree-sitter/py-tree-sitter)
and [Python grammar](https://github.com/tree-sitter/tree-sitter-python).

## Decision

DevPilot indexes modules, classes, and functions as separate chunks. Retrieval combines:

- BM25 term relevance
- exact symbol-name overlap
- repository path overlap
- referenced-call overlap
- a hard context token budget

The parser is behind a language-neutral protocol. Python is the first registered grammar; Java
and TypeScript can be added without changing retrieval.

## Alternatives

- **Fixed text chunks:** simplest, but break structural boundaries.
- **Vector search only:** useful for semantic paraphrases, but requires a model and can confuse
  similarly described symbols.
- **Knowledge graph only:** precise for resolved references, but incomplete in dynamic languages.

## Consequences

The initial retriever runs offline and is reproducible. Embeddings and pgvector will later add a
semantic candidate source, while symbol and lexical evidence remain available for filtering and
explanation. Retrieval changes are evaluated with Hit@1, Hit@5, and mean reciprocal rank.

