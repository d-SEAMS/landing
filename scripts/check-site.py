"""Validate the static landing page without network access."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
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
        self.meta: list[dict[str, str]] = []
        self.link_tags: list[dict[str, str]] = []
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
        if tag == "meta":
            self.meta.append({key: value or "" for key, value in attrs})
        elif tag == "link":
            self.link_tags.append({key: value or "" for key, value in attrs})

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


FORTHCOMING_NOTICE = re.compile(
    r'<p\s+id=(["\'])forthcoming-paper-status\1\s*>\s*Coming soon\.\s*</p>',
    flags=re.IGNORECASE,
)


def check_forthcoming_notice(source: str) -> list[str]:
    """Permit the paper notice while rejecting release-status placeholders."""

    notices = list(FORTHCOMING_NOTICE.finditer(source))
    failures: list[str] = []
    if len(notices) != 1:
        failures.append(
            "index.html: expected one exact forthcoming paper notice"
        )
    without_notice = FORTHCOMING_NOTICE.sub("", source)
    if re.search(r"\bcoming\s+soon\b", without_notice, flags=re.IGNORECASE):
        failures.append(
            "index.html: reader-facing plumbing: coming soon"
        )
    return failures


EXPECTED_BINDING_TABS = (
    ("tab-python", "panel-python"),
    ("tab-cli", "panel-cli"),
    ("tab-rust", "panel-rust"),
    ("tab-r", "panel-r"),
    ("tab-lua", "panel-lua"),
    ("tab-fortran", "panel-fortran"),
    ("tab-plumed", "panel-plumed"),
)


class _SectionStructureParser(HTMLParser):
    """Extract tabs, tabpanels, #linkcell section, and nav/footer groupings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.tabs: list[dict[str, str]] = []
        self._active_tab: dict[str, str] | None = None
        self.tabpanels: list[str] = []
        self.section_order: list[str] = []
        self.linkcell_found = False
        self.linkcell_in_install = False
        self.linkcell_in_tabpanel = False
        self.linkcell_text: list[str] = []
        self.linkcell_hrefs: list[str] = []
        self.primary_nav_hrefs: list[str] = []
        self.docs_menu_items: list[tuple[str, str]] = []
        self._active_docs_label: list[str] | None = None
        self.books_groups: list[dict[str, object]] = []
        self._active_books_group: dict[str, object] | None = None
        self._active_books_label: list[str] | None = None
        self.foot_groups: list[dict[str, object]] = []
        self._active_foot_group: dict[str, object] | None = None
        self._active_foot_label: list[str] | None = None

    def _in_class(self, class_name: str) -> bool:
        return any(
            class_name in (attrs.get("class") or "").split()
            for _tag, attrs in self.stack
        )

    def _in_id(self, element_id: str) -> bool:
        return any(attrs.get("id") == element_id for _tag, attrs in self.stack)

    def _in_role(self, role: str) -> bool:
        return any(attrs.get("role") == role for _tag, attrs in self.stack)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {k: (v or "") for k, v in attrs}
        classes = set(values.get("class", "").split())
        element_id = values.get("id", "")
        role = values.get("role", "")

        if tag == "section" and element_id:
            self.section_order.append(element_id)
            if element_id == "linkcell":
                self.linkcell_found = True
                if self._in_id("install"):
                    self.linkcell_in_install = True
                if self._in_role("tabpanel"):
                    self.linkcell_in_tabpanel = True

        if role == "tab" and self._in_role("tablist"):
            self._active_tab = {
                "id": element_id,
                "controls": values.get("aria-controls", ""),
                "label": "",
            }

        if role == "tabpanel" and element_id:
            self.tabpanels.append(element_id)

        if tag == "a" and values.get("href"):
            href = values["href"]
            if self._in_id("linkcell") or element_id == "linkcell":
                self.linkcell_hrefs.append(href)
            if any(
                t == "nav" and a.get("aria-label") == "Primary"
                for t, a in self.stack
            ):
                self.primary_nav_hrefs.append(href)
            if self._in_class("docs-menu"):
                self.docs_menu_items.append(("link", href))
            if self._active_books_group is not None:
                self._active_books_group["hrefs"].append(href)  # type: ignore[union-attr]
            if self._active_foot_group is not None:
                self._active_foot_group["hrefs"].append(href)  # type: ignore[union-attr]

        if "docs-menu-label" in classes and self._in_class("docs-menu"):
            self._active_docs_label = []

        if "books-group" in classes and self._in_class("books-strip"):
            self._active_books_group = {"label": "", "hrefs": []}
        if "books-group-label" in classes and self._active_books_group is not None:
            self._active_books_label = []

        if "foot-group" in classes and self._in_class("foot-links"):
            self._active_foot_group = {"label": "", "hrefs": []}
        if "foot-group-label" in classes and self._active_foot_group is not None:
            self._active_foot_label = []

        self.stack.append((tag, values))

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        popped_tag, popped_attrs = self.stack.pop()
        classes = set(popped_attrs.get("class", "").split())
        if popped_attrs.get("role") == "tab" and self._active_tab is not None:
            self._active_tab["label"] = self._active_tab["label"].strip()
            self.tabs.append(self._active_tab)
            self._active_tab = None
        if "docs-menu-label" in classes and self._active_docs_label is not None:
            label = " ".join(self._active_docs_label).strip()
            self.docs_menu_items.append(("label", label))
            self._active_docs_label = None
        if "books-group-label" in classes and self._active_books_label is not None:
            if self._active_books_group is not None:
                self._active_books_group["label"] = " ".join(
                    self._active_books_label
                ).strip()
            self._active_books_label = None
        if "books-group" in classes and self._active_books_group is not None:
            self.books_groups.append(self._active_books_group)
            self._active_books_group = None
        if "foot-group-label" in classes and self._active_foot_label is not None:
            if self._active_foot_group is not None:
                self._active_foot_group["label"] = " ".join(
                    self._active_foot_label
                ).strip()
            self._active_foot_label = None
        if "foot-group" in classes and self._active_foot_group is not None:
            self.foot_groups.append(self._active_foot_group)
            self._active_foot_group = None

    def handle_data(self, data: str) -> None:
        if self._active_tab is not None:
            self._active_tab["label"] += data
        if self._in_id("linkcell"):
            stripped = data.strip()
            if stripped:
                self.linkcell_text.append(stripped)
        if self._active_docs_label is not None and data.strip():
            self._active_docs_label.append(data.strip())
        if self._active_books_label is not None and data.strip():
            self._active_books_label.append(data.strip())
        if self._active_foot_label is not None and data.strip():
            self._active_foot_label.append(data.strip())


