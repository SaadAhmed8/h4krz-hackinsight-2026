"""Official external source metadata and passage extraction.

The PDFs and extracted text files are stored locally so retrieval is reproducible
and does not need network access. Source metadata records the official URL,
publisher, publication date, licence, checksums, and citation text.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data/external/rag_sources.json"
MAX_PASSAGE_CHARS = 1800
PAGE_MARKER = re.compile(r"\[\[PAGE\s+(\d+)\]\]")


def _resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


@dataclass(frozen=True)
class ExternalSource:
    id: str
    title: str
    short_title: str
    publisher: str
    publication_date: str
    source_type: str
    jurisdiction: str
    url: str
    pdf_url: str
    local_file: Path
    text_file: Path
    pdf_sha256: str
    text_sha256: str
    license: str
    citation: str
    notes: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExternalSource":
        required = (
            "id",
            "title",
            "short_title",
            "publisher",
            "publication_date",
            "source_type",
            "jurisdiction",
            "url",
            "pdf_url",
            "local_file",
            "text_file",
            "pdf_sha256",
            "text_sha256",
            "license",
            "citation",
        )
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise ValueError(f"External source is missing fields: {', '.join(missing)}")
        return cls(
            id=str(value["id"]),
            title=str(value["title"]),
            short_title=str(value["short_title"]),
            publisher=str(value["publisher"]),
            publication_date=str(value["publication_date"]),
            source_type=str(value["source_type"]),
            jurisdiction=str(value["jurisdiction"]),
            url=str(value["url"]),
            pdf_url=str(value["pdf_url"]),
            local_file=_resolve(str(value["local_file"])),
            text_file=_resolve(str(value["text_file"])),
            pdf_sha256=str(value["pdf_sha256"]),
            text_sha256=str(value["text_sha256"]),
            license=str(value["license"]),
            citation=str(value["citation"]),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True)
class ExternalPassage:
    source: ExternalSource
    page: int
    part: int
    text: str


def load_external_sources(
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
) -> tuple[ExternalSource, ...]:
    path = _resolve(metadata_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = tuple(ExternalSource.from_mapping(item) for item in data.get("sources", []))
    if not sources:
        raise ValueError(f"No external sources are declared in {path}")

    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ValueError(f"Duplicate external source ID: {source.id}")
        seen.add(source.id)
        if not source.pdf_url.startswith(("https://", "http://")):
            raise ValueError(f"External source URL must be HTTP(S): {source.pdf_url}")
        if not source.local_file.exists():
            raise FileNotFoundError(f"External source PDF is missing: {source.local_file}")
        if not source.text_file.exists():
            raise FileNotFoundError(
                f"Extracted text is missing: {source.text_file}. "
                "Run `python -m src.rag.external_sources --refresh`."
            )
    return sources


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract page-delimited text with PyMuPDF.

    This is only used to rebuild the checked-in text cache. Runtime retrieval
    reads the cached text file, so ordinary tests do not parse PDFs.
    """

    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to rebuild external source text. "
            "Install dependencies from requirements.txt."
        ) from exc

    path = _resolve(pdf_path)
    document = pymupdf.open(path)
    pages = [page.get_text("text") for page in document]
    return "\n\n".join(
        f"[[PAGE {index + 1}]]\n{page_text}" for index, page_text in enumerate(pages)
    )


def refresh_external_texts(
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
) -> tuple[Path, ...]:
    """Rebuild cached text files from the locally stored PDFs."""

    metadata = _resolve(metadata_path)
    data = json.loads(metadata.read_text(encoding="utf-8"))
    written: list[Path] = []
    for item in data.get("sources", []):
        source = ExternalSource.from_mapping(item)
        text = extract_pdf_text(source.local_file)
        source.text_file.parent.mkdir(parents=True, exist_ok=True)
        source.text_file.write_text(text, encoding="utf-8")
        written.append(source.text_file)
    return tuple(written)


def _normalise_page_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def split_passage(text: str, max_chars: int = MAX_PASSAGE_CHARS) -> list[str]:
    """Split a page into stable, non-overlapping text passages."""

    text = _normalise_page_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        split_at = window.rfind("\n\n")
        if split_at < max_chars * 0.55:
            split_at = window.rfind("\n")
        if split_at < max_chars * 0.55:
            split_at = window.rfind(". ")
        if split_at < max_chars * 0.55:
            split_at = window.rfind(" ")
        if split_at < max_chars * 0.55:
            split_at = max_chars
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _page_texts(text: str) -> list[tuple[int, str]]:
    matches = list(PAGE_MARKER.finditer(text))
    if not matches:
        return [(1, text)]
    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        page = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((page, text[start:end]))
    return pages


def iter_external_passages(
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
) -> Iterable[ExternalPassage]:
    for source in load_external_sources(metadata_path):
        text = source.text_file.read_text(encoding="utf-8")
        for page, page_text in _page_texts(text):
            for part, passage in enumerate(split_passage(page_text), start=1):
                yield ExternalPassage(
                    source=source,
                    page=page,
                    part=part,
                    text=passage,
                )


def source_as_dict(source: ExternalSource) -> dict[str, str]:
    return {
        "source_id": source.id,
        "source_title": source.title,
        "source_short_title": source.short_title,
        "publisher": source.publisher,
        "publication_date": source.publication_date,
        "source_type": source.source_type,
        "jurisdiction": source.jurisdiction,
        "url": source.url,
        "pdf_url": source.pdf_url,
        "local_file": _relative(source.local_file),
        "license": source.license,
        "citation": source.citation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild cached text files from the local official PDFs.",
    )
    args = parser.parse_args()
    if args.refresh:
        for path in refresh_external_texts():
            print(f"Wrote {_relative(path)}")
    else:
        for source in load_external_sources():
            print(f"{source.id}: {source.title} ({source.publication_date})")


if __name__ == "__main__":
    main()
