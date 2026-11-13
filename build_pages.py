import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.services.airports import AIRPORTS

BASE_DIR = Path(__file__).resolve().parent


def validate_api_base_url(value: str) -> str:
    api_base_url = value.strip().rstrip("/")
    if not api_base_url:
        return ""

    parsed = urlsplit(api_base_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "PAGES_API_BASE_URL must be an HTTPS base URL without credentials, "
            "query parameters, or a fragment"
        )
    return api_base_url


def build_site(output_dir: Path, api_base_url: str = "") -> None:
    environment = Environment(
        loader=FileSystemLoader(BASE_DIR / "templates"),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
    )
    html = environment.get_template("index.html").render(
        app_name="Your Flight Support Bot System",
        airports=AIRPORTS,
        api_base_url=validate_api_base_url(api_base_url),
        static_pages=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    shutil.copytree(BASE_DIR / "static", output_dir / "static", dirs_exist_ok=True)


if __name__ == "__main__":
    build_site(
        BASE_DIR / "_site",
        os.environ.get("PAGES_API_BASE_URL", ""),
    )
