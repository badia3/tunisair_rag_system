import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request
from unittest.mock import Mock, patch

from langchain_core.documents import Document

from build_pages import build_site
from app.rag import vectorstore
from app.rag import workflow
from app.rag.state import EvidenceGrade, RouteDecision
from app.services.airports import AIRPORTS
from app.services import tunisair_sync
from app.services import tunisair as tunisair_service
from app.services.tunisair import (
    ALLOWED_PAGE_URLS,
    BOOKING_HOST,
    TunisairAccessBlocked,
    TunisairCrawler,
    TunisairPage,
    build_booking_url,
)


class TunisairAllowlistTests(unittest.TestCase):
    def test_only_the_four_explicit_landing_pages_are_fetched(self):
        crawler = TunisairCrawler()
        robots = type("AllowAll", (), {"can_fetch": lambda *_: True})()
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        response = (b"<html><title>Tunisair</title><body>Official Tunisair page</body></html>", headers)

        with (
            patch.object(crawler, "_robots_for", return_value=robots),
            patch.object(crawler, "_fetch", return_value=(*response, ALLOWED_PAGE_URLS[0])) as fetch,
        ):
            fetch.side_effect = [
                (*response, url)
                for url in ALLOWED_PAGE_URLS
            ]
            pages = crawler.fetch_allowed_pages()

        self.assertEqual(list(ALLOWED_PAGE_URLS), [page.url for page in pages])
        self.assertEqual(4, fetch.call_count)
        self.assertEqual(list(ALLOWED_PAGE_URLS), [call.args[0] for call in fetch.call_args_list])

    def test_crawler_rejects_non_allowlisted_routes_without_requesting_them(self):
        crawler = TunisairCrawler()
        with patch.object(crawler, "_open") as open_page:
            with self.assertRaises(ValueError):
                crawler._fetch("https://www.tunisair.com/fr/offres/some-offer")
        open_page.assert_not_called()

    def test_challenge_or_forbidden_page_stops_without_retrying(self):
        crawler = TunisairCrawler()
        robots = type("AllowAll", (), {"can_fetch": lambda *_: True})()
        denied = HTTPError(
            ALLOWED_PAGE_URLS[0], 403, "Forbidden", Message(), None
        )
        with (
            patch.object(crawler, "_robots_for", return_value=robots),
            patch.object(crawler, "_open", side_effect=denied) as open_page,
        ):
            with self.assertRaises(TunisairAccessBlocked):
                crawler.fetch_allowed_pages()
        open_page.assert_called_once()

    def test_redirect_handler_does_not_follow_redirects(self):
        crawler = TunisairCrawler()
        opener = Mock()
        with patch.object(tunisair_service, "build_opener", return_value=opener) as build_opener:
            crawler._open(Request(ALLOWED_PAGE_URLS[0]))

        redirect_handler = build_opener.call_args.args[0]
        self.assertIsNone(
            redirect_handler.redirect_request(
                Request(ALLOWED_PAGE_URLS[0]),
                None,
                302,
                "Found",
                Message(),
                "https://example.com/redirect",
            )
        )
        opener.open.assert_called_once()

    def test_booking_link_uses_validated_codes_and_dates(self):
        url = build_booking_url("tun", "par", "2026-11-11", "2026-11-12")
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        self.assertEqual(BOOKING_HOST, parsed.hostname)
        self.assertEqual("/plnext/tunisairDX/Override.action", parsed.path)
        self.assertEqual(["TUN"], params["B_LOCATION"])
        self.assertEqual(["PAR"], params["E_LOCATION"])
        self.assertEqual(["202611110000"], params["B_DATE"])
        self.assertEqual(["202611120000"], params["E_DATE"])
        self.assertEqual("/TIMR", parsed.fragment)

    def test_booking_link_rejects_bad_codes_or_date_order(self):
        with self.assertRaises(ValueError):
            build_booking_url("TUN", "https://example.com", "2026-11-11", "2026-11-12")
        with self.assertRaises(ValueError):
            build_booking_url("TUN", "PAR", "2026-11-12", "2026-11-11")

    def test_booking_route_generates_a_link_without_fetching_booking_host(self):
        state = {
            "question": "TUN to PAR, depart 2026-11-11, return 2026-11-12",
            "flight_search": {
                "origin_code": "TUN",
                "destination_code": "PAR",
                "departure_date": "2026-11-11",
                "return_date": "2026-11-12",
            },
            "trace": [],
        }
        model = Mock()
        model.invoke.return_value.content = "Open the official timetable link."

        with patch.object(workflow, "llm", return_value=model):
            result = workflow.create_booking_link(state)

        self.assertEqual("tunisair_booking_link", result["source_used"])
        self.assertEqual(BOOKING_HOST, urlsplit(result["citations"][0]["url"]).hostname)
        self.assertIn("booking site not fetched", result["trace"][0])