def _parse_structure(source: str) -> _SectionStructureParser:
    parser = _SectionStructureParser()
    parser.feed(source)
    parser.close()
    return parser


def check_bindings_tabs(source: str) -> list[str]:
    """Require the seven binding tabs and forbid linkcell in the tab set."""

    parsed = _parse_structure(source)
    failures: list[str] = []
    tab_pairs = [(tab["id"], tab["controls"]) for tab in parsed.tabs]
    for tab in parsed.tabs:
        if "linkcell" in tab["id"].lower() or "linkcell" in tab["controls"].lower() or "linkcell" in tab["label"].lower():
            failures.append("index.html: linkcell must not appear in bindings tabs")
            break
    if "panel-linkcell" in parsed.tabpanels:
        failures.append("index.html: panel-linkcell must not exist as a binding tabpanel")
    if tab_pairs != list(EXPECTED_BINDING_TABS):
        failures.append(
            f"index.html: unexpected bindings tabs: {tab_pairs}"
        )
    for _tab_id, panel_id in EXPECTED_BINDING_TABS:
        if panel_id not in parsed.tabpanels:
            failures.append(f"index.html: missing binding tabpanel: {panel_id}")
    return failures


def check_linkcell_section(source: str) -> list[str]:
    """Require the standalone linkcell section below the bindings."""

    parsed = _parse_structure(source)
    failures: list[str] = []
    if not parsed.linkcell_found:
        return ["index.html: missing standalone #linkcell section"]
    if parsed.linkcell_in_install or parsed.linkcell_in_tabpanel:
        failures.append("index.html: #linkcell section must be outside #install bindings")
    if "install" in parsed.section_order and "linkcell" in parsed.section_order:
        if parsed.section_order.index("linkcell") < parsed.section_order.index("install"):
            failures.append("index.html: #linkcell section must appear below #install")
    section_text = " ".join(parsed.linkcell_text)
    section_lower = section_text.lower()
    for needle in (
        "pip install linkcell numpy",
        "cargo add linkcell",
        "linkcell.knearest",
        "pairs_within",
        "NeighborList",
        "lc_vesin_neighbors",
        "from linkcell import NeighborList",
    ):
        if needle not in section_text:
            failures.append(f"index.html: #linkcell section missing copy: {needle}")
    for needle in (
        "orthogonal",
        "triclinic",
        "stands alone",
        "neighbour search",
        "vesin",
    ):
        if needle not in section_lower:
            failures.append(f"index.html: #linkcell section missing copy: {needle}")
    if not has_href(parsed.linkcell_hrefs, "https://linkcell.dseams.info"):
        failures.append("index.html: #linkcell section missing link to https://linkcell.dseams.info/")
    if not has_href(parsed.linkcell_hrefs, "https://linkcell.dseams.info/explanation/mic-and-cells"):
        failures.append(
            "index.html: #linkcell section missing link to https://linkcell.dseams.info/explanation/mic-and-cells/"
        )
    if not has_href(parsed.linkcell_hrefs, "https://github.com/Luthaf/vesin"):
        failures.append("index.html: #linkcell section missing link to https://github.com/Luthaf/vesin")
    return failures


