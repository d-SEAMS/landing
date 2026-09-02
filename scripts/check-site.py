"""Validate the static landing page without network access."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PageParser(HTMLParser):
    """Collect the page structure needed by the site contract."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.links: list[tuple[str, str, str]] = []
        self.text: list[str] = []
        self.title: list[str] = []
        self._in_title = False
        self.html_lang: str | None = None
        self.h1_count = 0
        self.main_ids: list[str | None] = []
        self.nav_labels: list[str | None] = []
        self.skip_targets: list[str] = []
        self.images_without_alt = 0
        self.unsafe_blank_targets: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "html":
            self.html_lang = values.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "main":
            self.main_ids.append(values.get("id"))
        elif tag == "nav":
            self.nav_labels.append(values.get("aria-label"))
        elif tag == "img" and "alt" not in values:
            self.images_without_alt += 1

        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.add(element_id)
            self.ids.add(element_id)

        classes = set((values.get("class") or "").split())
        if tag == "a" and "skip-link" in classes and values.get("href"):
            self.skip_targets.append(values["href"] or "")

        if tag == "a" and values.get("target") == "_blank":
            rel = set((values.get("rel") or "").split())
            if not {"noopener", "noreferrer"}.issubset(rel):
                self.unsafe_blank_targets.append(values.get("href") or "<missing href>")

        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                self.links.append((tag, attribute, value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text.append(value)
            if self._in_title:
                self.title.append(value)


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def resolve_target(site: Path, source: Path, raw_url: str) -> tuple[Path, str]:
    parsed = urlsplit(raw_url)
    relative = unquote(parsed.path)
    target = site / relative.removeprefix("/") if relative.startswith("/") else source.parent / relative

    if not relative:
        target = source
    elif relative.endswith("/") or target.is_dir():
        target /= "index.html"

    return target.resolve(), unquote(parsed.fragment)


def check_page(site: Path, source: Path, page: PageParser) -> list[str]:
    relative_source = source.relative_to(site)
    failures: list[str] = []
    if page.html_lang != "en":
        failures.append(f"{relative_source}: html lang must be en")
    if not page.title:
        failures.append(f"{relative_source}: title must not be empty")
    if page.h1_count != 1:
        failures.append(f"{relative_source}: expected one h1, found {page.h1_count}")
    if page.main_ids != ["main-content"]:
        failures.append(f"{relative_source}: main must have id=main-content")
    if not page.nav_labels or any(not label for label in page.nav_labels):
        failures.append(f"{relative_source}: every nav needs an aria-label")
    if "#main-content" not in page.skip_targets:
        failures.append(f"{relative_source}: missing skip link to #main-content")
    if page.images_without_alt:
        failures.append(
            f"{relative_source}: {page.images_without_alt} image(s) lack alt attributes"
        )
    if page.duplicate_ids:
        failures.append(
            f"{relative_source}: duplicate ids: {', '.join(sorted(page.duplicate_ids))}"
        )
    for href in page.unsafe_blank_targets:
        failures.append(f"{relative_source}: target=_blank lacks safe rel: {href}")
    return failures


def check_links(
    site: Path, parsed_pages: dict[Path, PageParser]
) -> list[str]:
    failures: list[str] = []
    for source, page in parsed_pages.items():
        for tag, attribute, raw_url in page.links:
            parsed = urlsplit(raw_url)
            if parsed.scheme or parsed.netloc or raw_url.startswith("//"):
                continue
            target, fragment = resolve_target(site, source, raw_url)
            try:
                target.relative_to(site)
            except ValueError:
                failures.append(
                    f"{source.relative_to(site)}: {tag} {attribute} escapes site: {raw_url}"
                )
                continue
            if not target.exists():
                failures.append(
                    f"{source.relative_to(site)}: missing {tag} {attribute}: {raw_url}"
                )
                continue
            if fragment and target.suffix == ".html":
                target_page = parsed_pages.get(target)
                if target_page is None or fragment not in target_page.ids:
                    failures.append(
                        f"{source.relative_to(site)}: missing fragment: {raw_url}"
                    )
    return failures


def href_values(page: PageParser) -> list[str]:
    return [url for _tag, attribute, url in page.links if attribute == "href"]


def has_href(hrefs: list[str], needed: str) -> bool:
    target = needed.rstrip("/")
    for url in hrefs:
        value = url.rstrip("/")
        if value == target or value.startswith(f"{target}/"):
            return True
    return False


def check_contract(site: Path, index: PageParser) -> list[str]:
    text = " ".join(index.text)
    required = (
        "pip install pydseamslib",
        "import pydseams",
        'require("dseams")',
        "seams-core",
        "yodaStruct",
        "dseams-plumed",
        "DSEAMS_CAGES",
        "linkcell",
        "readcon-core",
        "dseams2_repro",
        "2.7.0",
        "0.1.0",
        "density-z",
        "chill-plus",
        "read, chill, chill-plus, cages, rdf, cn, hbonds, pairs, density-z, and domains",
        "1.x recording",
        "2.x recording",
    )
    forbidden = (
        "pip install pydseams ",
        "Needs its own recording",
        "Until that exists",
        "Use the runnable",
        "Software 2.2",
        "three packages",
        "Three packages",
        "libyodaLib",
        "fingerprint",
        "topology keys",
        "seams ions",
    )
    failures = [f"index.html: missing public contract: {value}" for value in required if value not in text]
    failures.extend(
        f"index.html: stale or invalid copy: {value}"
        for value in forbidden
        if value in f"{text} "
    )

    hrefs = href_values(index)
    required_hrefs = (
        "https://github.com/d-SEAMS/seams-core",
        "https://github.com/d-SEAMS/PydSEAMSlib",
        "https://github.com/d-SEAMS/yodaStruct",
        "https://github.com/d-SEAMS/linkcell",
        "https://github.com/d-SEAMS/wiki",
        "https://github.com/d-SEAMS/landing",
        "https://github.com/HaoZeke/dseams-plumed",
        "https://github.com/HaoZeke/dseams2_repro",
        "https://github.com/HaoZeke/readcon-core",
        "https://docs.dseams.info",
        "https://wiki.dseams.info",
        "https://d-seams.github.io/PydSEAMSlib/",
        "https://d-seams.github.io/yodaStruct/",
        "https://cdn.jsdelivr.net/npm/asciinema-player@3.17.0/dist/bundle/asciinema-player.css",
        "casts/dseams-2x.cast",
    )
    failures.extend(
        f"index.html: missing required href: {url}"
        for url in required_hrefs
        if not has_href(hrefs, url)
    )

    srcs = [url for _tag, attribute, url in index.links if attribute == "src"]
    required_srcs = (
        "https://cdn.jsdelivr.net/npm/asciinema-player@3.17.0/dist/bundle/asciinema-player.min.js",
        "https://asciinema.org/a/4KAQce0vldH90WcANWBDACSwD.js",
    )
    failures.extend(
        f"index.html: missing required src: {url}"
        for url in required_srcs
        if url not in srcs
    )

    cast = site / "casts" / "dseams-2x.cast"
    if not cast.is_file():
        failures.append("casts/dseams-2x.cast: missing 2.x recording")
    else:
        cast_text = cast.read_text(encoding="utf-8")
        for value in (
            "seams",
            "pip install pydseamslib",
            "import pydseams",
        ):
            if value not in cast_text:
                failures.append(f"casts/dseams-2x.cast: missing public contract: {value}")
        if (
            'require("dseams")' not in cast_text
            and r'require(\"dseams\")' not in cast_text
        ):
            failures.append(
                'casts/dseams-2x.cast: missing public contract: require("dseams")'
            )

    css = site / "css" / "site.css"
    if not css.is_file():
        failures.append("css/site.css: missing stylesheet")
    elif ":focus-visible" not in css.read_text(encoding="utf-8"):
        failures.append("css/site.css: missing visible keyboard focus style")
    return failures


def check_site(site: Path) -> list[str]:
    site = site.resolve()
    pages = sorted(path.resolve() for path in site.rglob("*.html"))
    if not pages:
        return [f"no HTML pages found under {site}"]

    parsed_pages = {page: parse_page(page) for page in pages}
    index_path = (site / "index.html").resolve()
    if index_path not in parsed_pages:
        return ["index.html: missing landing page"]

    failures: list[str] = []
    for source, page in parsed_pages.items():
        failures.extend(check_page(site, source, page))
    failures.extend(check_links(site, parsed_pages))
    failures.extend(check_contract(site, parsed_pages[index_path]))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    failures = check_site(args.site)
    if failures:
        print("\n".join(failures))
        return 1
    print("static site contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