class LLMProviderTests(unittest.TestCase):
    def test_openai_provider_uses_configured_model_and_api_key(self):
        config = SimpleNamespace(
            llm_provider="openai",
            openai_api_key="test-key",
            openai_chat_model="gpt-4o-mini",
        )
        with (
            patch.object(workflow, "settings", config),
            patch.object(workflow, "_llm", None),
            patch.object(workflow, "ChatOpenAI") as chat_openai,
        ):
            result = workflow.llm()

        chat_openai.assert_called_once_with(
            model="gpt-4o-mini",
            api_key="test-key",
            temperature=0,
        )
        self.assertIs(result, chat_openai.return_value)

    def test_openai_provider_requires_api_key(self):
        config = SimpleNamespace(
            llm_provider="openai",
            openai_api_key="",
            openai_chat_model="gpt-4o-mini",
        )
        with (
            patch.object(workflow, "settings", config),
            patch.object(workflow, "_llm", None),
            patch.object(workflow, "ChatOpenAI") as chat_openai,
        ):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is required"):
                workflow.llm()

        chat_openai.assert_not_called()

    def test_ollama_remains_the_default_provider(self):
        config = SimpleNamespace(
            llm_provider="ollama",
            ollama_chat_model="llama3.2",
            ollama_base_url="http://localhost:11434",
        )
        with (
            patch.object(workflow, "settings", config),
            patch.object(workflow, "_llm", None),
            patch.object(workflow, "ChatOllama") as chat_ollama,
        ):
            result = workflow.llm()

        chat_ollama.assert_called_once_with(
            model="llama3.2",
            base_url="http://localhost:11434",
            temperature=0,
        )
        self.assertIs(result, chat_ollama.return_value)