def check_library_grouping(source: str) -> list[str]:
    """Require linkcell to be grouped separately under Libraries across navs."""

    parsed = _parse_structure(source)
    failures: list[str] = []
    if "#linkcell" not in parsed.primary_nav_hrefs:
        failures.append("index.html: primary nav missing #linkcell link")

    current_label = ""
    docs_linkcell_labels: list[str] = []
    for kind, value in parsed.docs_menu_items:
        if kind == "label":
            current_label = value
        elif kind == "link" and value.rstrip("/") == "https://linkcell.dseams.info":
            docs_linkcell_labels.append(current_label)
    if docs_linkcell_labels != ["Libraries"]:
        failures.append(
            "index.html: Docs menu must group linkcell under Libraries label"
        )

    books_lib_groups = [
        group for group in parsed.books_groups
        if has_href(group["hrefs"], "https://linkcell.dseams.info")  # type: ignore[arg-type]
    ]
    if (
        len(books_lib_groups) != 1
        or books_lib_groups[0]["label"] != "Libraries"
        or len(books_lib_groups[0]["hrefs"]) != 1  # type: ignore[arg-type]
    ):
        failures.append(
            "index.html: doc-site list must group linkcell separately under Libraries"
        )

    foot_lib_groups = [
        group for group in parsed.foot_groups
        if has_href(group["hrefs"], "https://linkcell.dseams.info")  # type: ignore[arg-type]
    ]
    if (
        len(foot_lib_groups) != 1
        or foot_lib_groups[0]["label"] != "Libraries"
        or len(foot_lib_groups[0]["hrefs"]) != 1  # type: ignore[arg-type]
    ):
        failures.append(
            "index.html: footer must group linkcell separately under Libraries"
        )
    return failures


INTERNAL_TEXT = (
    (r"\belja\b", "cluster host name"),
    (r"\bjobs?\s*#?\d{3,}", "job id"),
    (r"\bbase\b[^.\n]{0,60}\bvs\b[^.\n]{0,60}\btip\b", "revision comparison"),
    (r"\bpaper_manifest\b", "manifest file name"),
    (r"results/reference", "internal results path"),
    (r"(?<![\w./-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])", "commit hash or job number"),
    (r"\bexclusive\b", "scheduler wording"),
    (r"\bmanifest:\b", "manifest label"),
)


def check_internal_text(site: Path) -> list[str]:
    failures: list[str] = []
    for name in ("index.html", "README.md"):
        p = site / name
        if not p.is_file():
            continue
        for number, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in INTERNAL_TEXT:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    failures.append(
                        f"{name}:{number}: internal text ({label}): {match.group(0)}"
                    )
                    break
    return failures


