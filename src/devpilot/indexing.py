from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import tree_sitter_python
from sqlalchemy import select
from sqlalchemy.orm import Session
from tree_sitter import Language, Node, Parser

from devpilot.db import CodeDocumentRecord, CodeSymbolRecord, RepositoryIndexRecord

TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_PATTERN.findall(value):
        for camel_part in CAMEL_BOUNDARY.sub(" ", raw).split():
            tokens.extend(part.lower() for part in camel_part.split("_") if part)
    return tokens


@dataclass(frozen=True)
class CodeChunk:
    id: str
    path: str
    language: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    content: str
    tokens: list[str]
    references: list[str]


@dataclass(frozen=True)
class ParsedSymbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    content: str
    references: list[str]


class CodeParser(Protocol):
    language: str
    extensions: tuple[str, ...]
    version: str

    def parse(self, path: str, source: bytes) -> list[ParsedSymbol]: ...


class PythonTreeSitterParser:
    language = "Python"
    extensions: tuple[str, ...] = (".py",)
    version = "tree-sitter-python-0.25"

    def __init__(self) -> None:
        language = Language(tree_sitter_python.language())
        self.parser = Parser(language)

    def parse(self, path: str, source: bytes) -> list[ParsedSymbol]:
        tree = self.parser.parse(source)
        symbols = [self._module_symbol(path, source, tree.root_node)]
        self._walk(tree.root_node, source, [], symbols)
        return symbols

    def _walk(
        self,
        node: Node,
        source: bytes,
        scope: list[str],
        symbols: list[ParsedSymbol],
    ) -> None:
        is_symbol = node.type in {"class_definition", "function_definition"}
        next_scope = scope
        if is_symbol:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = self._text(source, name_node)
                qualified_name = ".".join([*scope, name])
                body = node.child_by_field_name("body")
                signature_end = body.start_byte if body is not None else node.end_byte
                signature = (
                    source[node.start_byte : signature_end]
                    .decode("utf-8", errors="replace")
                    .rstrip()
                    .rstrip(":")
                )
                content = self._text(source, node)
                symbols.append(
                    ParsedSymbol(
                        name=name,
                        qualified_name=qualified_name,
                        kind="class" if node.type == "class_definition" else "function",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        signature=signature,
                        content=content,
                        references=self._references(node, source, skip_nested=True),
                    )
                )
                next_scope = [*scope, name]
        for child in node.children:
            self._walk(child, source, next_scope, symbols)

    def _module_symbol(self, path: str, source: bytes, root: Node) -> ParsedSymbol:
        text = source.decode("utf-8", errors="replace")
        return ParsedSymbol(
            name="<module>",
            qualified_name=path.replace("/", "."),
            kind="module",
            start_line=1,
            end_line=max(root.end_point.row + 1, 1),
            signature=path,
            content=text,
            references=self._references(root, source, skip_nested=False),
        )

    def _references(self, root: Node, source: bytes, *, skip_nested: bool) -> list[str]:
        references: set[str] = set()
        stack = list(root.children)
        while stack:
            node = stack.pop()
            if skip_nested and node.type in {"class_definition", "function_definition"}:
                continue
            if node.type == "call":
                function = node.child_by_field_name("function")
                if function is not None:
                    references.add(self._text(source, function))
            elif node.type in {"import_statement", "import_from_statement"}:
                references.add(self._text(source, node))
            stack.extend(node.children)
        return sorted(references)

    @staticmethod
    def _text(source: bytes, node: Node) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


class RepositoryIndexer:
    def __init__(self, session: Session, parsers: list[CodeParser] | None = None) -> None:
        self.session = session
        self.parsers = parsers or [PythonTreeSitterParser()]

    def index(self, snapshot: dict[str, object]) -> list[CodeChunk]:
        root = str(snapshot["root"])
        tree_digest = str(snapshot["tree_digest"])
        existing = self.session.scalar(
            select(RepositoryIndexRecord).where(
                RepositoryIndexRecord.repository_root == root,
                RepositoryIndexRecord.tree_digest == tree_digest,
            )
        )
        if existing is not None:
            return self._load_chunks(existing.id)

        raw_files = snapshot.get("files", [])
        files = [str(item) for item in raw_files] if isinstance(raw_files, list) else []
        parser_version = ",".join(parser.version for parser in self.parsers)
        index = RepositoryIndexRecord(
            repository_root=root,
            tree_digest=tree_digest,
            parser_version=parser_version,
            file_count=0,
        )
        self.session.add(index)
        self.session.flush()
        indexed_files = 0
        for relative_path in files:
            parser = self._parser_for(relative_path)
            if parser is None:
                continue
            absolute_path = Path(root) / relative_path
            try:
                source = absolute_path.read_bytes()
            except OSError:
                continue
            document = CodeDocumentRecord(
                index_id=index.id,
                path=relative_path,
                language=parser.language,
                content_digest=hashlib.sha256(source).hexdigest(),
                line_count=source.count(b"\n") + 1,
            )
            self.session.add(document)
            self.session.flush()
            for symbol in parser.parse(relative_path, source):
                combined = " ".join(
                    [relative_path, symbol.qualified_name, symbol.signature, symbol.content]
                )
                self.session.add(
                    CodeSymbolRecord(
                        document_id=document.id,
                        name=symbol.name,
                        qualified_name=symbol.qualified_name,
                        kind=symbol.kind,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        signature=symbol.signature,
                        content=symbol.content,
                        tokens=tokenize(combined),
                        references=symbol.references,
                    )
                )
            indexed_files += 1
        index.file_count = indexed_files
        self.session.flush()
        return self._load_chunks(index.id)

    def _parser_for(self, path: str) -> CodeParser | None:
        suffix = Path(path).suffix.lower()
        return next((parser for parser in self.parsers if suffix in parser.extensions), None)

    def _load_chunks(self, index_id: str) -> list[CodeChunk]:
        rows = self.session.execute(
            select(CodeSymbolRecord, CodeDocumentRecord)
            .join(CodeDocumentRecord, CodeSymbolRecord.document_id == CodeDocumentRecord.id)
            .where(CodeDocumentRecord.index_id == index_id)
        ).all()
        return [
            CodeChunk(
                id=symbol.id,
                path=document.path,
                language=document.language,
                name=symbol.name,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                signature=symbol.signature,
                content=symbol.content,
                tokens=list(symbol.tokens),
                references=list(symbol.references),
            )
            for symbol, document in rows
        ]
