import argparse
import sys

from langchain_core.documents import Document

from app.services.ingestion import chunk_documents
from app.services.tunisair import TunisairAccessBlocked, TunisairCrawler
from app.services.tunisair_sync import sync_tunisair


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync only the explicitly allowlisted Tunisair French pages."
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and count chunks without changing Pinecone.")
    args = parser.parse_args()

    try:
        if args.dry_run:
            pages = TunisairCrawler().fetch_allowed_pages()
            chunks = sum(
                len(chunk_documents([Document(page_content=page.text)]))
                for page in pages
            )
            print(f"Dry run: {len(pages)} allowlisted pages, {chunks} chunks. No data was changed.")
            for page in pages:
                print(f"{page.url} — {page.title}")
            return 0

        result = sync_tunisair()
        for name, value in result.items():
            print(f"{name}: {value}")
        return 0
    except TunisairAccessBlocked as exc:
        print(f"Sync stopped: {exc}")
        print("No further pages were requested. Do not retry repeatedly or automate a CAPTCHA.")
        return 2
    except Exception as exc:
        print(f"Sync failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