def check_contract(site: Path, index: PageParser) -> list[str]:
    text = " ".join(index.text)
    required = (
        "pip install pydseamslib",
        "cargo add dseams",
        "pip install linkcell",
        "cargo add linkcell",
        "CHILL+",
        "clathrate",
        "pixi run build",
        "remotes::install_github",
        "meson setup bbdir --wrap-mode=nofallback",
        "dseams-fortran",
        "dseams-plumed",
    )
    reader_forbidden = (
        "live index",
        "checked against",
        "conda-forge yet",
        "not on conda-forge",
        "install.json",
        "check-registries",
        "published</td>",
        ">published<",
        ">source<",
        "Status</th>",
    )
    forbidden = (
        "Elja",
        "job 1785712",
        "asciinema",
        "repro/reference",
        "libyodaLib",
        "2.7.0",
        "Antics",
        "fonts.googleapis",
        "gstatic.com",
    )
    html_raw = (site / "index.html").read_text(encoding="utf-8")
    failures = [f"index.html: missing public contract: {value}" for value in required if value not in text]
    failures.extend(
        f"index.html: stale or invalid copy: {value}"
        for value in forbidden
        if value in f"{text} "
    )
    failures.extend(
        f"index.html: reader-facing plumbing: {value}"
        for value in reader_forbidden
        if value in html_raw
    )
    failures.extend(check_forthcoming_notice(html_raw))
    failures.extend(check_bindings_tabs(html_raw))
    failures.extend(check_linkcell_section(html_raw))
    failures.extend(check_library_grouping(html_raw))
    for needle in ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "cdn.jsdelivr.net/npm/@fontsource"):
        if needle in html_raw:
            failures.append(f"index.html: external font or player CDN: {needle}")
    if 'loading="lazy"' in html_raw:
        failures.append("index.html: do not lazy-load images; all figures must load eagerly")

    hrefs = href_values(index)
    books = (
        "https://docs.dseams.info",
        "https://python.dseams.info",
        "https://rust.dseams.info",
        "https://julia.dseams.info",
        "https://fortran.dseams.info",
        "https://lua.dseams.info",
        "https://r.dseams.info",
        "https://plumed.dseams.info",
        "https://linkcell.dseams.info",
    )
    failures.extend(
        f"index.html: missing required href: {url}"
        for url in books
        if not has_href(hrefs, url)
    )

    if not has_href(hrefs, "https://github.com/d-SEAMS"):
        failures.append("index.html: missing GitHub org link")

    logo = site / "images" / "logo" / "dSeamsLogo.png"
    if not logo.is_file():
        failures.append("images/logo/dSeamsLogo.png: missing logo asset")
    elif "images/logo/dSeamsLogo.png" not in [u for _t, a, u in index.links if a == "src"]:
        failures.append("index.html: logo must appear in img src")

    manifest = site / "install.json"
    if not manifest.is_file():
        failures.append("install.json: missing install manifest")
    else:
        entries = json.loads(manifest.read_text(encoding="utf-8")).get("packages", [])
        for entry in entries:
            page_cmd = entry.get("page_command", entry.get("command", ""))
            if page_cmd:
                snippet = page_cmd if len(page_cmd) < 48 else page_cmd.split()[0]
                if page_cmd not in html_raw and snippet not in html_raw:
                    failures.append(f"install.json: page command missing on page: {page_cmd}")
            book = (entry.get("book") or "").rstrip("/")
            if book and not has_href(hrefs, book):
                failures.append(f"install.json: missing book href: {book}")
        blocks = re.findall(
            r'<script\s+type="application/ld\+json"\s*>(.*?)</script>',
            html_raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if len(blocks) == 1:
            graph = json.loads(blocks[0]).get("@graph", [])
            failures.extend(check_manifest_versions(graph, entries))

    for fig in (
        "images/dSEAMS/image7.png",
        "images/science/gallery-cages-sII.png",
        "images/science/gallery-rings.png",
        "images/science/gallery-interface.png",
        "images/science/gallery-interface-raw.png",
        "images/science/sii.png",
    ):
        if not (site / fig).is_file():
            failures.append(f"{fig}: missing science still")

    js_file = site / "js" / "site.js"
    if not js_file.is_file():
        failures.append("js/site.js: missing interactive script")
    elif js_file.stat().st_size >= 30_720:
        failures.append("js/site.js: exceeds 30 KB budget")

    css = site / "css" / "site.css"
    if not css.is_file():
        failures.append("css/site.css: missing stylesheet")
    else:
        css_text = css.read_text(encoding="utf-8")
        if ":focus-visible" not in css_text:
            failures.append("css/site.css: missing visible keyboard focus style")
        for bad in (".lattice", "Source Serif", "Source Sans", "fonts.googleapis"):
            if bad in css_text:
                failures.append(f"css/site.css: generic template marker: {bad}")
    return failures


def check_manifest_versions(graph: list[dict], entries: list[dict]) -> list[str]:
    """Require index.html JSON-LD softwareVersion to match install.json engine."""

    failures: list[str] = []
    engine = next(
        (entry for entry in entries if entry.get("id") == "engine"),
        None,
    )
    software = next(
        (
            node
            for node in graph
            if isinstance(node, dict)
            and node.get("@id") == "https://dseams.info/#software"
        ),
        None,
    )
    if engine is None:
        failures.append("install.json: missing engine entry")
    elif software is not None:
        expected = engine.get("version")
        actual = software.get("softwareVersion")
        if actual != expected:
            failures.append(
                f"index.html: softwareVersion {actual!r} != install.json engine {expected!r}"
            )
    return failures


def check_jsonld_graph(graph: list[dict]) -> list[str]:
    """Validate d-SEAMS, linkcell, and citation nodes in JSON-LD."""

    failures: list[str] = []
    types = {node.get("@type") for node in graph if isinstance(node, dict)}
    required_types = {"SoftwareApplication", "SoftwareSourceCode", "ScholarlyArticle"}
    if not required_types.issubset(types):
        failures.append("index.html: incomplete JSON-LD graph")

    software = next(
        (
            node
            for node in graph
            if isinstance(node, dict)
            and node.get("@id") == "https://dseams.info/#software"
        ),
        None,
    )
    if software is None or "https://crates.io/crates/linkcell" in software.get("sameAs", []):
        failures.append(
            "index.html: d-SEAMS SoftwareApplication must not list linkcell crate in sameAs"
        )

    linkcell_node = next(
        (
            node
            for node in graph
            if isinstance(node, dict)
            and node.get("@id") == "https://github.com/d-SEAMS/linkcell"
        ),
        None,
    )
    if (
        linkcell_node is None
        or linkcell_node.get("@type") != "SoftwareSourceCode"
        or linkcell_node.get("name") != "linkcell"
        or linkcell_node.get("url") != "https://linkcell.dseams.info/"
        or linkcell_node.get("codeRepository") != "https://github.com/d-SEAMS/linkcell"
        or "targetProduct" in linkcell_node
        or "https://crates.io/crates/linkcell" not in linkcell_node.get("sameAs", [])
    ):
        failures.append("index.html: invalid standalone linkcell JSON-LD node")

    forthcoming = next(
        (
            node
            for node in graph
            if isinstance(node, dict)
            and node.get("@id") == "https://dseams.info/#dseams-2-paper"
        ),
        None,
    )
    expected_authors = [
        ("Rohit Goswami", "https://orcid.org/0000-0002-2393-8056"),
        ("Amrita Goswami", "https://orcid.org/0000-0001-8706-2383"),
        ("Ruhila Goswami", "https://orcid.org/0000-0002-5443-9356"),
        ("Jayant K. Singh", "https://orcid.org/0000-0001-8056-2115"),
    ]
    if (
        forthcoming is None
        or forthcoming.get("@type") != "ScholarlyArticle"
        or forthcoming.get("name")
        != "d-SEAMS 2.0: Incremental ring and cage algorithms for ice structure analysis"
        or forthcoming.get("creativeWorkStatus") != "Forthcoming"
        or [
            (author.get("name"), author.get("@id"))
            for author in forthcoming.get("author", [])
        ]
        != expected_authors
    ):
        failures.append("index.html: invalid d-SEAMS 2.0 JSON-LD article")
    elif any(
        key in forthcoming
        for key in ("datePublished", "doi", "isPartOf", "sameAs")
    ):
        failures.append(
            "index.html: forthcoming article must not claim publication metadata"
        )
    return failures


def check_seo(site: Path, index: PageParser) -> list[str]:
    failures: list[str] = []
    descriptions = [
        item.get("content", "")
        for item in index.meta
        if item.get("name", "").lower() == "description"
    ]
    if len(descriptions) != 1 or not descriptions[0]:
        failures.append("index.html: expected one non-empty meta description")

    canonicals = [
        item.get("href", "")
        for item in index.link_tags
        if "canonical" in item.get("rel", "").lower().split()
    ]
    if canonicals != ["https://dseams.info/"]:
        failures.append("index.html: canonical must be https://dseams.info/")

    required_properties = {
        "og:site_name": "d-SEAMS",
        "og:title": "",
        "og:description": "",
        "og:type": "website",
        "og:url": "https://dseams.info/",
        "og:image": "https://dseams.info/images/og-card.png",
        "og:image:alt": "",
    }
    for prop, expected in required_properties.items():
        values = [
            item.get("content", "")
            for item in index.meta
            if item.get("property", "").lower() == prop
        ]
        if len(values) != 1 or not values[0] or (expected and values[0] != expected):
            failures.append(f"index.html: invalid {prop}")

    required_names = {
        "twitter:card": "summary_large_image",
        "twitter:title": "",
        "twitter:description": "",
        "twitter:image": "https://dseams.info/images/og-card.png",
        "twitter:image:alt": "",
    }
    for name, expected in required_names.items():
        values = [
            item.get("content", "")
            for item in index.meta
            if item.get("name", "").lower() == name
        ]
        if len(values) != 1 or not values[0] or (expected and values[0] != expected):
            failures.append(f"index.html: invalid {name}")

    image = site / "images" / "og-card.png"
    if not image.is_file():
        failures.append("images/og-card.png: missing social image")

    robots = site / "robots.txt"
    if not robots.is_file():
        failures.append("robots.txt: missing")
    else:
        text = robots.read_text(encoding="utf-8")
        if "User-agent: *" not in text or "Allow: /" not in text:
            failures.append("robots.txt: crawlers must be allowed")
        if "Sitemap: https://dseams.info/sitemap.xml" not in text:
            failures.append("robots.txt: missing sitemap URL")

    sitemap = site / "sitemap.xml"
    if not sitemap.is_file():
        failures.append("sitemap.xml: missing")
    else:
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = [
            item.text or ""
            for item in ET.parse(sitemap).findall(".//sm:loc", namespace)
        ]
        if locations != ["https://dseams.info/"]:
            failures.append("sitemap.xml: expected only https://dseams.info/")

    source = (site / "index.html").read_text(encoding="utf-8")
    blocks = re.findall(
        r'<script\s+type="application/ld\+json"\s*>(.*?)</script>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(blocks) != 1:
        failures.append("index.html: expected one JSON-LD graph")
    else:
        graph = json.loads(blocks[0]).get("@graph", [])
        failures.extend(check_jsonld_graph(graph))
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
    hero_src = [url for tag, attribute, url in parsed_pages[index_path].links if tag == "img" and attribute == "src"]
    for need in (
        "images/dSEAMS/image7.png",
        "images/science/gallery-cages-sII.png",
        "images/science/gallery-rings.png",
        "images/science/gallery-interface.png",
        "images/science/gallery-interface-raw.png",
        "images/science/sii.png",
        "images/logo/dSeamsLogo.png",
    ):
        if need not in hero_src:
            failures.append(f"index.html: missing figure or logo src: {need}")
    failures.extend(check_contract(site, parsed_pages[index_path]))
    failures.extend(check_seo(site, parsed_pages[index_path]))
    failures.extend(check_internal_text(site))
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