class GitHubPagesBuildTests(unittest.TestCase):
    def test_build_renders_template_and_static_assets_for_pages_subpath(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            build_site(output_dir, "https://api.example.com/")

            html = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="static/css/style.css"', html)
            self.assertIn('src="static/js/app.js"', html)
            self.assertIn('"apiBaseUrl": "https://api.example.com"', html)
            self.assertIn('"staticPages": true', html)
            self.assertTrue((output_dir / "static" / "css" / "style.css").exists())
            self.assertTrue((output_dir / "static" / "js" / "app.js").exists())

    def test_build_rejects_non_https_api_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be an HTTPS base URL"):
                build_site(Path(temp_dir), "http://api.example.com")

    def test_build_without_backend_url_keeps_static_page_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            build_site(output_dir)

            html = (output_dir / "index.html").read_text(encoding="utf-8")
            app_js = (output_dir / "static" / "js" / "app.js").read_text(encoding="utf-8")
            self.assertIn('"apiBaseUrl": ""', html)
            self.assertIn("Le service de chat n’est pas encore configuré", app_js)


class WorkflowStructuredOutputTests(unittest.TestCase):
    def test_flight_form_airports_are_unique_and_available_to_route_parser(self):
        codes = [code for code, _ in AIRPORTS]

        self.assertEqual(49, len(codes))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual("ABJ", workflow._extract_flight_search("Tunis to Abidjan")["destination_code"])
        self.assertEqual("GVA", workflow._extract_flight_search("Montréal to Genève")["destination_code"])

    def test_user_link_request_returns_the_offers_page_url(self):
        result = workflow.ask("Donne-moi le lien des offres Tunisair")

        self.assertEqual("official_page_link", result["source_used"])
        self.assertEqual(
            "https://www.tunisair.com/fr/offres",
            result["citations"][0]["url"],
        )
        self.assertIn(result["citations"][0]["url"], result["answer"])

    def test_live_flight_status_uses_current_page_not_weekly_indexed_data(self):
        result = workflow.ask("Quel est le statut des vols en cours ?")

        self.assertEqual("live_flight_status", result["source_used"])
        self.assertIn("peuvent ne plus être à jour", result["answer"])
        self.assertEqual(
            "https://www.tunisair.com/fr/vols-en-cours",
            result["citations"][0]["url"],
        )

    def test_fare_question_routes_to_booking_and_extracts_tunis_montreal(self):
        state = {
            "question": "Quel est le prix du vol Tunis-Montréal ?",
            "trace": [],
        }

        with patch.object(workflow, "llm") as model:
            result = workflow.route_question(state)

        model.assert_not_called()
        self.assertEqual("booking", result["source_used"])
        self.assertEqual("TUN", result["flight_search"]["origin_code"])
        self.assertEqual("YUL", result["flight_search"]["destination_code"])
        self.assertIsNone(result["flight_search"]["departure_date"])
        self.assertIsNone(result["flight_search"]["return_date"])

    def test_flight_search_extracts_explicit_french_dates_in_order(self):
        search = workflow._extract_flight_search(
            "Vol Tunis-Montréal le 20 novembre 2026 et retour le 27 novembre 2026"
        )

        self.assertEqual("TUN", search["origin_code"])
        self.assertEqual("YUL", search["destination_code"])
        self.assertEqual("2026-11-20", search["departure_date"])
        self.assertEqual("2026-11-27", search["return_date"])

    def test_incomplete_fare_search_links_to_official_flight_planner(self):
        state = {
            "question": "Quel est le prix du vol Tunis-Montréal ?",
            "flight_search": {
                "origin_code": "TUN",
                "destination_code": "YUL",
                "departure_date": None,
                "return_date": None,
            },
            "trace": [],
        }
        result = workflow.create_booking_link(state)

        self.assertEqual("tunisair_booking", result["source_used"])
        self.assertIn("Tunis–Montréal", result["answer"])
        self.assertIn("date aller et la date retour", result["answer"])
        self.assertEqual(
            "https://www.tunisair.com/fr",
            result["citations"][0]["url"],
        )
        self.assertEqual("Planifiez votre prochain vol", result["citations"][0]["title"])

    def test_french_fare_question_returns_planner_link_without_retrieval(self):
        result = workflow.ask("Quel est le prix du vol Tunis-Montréal ?")

        self.assertEqual("tunisair_booking", result["source_used"])
        self.assertIn("Tunis–Montréal", result["answer"])
        self.assertEqual(
            "https://www.tunisair.com/fr",
            result["citations"][0]["url"],
        )
        self.assertTrue(any("BOOKING" in item for item in result["trace"]))

    def test_router_uses_function_calling_for_route_decision(self):
        model = Mock()
        router = Mock()
        router.invoke.return_value = RouteDecision(route="kb")
        model.with_structured_output.return_value = router

        with patch.object(workflow, "llm", return_value=model):
            result = workflow.route_question({"question": "How do I check flights?", "trace": []})

        model.with_structured_output.assert_called_once_with(
            RouteDecision, method="function_calling"
        )
        self.assertEqual("kb", result["source_used"])

    def test_evidence_grader_uses_function_calling(self):
        model = Mock()
        grader = Mock()
        grader.invoke.return_value = EvidenceGrade(grade="good")
        model.with_structured_output.return_value = grader
        state = {
            "question": "How do I check flights?",
            "kb_docs": [Document(page_content="Flight information", metadata={})],
            "trace": [],
        }

        with patch.object(workflow, "llm", return_value=model):
            result = workflow.grade_kb(state)

        model.with_structured_output.assert_called_once_with(
            EvidenceGrade, method="function_calling"
        )
        self.assertEqual("good", result["kb_grade"])


class TunisairSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manifest_path = Path(self.temp_dir.name) / "manifest.json"
        self.content_db_path = Path(self.temp_dir.name) / "tunisair_content.db"
        self.settings_patches = (
            patch.object(
                tunisair_sync.settings, "tunisair_sync_manifest_path", str(self.manifest_path)
            ),
            patch.object(
                tunisair_sync.settings, "tunisair_content_db_path", str(self.content_db_path)
            ),
        )
        for settings_patch in self.settings_patches:
            settings_patch.start()
            self.addCleanup(settings_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_sync_uses_manifest_ids_and_ignores_unchanged_pages(self):
        page = TunisairPage(
            url=ALLOWED_PAGE_URLS[0],
            title="Tunisair",
            text="Tunisair official content " * 80,
            fetched_at="2026-11-11T12:00:00+00:00",
        )
        with (
            patch.object(tunisair_sync, "TunisairCrawler") as crawler,
            patch.object(tunisair_sync, "add_documents") as add_documents,
            patch.object(tunisair_sync, "delete_documents") as delete_documents,
        ):
            crawler.return_value.fetch_allowed_pages.return_value = [page]
            first = tunisair_sync.sync_tunisair()
            self.assertEqual(1, first["indexed_pages"])
            self.assertTrue(add_documents.call_args.kwargs["ids"])

            page = TunisairPage(
                url=page.url,
                title=page.title,
                text=page.text,
                fetched_at="2026-11-12T12:00:00+00:00",
            )
            crawler.return_value.fetch_allowed_pages.return_value = [page]
            add_documents.reset_mock()
            second = tunisair_sync.sync_tunisair()

        self.assertEqual(1, second["unchanged_pages"])
        add_documents.assert_not_called()
        delete_documents.assert_not_called()
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertIn(page.url, manifest)
        with closing(sqlite3.connect(self.content_db_path)) as connection, connection:
            stored = connection.execute(
                "SELECT title, content_text, fetched_at FROM source_pages WHERE url = ?",
                (page.url,),
            ).fetchone()
        self.assertEqual(("Tunisair", page.text, page.fetched_at), stored)

    def test_blocked_fetch_does_not_change_vectors_or_manifest(self):
        with (
            patch.object(tunisair_sync, "TunisairCrawler") as crawler,
            patch.object(tunisair_sync, "add_documents") as add_documents,
            patch.object(tunisair_sync, "delete_documents") as delete_documents,
        ):
            crawler.return_value.fetch_allowed_pages.side_effect = TunisairAccessBlocked("HTTP 421")
            with self.assertRaises(TunisairAccessBlocked):
                tunisair_sync.sync_tunisair()

        add_documents.assert_not_called()
        delete_documents.assert_not_called()
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.content_db_path.exists())

    def test_extracted_text_is_archived_when_vector_sync_is_unavailable(self):
        page = TunisairPage(
            url=ALLOWED_PAGE_URLS[0],
            title="Tunisair",
            text="Extracted page text",
            fetched_at="2026-11-11T12:00:00+00:00",
        )
        with (
            patch.object(tunisair_sync, "TunisairCrawler") as crawler,
            patch.object(
                tunisair_sync,
                "add_documents",
                side_effect=RuntimeError("Ollama unavailable"),
            ),
        ):
            crawler.return_value.fetch_allowed_pages.return_value = [page]
            with self.assertRaisesRegex(RuntimeError, "Ollama unavailable"):
                tunisair_sync.sync_tunisair()

        self.assertTrue(self.content_db_path.exists())
        self.assertFalse(self.manifest_path.exists())
        with closing(sqlite3.connect(self.content_db_path)) as connection:
            row = connection.execute(
                "SELECT content_text FROM source_pages WHERE url = ?",
                (page.url,),
            ).fetchone()
        self.assertEqual((page.text,), row)


class PineconeSafetyTests(unittest.TestCase):
    def test_dimension_mismatch_does_not_delete_existing_index(self):
        class FakePinecone:
            def __init__(self):
                self.delete_index = Mock()

            def list_indexes(self):
                return [{"name": "test-index"}]

            def describe_index(self, _name):
                return type("IndexInfo", (), {"dimension": 384})()

        with (
            patch.object(vectorstore.settings, "pinecone_api_key", "test-key"),
            patch.object(vectorstore.settings, "pinecone_index_name", "test-index"),
            patch.object(vectorstore.settings, "embedding_model", "nomic-embed-text"),
            patch.object(vectorstore, "Pinecone", return_value=FakePinecone()) as pinecone,
        ):
            with self.assertRaisesRegex(RuntimeError, "existing index was not changed"):
                vectorstore.ensure_index()

        pinecone.return_value.delete_index.assert_not_called()

    def test_openai_embedding_provider_uses_configured_model_and_key(self):
        with (
            patch.object(vectorstore.settings, "embedding_provider", "openai"),
            patch.object(vectorstore.settings, "openai_embedding_model", "text-embedding-3-small"),
            patch.object(vectorstore.settings, "openai_api_key", "test-key"),
            patch.object(vectorstore, "_embeddings", None),
            patch.object(vectorstore, "OpenAIEmbeddings") as openai_embeddings,
        ):
            result = vectorstore.get_embeddings()
            dimension = vectorstore.get_embedding_dimension()

        openai_embeddings.assert_called_once_with(
            model="text-embedding-3-small",
            api_key="test-key",
        )
        self.assertIs(result, openai_embeddings.return_value)
        self.assertEqual(1536, dimension)

    def test_openai_embedding_provider_requires_api_key(self):
        with (
            patch.object(vectorstore.settings, "embedding_provider", "openai"),
            patch.object(vectorstore.settings, "openai_api_key", ""),
            patch.object(vectorstore, "_embeddings", None),
            patch.object(vectorstore, "OpenAIEmbeddings") as openai_embeddings,
        ):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is required"):
                vectorstore.get_embeddings()

        openai_embeddings.assert_not_called()

    def test_ollama_embedding_provider_remains_the_default(self):
        with (
            patch.object(vectorstore.settings, "embedding_provider", "ollama"),
            patch.object(vectorstore.settings, "embedding_model", "nomic-embed-text"),
            patch.object(vectorstore.settings, "ollama_base_url", "http://localhost:11434"),
            patch.object(vectorstore, "_embeddings", None),
            patch.object(vectorstore, "OllamaEmbeddings") as ollama_embeddings,
        ):
            result = vectorstore.get_embeddings()

        ollama_embeddings.assert_called_once_with(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )
        self.assertIs(result, ollama_embeddings.return_value)
        self.assertEqual(768, vectorstore.get_embedding_dimension())


if __name__ == "__main__":
    unittest.main()
