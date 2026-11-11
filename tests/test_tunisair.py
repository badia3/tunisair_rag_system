import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request
from unittest.mock import Mock, patch

from langchain_core.documents import Document

from app.rag import vectorstore
from app.rag import workflow
from app.rag.state import EvidenceGrade, RouteDecision
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
    def test_only_the_two_explicit_landing_pages_are_fetched(self):
        crawler = TunisairCrawler()
        robots = type("AllowAll", (), {"can_fetch": lambda *_: True})()
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        response = (b"<html><title>Tunisair</title><body>Official Tunisair page</body></html>", headers)

        with (
            patch.object(crawler, "_robots_for", return_value=robots),
            patch.object(crawler, "_fetch", return_value=(*response, ALLOWED_PAGE_URLS[0])) as fetch,
        ):
            # Return the URL matching each fixed allowlisted page in order.
            fetch.side_effect = [
                (*response, ALLOWED_PAGE_URLS[0]),
                (*response, ALLOWED_PAGE_URLS[1]),
            ]
            pages = crawler.fetch_allowed_pages()

        self.assertEqual(list(ALLOWED_PAGE_URLS), [page.url for page in pages])
        self.assertEqual(2, fetch.call_count)
        self.assertEqual(list(ALLOWED_PAGE_URLS), [call.args[0] for call in fetch.call_args_list])

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


class WorkflowStructuredOutputTests(unittest.TestCase):
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
        self.settings_patch = patch.object(
            tunisair_sync.settings, "tunisair_sync_manifest_path", str(self.manifest_path)
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
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


if __name__ == "__main__":
    unittest.main()
