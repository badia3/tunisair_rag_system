import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.config import get_settings
from app.rag.vectorstore import add_documents, delete_documents
from app.services.content_store import store_pages
from app.services.ingestion import chunk_documents
from app.services.tunisair import TunisairCrawler, TunisairPage

settings = get_settings()


def _read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Tunisair sync manifest at {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Tunisair sync manifest must be a JSON object: {path}")
    return manifest


def _write_manifest(path: Path, manifest: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise RuntimeError(f"Could not save Tunisair sync manifest at {path}: {exc}") from exc


def _chunks_for_page(page: TunisairPage) -> tuple[str, list[Document], list[str]]:
    digest = hashlib.sha256(f"{page.title}\n{page.text}".encode("utf-8")).hexdigest()
    document = Document(
        page_content=page.text,
        metadata={
            "source": page.url,
            "source_url": page.url,
            "title": page.title,
            "fetched_at": page.fetched_at,
            "language": "fr",
        },
    )
    chunks = chunk_documents([document])
    ids = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{page.url}#chunk-{position}"))
        for position in range(len(chunks))
    ]
    return digest, chunks, ids


def sync_tunisair() -> dict[str, int]:
    # Fetch and validate all allowlisted pages before writing any vectors.
    pages = TunisairCrawler().fetch_allowed_pages()
    manifest_path = Path(settings.tunisair_sync_manifest_path)
    previous = _read_manifest(manifest_path)
    updated = dict(previous)
    indexed_pages = 0
    chunk_count = 0
    content_hashes: dict[str, str] = {}
    prepared_pages = []

    for page in pages:
        digest, chunks, ids = _chunks_for_page(page)
        content_hashes[page.url] = digest
        if not chunks:
            raise RuntimeError(f"Refusing to index an empty Tunisair page: {page.url}")
        prepared_pages.append((page, digest, chunks, ids))

    stored_pages = store_pages(
        Path(settings.tunisair_content_db_path),
        pages,
        content_hashes,
    )

    for page, digest, chunks, ids in prepared_pages:
        old_page = previous.get(page.url, {})
        old_ids = set(old_page.get("vector_ids", []))
        if digest == old_page.get("content_sha256"):
            continue

        add_documents(chunks, ids=ids)
        obsolete_ids = sorted(old_ids - set(ids))
        if obsolete_ids:
            delete_documents(obsolete_ids)
        updated[page.url] = {"content_sha256": digest, "vector_ids": ids}
        indexed_pages += 1
        chunk_count += len(chunks)

    allowed_urls = {page.url for page in pages}
    stale_urls = set(previous) - allowed_urls
    stale_ids = [
        vector_id
        for url in stale_urls
        for vector_id in previous[url].get("vector_ids", [])
    ]
    if stale_ids:
        delete_documents(stale_ids)
    for url in stale_urls:
        updated.pop(url, None)

    _write_manifest(manifest_path, updated)
    return {
        "crawled_pages": len(pages),
        "indexed_pages": indexed_pages,
        "chunks_upserted": chunk_count,
        "unchanged_pages": len(pages) - indexed_pages,
        "stored_pages": stored_pages,
    }
