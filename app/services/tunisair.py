import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import get_settings

settings = get_settings()

USER_AGENT = "TunisairRAGAssistant/1.0"
ALLOWED_PAGE_URLS = (
    "https://www.tunisair.com/fr",
    "https://flights.tunisair.com/fr",
)
BOOKING_HOST = "book.tunisair.com"
BOOKING_PATH = "/plnext/tunisairDX/Override.action"
BOOKING_BASE_URL = f"https://{BOOKING_HOST}{BOOKING_PATH}"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class TunisairAccessBlocked(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new_url):
        return None


@dataclass(frozen=True)
class TunisairPage:
    url: str
    title: str
    text: str
    fetched_at: str


class _PageParser(HTMLParser):
    _ignored_tags = {"script", "style", "noscript", "svg", "nav", "header", "footer"}
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._title_depth = 0
        self.title: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, _attrs)
        if tag == "title":
            self._title_depth += 1
        if self._ignored_depth:
            if tag not in self._void_tags:
                self._ignored_depth += 1
        elif tag in self._ignored_tags:
            self._ignored_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._title_depth:
            self.title.append(text)
        if not self._ignored_depth:
            self.text.append(text)


class TunisairCrawler:
    """Fetches only the two explicitly allowed, fixed Tunisair landing pages."""

    def __init__(self):
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request_at = 0.0

    @staticmethod
    def _open(request: Request):
        opener = build_opener(_NoRedirectHandler())
        return opener.open(request, timeout=settings.tunisair_request_timeout_seconds)

    def _fetch(self, url: str) -> tuple[bytes, Message, str]:
        parsed = urlsplit(url)
        if url not in ALLOWED_PAGE_URLS:
            raise ValueError(f"Refusing to fetch a URL outside the Tunisair allowlist: {url}")
        if parsed.path != "/fr" or parsed.query or parsed.fragment:
            raise ValueError(f"Refusing to fetch a non-allowlisted Tunisair route: {url}")

        delay = max(0.0, settings.tunisair_crawl_delay_seconds)
        remaining = delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
            },
        )
        try:
            with self._open(request) as response:
                final_url = response.geturl()
                if final_url.rstrip("/") != url.rstrip("/"):
                    raise ValueError(f"Tunisair page redirected outside the allowlist: {final_url}")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"Tunisair page exceeds {MAX_RESPONSE_BYTES} bytes: {url}")
                headers = response.headers
        except HTTPError as exc:
            if exc.code in {401, 403, 421, 429}:
                raise TunisairAccessBlocked(
                    f"Tunisair denied automated access to {url} (HTTP {exc.code}); stopping."
                ) from exc
            raise
        finally:
            self._last_request_at = time.monotonic()
        return body, headers, final_url

    def _robots_for(self, url: str) -> RobotFileParser:
        host = urlsplit(url).netloc
        if host not in self._robots:
            robots_url = f"https://{host}/robots.txt"
            request = Request(robots_url, headers={"User-Agent": USER_AGENT})
            try:
                with self._open(request) as response:
                    body = response.read(64 * 1024)
            except HTTPError as exc:
                if 300 <= exc.code < 400:
                    raise RuntimeError(
                        f"Refusing to follow a redirect while checking {host} robots.txt."
                    ) from exc
                if exc.code == 404:
                    body = b""
                else:
                    raise
            except URLError as exc:
                raise RuntimeError(f"Could not check {host} robots.txt: {exc}") from exc
            parser = RobotFileParser(robots_url)
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            self._robots[host] = parser
        return self._robots[host]

    @staticmethod
    def _parse(url: str, body: bytes, headers: Message) -> TunisairPage:
        charset = headers.get_content_charset() or "utf-8"
        html = body.decode(charset, errors="replace")
        parser = _PageParser()
        parser.feed(html)
        title = " ".join(parser.title).strip() or PurePosixPath(urlsplit(url).path).name
        text = "\n".join(parser.text).strip()
        lowered = f"{title}\n{text}".casefold()
        if any(
            marker in lowered
            for marker in (
                "validation needed to continue",
                "please type the text you see in the image",
                "captcha.gif",
                "number of attempts left",
            )
        ):
            raise TunisairAccessBlocked(
                f"Tunisair returned a validation challenge for {url}; stopping without retrying."
            )
        if not text:
            raise ValueError(f"Tunisair page returned no readable content: {url}")
        return TunisairPage(
            url=url,
            title=title,
            text=text,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    def fetch_allowed_pages(self) -> list[TunisairPage]:
        pages = []
        for url in ALLOWED_PAGE_URLS:
            if not self._robots_for(url).can_fetch(USER_AGENT, url):
                raise TunisairAccessBlocked(
                    f"robots.txt disallows crawling {url}; no pages were indexed."
                )
            body, headers, final_url = self._fetch(url)
            pages.append(self._parse(final_url, body, headers))
        return pages


def build_booking_url(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: str,
) -> str:
    """Build the user-facing round-trip link; never requests the robots-disallowed booking host."""
    origin = origin_code.strip().upper()
    destination = destination_code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", origin) or not re.fullmatch(r"[A-Z]{3}", destination):
        raise ValueError("Use three-letter Tunisair location codes for origin and destination.")
    if origin == destination:
        raise ValueError("Origin and destination must be different.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", departure_date) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", return_date
    ):
        raise ValueError("Use dates in YYYY-MM-DD format.")
    try:
        outbound = date.fromisoformat(departure_date)
        inbound = date.fromisoformat(return_date)
    except ValueError as exc:
        raise ValueError("Use dates in YYYY-MM-DD format.") from exc
    if inbound < outbound:
        raise ValueError("Return date cannot be before departure date.")

    params = [
        ("LANGUAGE", "FR"),
        ("EMBEDDED_TRANSACTION", "TimeTable"),
        ("SITE", "BASXBNEW"),
        ("TRIP_TYPE", "R"),
        ("B_LOCATION", origin),
        ("E_LOCATION", destination),
        ("B_DATE", outbound.strftime("%Y%m%d0000")),
        ("E_DATE", inbound.strftime("%Y%m%d0000")),
        ("TRIP_FLOW", "YES"),
        ("EXTERNAL_ID", "BOOKING"),
        ("SO_SITE_OFFICE_ID", "TUNTU08BB"),
    ]
    return f"{BOOKING_BASE_URL}?{urlencode(params)}#/TIMR"
