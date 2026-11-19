"""Tests for exceptions in the static site contract."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check-site.py")
SPEC = importlib.util.spec_from_file_location("check_site", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK_SITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_SITE)


class ForthcomingNoticeTests(unittest.TestCase):
    def test_allows_exact_paper_notice(self) -> None:
        source = '<p id="forthcoming-paper-status">Coming soon.</p>'

        self.assertEqual(CHECK_SITE.check_forthcoming_notice(source), [])

    def test_rejects_release_status_notice(self) -> None:
        source = (
            '<p id="forthcoming-paper-status">Coming soon.</p>'
            '<p class="release-status">Package coming soon.</p>'
        )

        self.assertEqual(
            CHECK_SITE.check_forthcoming_notice(source),
            ["index.html: reader-facing plumbing: coming soon"],
        )


def _valid_tabs_html() -> str:
    tabs = "\n".join(
        f'<button type="button" role="tab" id="{tab}" aria-controls="{panel}">{tab}</button>'
        for tab, panel in CHECK_SITE.EXPECTED_BINDING_TABS
    )
    panels = "\n".join(
        f'<article role="tabpanel" id="{panel}"></article>'
        for _tab, panel in CHECK_SITE.EXPECTED_BINDING_TABS
    )
    return f'<section id="install"><div role="tablist">{tabs}</div>{panels}</section>'


def _valid_linkcell_section_html() -> str:
    return (
        '<section id="install"></section>'
        '<section id="linkcell">'
        '<p>d-SEAMS uses linkcell for neighbour search, but it stands alone.</p>'
        '<p>Orthogonal and triclinic periodic cells in Rust, C, C++, and Python.</p>'
        '<a href="https://linkcell.dseams.info/">Open linkcell book</a>'
        '<a href="https://linkcell.dseams.info/explanation/mic-and-cells/">Minimum image &amp; cells</a>'
        '<a href="https://github.com/Luthaf/vesin">vesin repo</a>'
        '<code>pip install linkcell numpy</code>'
        '<code>cargo add linkcell</code>'
        '<code>nn, d2 = linkcell.knearest(xyz, cell, 1)</code>'
        '<p>Drop-in replacement for vesin with pairs_within, NeighborList, and lc_vesin_neighbors.</p>'
        '<code>from linkcell import NeighborList</code>'
        '</section>'
    )


def _valid_grouping_html() -> str:
    return (
        '<nav aria-label="Primary">'
        '<a href="#install">Install</a>'
        '<a href="#linkcell">Libraries</a>'
        '<div class="docs-menu">'
        '<span class="docs-menu-label">Engine &amp; bindings</span>'
        '<a href="https://docs.dseams.info/">Engine &amp; CLI</a>'
        '<span class="docs-menu-label">Libraries</span>'
        '<a href="https://linkcell.dseams.info/">linkcell</a>'
        '</div>'
        '</nav>'
        '<nav class="books-strip">'
        '<div class="books-group">'
        '<span class="books-group-label">Engine &amp; bindings</span>'
        '<a href="https://docs.dseams.info/">docs.dseams.info</a>'
        '</div>'
        '<div class="books-group">'
        '<span class="books-group-label">Libraries</span>'
        '<a href="https://linkcell.dseams.info/">linkcell.dseams.info</a>'
        '</div>'
        '</nav>'
        '<nav class="foot-links">'
        '<div class="foot-group">'
        '<span class="foot-group-label">Engine &amp; bindings</span>'
        '<a href="https://docs.dseams.info/">Docs</a>'
        '</div>'
        '<div class="foot-group">'
        '<span class="foot-group-label">Libraries</span>'
        '<a href="https://linkcell.dseams.info/">linkcell</a>'
        '</div>'
        '</nav>'
    )


class BindingsTabsTests(unittest.TestCase):
    def test_accepts_seven_binding_tabs_without_linkcell(self) -> None:
        self.assertEqual(CHECK_SITE.check_bindings_tabs(_valid_tabs_html()), [])

    def test_rejects_linkcell_in_bindings_tabs(self) -> None:
        html = _valid_tabs_html().replace(
            '</div>',
            '<button type="button" role="tab" id="tab-linkcell" aria-controls="panel-linkcell">linkcell</button></div>'
            '<article role="tabpanel" id="panel-linkcell"></article>',
            1,
        )
        failures = CHECK_SITE.check_bindings_tabs(html)
        self.assertIn("index.html: linkcell must not appear in bindings tabs", failures)
        self.assertIn("index.html: panel-linkcell must not exist as a binding tabpanel", failures)


class LinkcellSectionTests(unittest.TestCase):
    def test_accepts_standalone_linkcell_section(self) -> None:
        self.assertEqual(CHECK_SITE.check_linkcell_section(_valid_linkcell_section_html()), [])

    def test_requires_standalone_linkcell_section(self) -> None:
        failures = CHECK_SITE.check_linkcell_section('<section id="install"></section>')
        self.assertEqual(failures, ["index.html: missing standalone #linkcell section"])

    def test_rejects_linkcell_inside_install_and_missing_cargo_add(self) -> None:
        html = (
            '<section id="install"><section id="linkcell">'
            '<a href="https://linkcell.dseams.info/">Book</a>'
            '<code>pip install linkcell numpy</code>'
            '<code>linkcell.knearest(xyz, cell, 1)</code>'
            '<p>orthogonal triclinic stands alone neighbour search</p>'
            '</section></section>'
        )
        failures = CHECK_SITE.check_linkcell_section(html)
        self.assertIn("index.html: #linkcell section must be outside #install bindings", failures)
        self.assertIn("index.html: #linkcell section missing copy: cargo add linkcell", failures)

    def test_case_insensitive_orthogonal_check_preserved(self) -> None:
        html = _valid_linkcell_section_html().replace("Orthogonal", "orthogonal")
        self.assertEqual(CHECK_SITE.check_linkcell_section(html), [])

    def test_requires_vesin_links_and_note(self) -> None:
        no_vesin_repo = _valid_linkcell_section_html().replace(
            '<a href="https://github.com/Luthaf/vesin">vesin repo</a>',
            '',
        )
        self.assertIn(
            "index.html: #linkcell section missing link to https://github.com/Luthaf/vesin",
            CHECK_SITE.check_linkcell_section(no_vesin_repo),
        )
        no_mic_link = _valid_linkcell_section_html().replace(
            '<a href="https://linkcell.dseams.info/explanation/mic-and-cells/">Minimum image &amp; cells</a>',
            '',
        )
        self.assertIn(
            "index.html: #linkcell section missing link to https://linkcell.dseams.info/explanation/mic-and-cells/",
            CHECK_SITE.check_linkcell_section(no_mic_link),
        )
        no_swap = _valid_linkcell_section_html().replace(
            '<code>from linkcell import NeighborList</code>',
            '',
        )
        self.assertIn(
            "index.html: #linkcell section missing copy: from linkcell import NeighborList",
            CHECK_SITE.check_linkcell_section(no_swap),
        )


class LibraryGroupingTests(unittest.TestCase):
    def test_accepts_grouped_library_links(self) -> None:
        self.assertEqual(CHECK_SITE.check_library_grouping(_valid_grouping_html()), [])

    def test_rejects_ungrouped_docs_menu_linkcell(self) -> None:
        html = _valid_grouping_html().replace(
            '<span class="docs-menu-label">Libraries</span>',
            '',
        )
        failures = CHECK_SITE.check_library_grouping(html)
        self.assertIn(
            "index.html: Docs menu must group linkcell under Libraries label",
            failures,
        )


class JsonLdTests(unittest.TestCase):
    def _valid_graph(self) -> list[dict]:
        return [
            {
                "@type": "SoftwareApplication",
                "@id": "https://dseams.info/#software",
                "sameAs": [
                    "https://github.com/d-SEAMS",
                    "https://crates.io/crates/dseams",
                ],
            },
            {
                "@type": "SoftwareSourceCode",
                "@id": "https://github.com/d-SEAMS/linkcell",
                "name": "linkcell",
                "url": "https://linkcell.dseams.info/",
                "codeRepository": "https://github.com/d-SEAMS/linkcell",
                "sameAs": [
                    "https://crates.io/crates/linkcell",
                    "https://pypi.org/project/linkcell/",
                ],
            },
            {
                "@type": "ScholarlyArticle",
                "@id": "https://dseams.info/#dseams-2-paper",
                "name": "d-SEAMS 2.0: Incremental ring and cage algorithms for ice structure analysis",
                "creativeWorkStatus": "Forthcoming",
                "author": [
                    {"name": "Rohit Goswami", "@id": "https://orcid.org/0000-0002-2393-8056"},
                    {"name": "Amrita Goswami", "@id": "https://orcid.org/0000-0001-8706-2383"},
                    {"name": "Ruhila Goswami", "@id": "https://orcid.org/0000-0002-5443-9356"},
                    {"name": "Jayant K. Singh", "@id": "https://orcid.org/0000-0001-8056-2115"},
                ],
            },
        ]

    def test_accepts_separate_linkcell_jsonld_node(self) -> None:
        self.assertEqual(CHECK_SITE.check_jsonld_graph(self._valid_graph()), [])

    def test_rejects_linkcell_sameas_on_dseams_app(self) -> None:
        graph = self._valid_graph()
        graph[0]["sameAs"].append("https://crates.io/crates/linkcell")
        failures = CHECK_SITE.check_jsonld_graph(graph)
        self.assertIn(
            "index.html: d-SEAMS SoftwareApplication must not list linkcell crate in sameAs",
            failures,
        )

    def test_rejects_missing_linkcell_source_node(self) -> None:
        graph = [node for node in self._valid_graph() if node.get("name") != "linkcell"]
        failures = CHECK_SITE.check_jsonld_graph(graph)
        self.assertIn("index.html: invalid standalone linkcell JSON-LD node", failures)


if __name__ == "__main__":
    unittest.main()
