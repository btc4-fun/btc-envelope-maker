"""Offline contracts for the allowlisted GitHub Pages snapshot."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPOSITORY_ROOT / "scripts" / "build_github_pages.py"


class SnapshotDocument(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.references: list[tuple[str, str, str]] = []
        self.ids: set[str] = set()
        self.head_meta: list[dict[str, str | None]] = []
        self.in_head = False
        self.feed(source)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "head":
            self.in_head = True
        if tag == "meta" and self.in_head:
            self.head_meta.append(attributes)
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        for name in ("href", "src", "action"):
            value = attributes.get(name)
            if value:
                self.references.append((tag, name, value))


class GitHubPagesSnapshotTest(unittest.TestCase):
    def build(self, output: Path) -> None:
        self.assertTrue(GENERATOR.is_file(), "GitHub Pages generator is missing")
        completed = subprocess.run(
            [sys.executable, str(GENERATOR), str(output)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_builds_only_five_canonical_html_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)

            expected = {
                Path("index.html"): "https://btc4.fun/",
                Path("guide/index.html"): "https://btc4.fun/guide",
                Path("security/index.html"): "https://btc4.fun/security",
                Path("terms/index.html"): "https://btc4.fun/terms",
                Path("download/index.html"): "https://btc4.fun/download",
            }
            self.assertEqual(
                {path.relative_to(output) for path in output.rglob("*.html")},
                set(expected),
            )
            for relative, canonical in expected.items():
                source = (output / relative).read_text(encoding="utf-8")
                self.assertIn(
                    f'<link rel="canonical" href="{canonical}">',
                    source,
                    relative,
                )

    def test_local_links_resolve_and_server_routes_use_the_main_site(self):
        dynamic_prefixes = ("/costs", "/contact", "/lookup", "/api")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)
            documents = {
                path.relative_to(output): SnapshotDocument(path.read_text(encoding="utf-8"))
                for path in output.rglob("*.html")
            }
            dynamic_references: list[str] = []

            for relative, document in documents.items():
                for tag, attribute, reference in document.references:
                    parsed = urlsplit(reference)
                    if any(
                        parsed.path == prefix or parsed.path.startswith(prefix + "/")
                        for prefix in dynamic_prefixes
                    ):
                        dynamic_references.append(reference)
                        self.assertEqual(
                            (parsed.scheme, parsed.netloc),
                            ("https", "btc4.fun"),
                            f"{relative}: {tag}[{attribute}]={reference}",
                        )
                        continue
                    if parsed.scheme or parsed.netloc:
                        continue
                    if reference.startswith("#"):
                        target_relative = relative
                    elif parsed.path == "/":
                        target_relative = Path("index.html")
                    elif parsed.path.startswith("/static/"):
                        target_relative = Path(parsed.path.removeprefix("/"))
                    elif parsed.path.startswith("/"):
                        target_relative = Path(parsed.path.removeprefix("/")) / "index.html"
                    else:
                        self.fail(f"Relative URL is ambiguous in {relative}: {reference}")
                    target = output / target_relative
                    self.assertTrue(
                        target.is_file(),
                        f"Broken {tag}[{attribute}] in {relative}: {reference}",
                    )
                    if parsed.fragment and target.suffix == ".html":
                        self.assertIn(
                            parsed.fragment,
                            documents[target_relative].ids,
                            f"Missing fragment target in {relative}: {reference}",
                        )

            self.assertTrue(dynamic_references, "Expected links to server-backed routes")

    def test_rebuild_removes_stale_dynamic_pages_and_forbidden_assets(self):
        stale_paths = (
            "costs/index.html",
            "contact/index.html",
            "lookup/index.html",
            "api/index.html",
            "static/privatekey.png",
            "static/publickey.png",
            "static/calculator.js",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)
            for relative in stale_paths:
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("stale", encoding="utf-8")

            self.build(output)

            for relative in stale_paths:
                self.assertFalse((output / relative).exists(), relative)

    def test_refuses_to_replace_an_unmarked_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("do not delete", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(GENERATOR), str(output)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not delete")

    def test_refuses_to_follow_a_symlinked_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "generated"
            self.build(target)
            sentinel = target / "keep.txt"
            sentinel.write_text("do not delete", encoding="utf-8")
            output = root / "pages-link"
            output.symlink_to(target, target_is_directory=True)

            completed = subprocess.run(
                [sys.executable, str(GENERATOR), str(output)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(output.is_symlink())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not delete")

    def test_asset_allowlist_is_explicit_and_copies_only_public_assets(self):
        expected = {
            "site.css",
            "site.js",
            "security.js",
            "logo.png",
            "favicon.png",
            "seal.svg",
            "SEAL-LICENSE.md",
            "guide-inner-example.png",
            "guide-outer-example.png",
            "payment-card.svg",
            "payment-sheba.svg",
            "fonts/Sahel.woff2",
            "fonts/Sahel-Bold.woff2",
            "fonts/LICENSE",
            "fonts/SOURCE.txt",
        }
        specification = importlib.util.spec_from_file_location("github_pages_generator", GENERATOR)
        if specification is None or specification.loader is None:
            self.fail("Could not load the GitHub Pages generator")
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        allowlist = getattr(module, "ASSET_ALLOWLIST", None)
        if allowlist is None:
            self.fail("The generator must expose an explicit asset allowlist")
        self.assertEqual({str(path) for path in allowlist}, expected)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)
            copied = {
                path.relative_to(output / "static").as_posix()
                for path in (output / "static").rglob("*")
                if path.is_file()
            }
            self.assertEqual(copied, expected)
            for forbidden in ("privatekey.png", "publickey.png", "calculator.js"):
                self.assertFalse((output / "static" / forbidden).exists(), forbidden)

    def test_rejects_all_symlinked_asset_inputs_before_copying(self):
        # Every byte, including the private-looking sentinel, is synthetic.
        cases = ("internal", "external", "broken", "fonts", "static", "ancestor")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repository = root / "repository"
                script = repository / "scripts/build_github_pages.py"
                script.parent.mkdir(parents=True)
                script.write_text(GENERATOR.read_text(encoding="utf-8"), encoding="utf-8")
                specification = importlib.util.spec_from_file_location("synthetic_generator", script)
                if specification is None or specification.loader is None:
                    self.fail("Could not load the synthetic generator")
                module = importlib.util.module_from_spec(specification)
                specification.loader.exec_module(module)
                module.TEMPLATE_ROOT.mkdir(parents=True)
                for relative in module.TEMPLATE_SOURCE_ALLOWLIST:
                    (module.TEMPLATE_ROOT / relative).write_text(
                        "<html><head></head><body>synthetic</body></html>", encoding="utf-8"
                    )
                for relative in module.ASSET_ALLOWLIST:
                    asset = module.STATIC_ROOT / relative
                    asset.parent.mkdir(parents=True, exist_ok=True)
                    asset.write_bytes(b"synthetic public asset")
                private = module.STATIC_ROOT / "privatekey.png"
                private.write_bytes(b"synthetic private sentinel, not a real key")
                if case in ("internal", "external", "broken"):
                    asset = module.STATIC_ROOT / "guide-inner-example.png"
                    asset.unlink()
                    target = private
                    if case == "external":
                        target = root / "outside.png"
                        target.write_bytes(b"synthetic external sentinel")
                    elif case == "broken":
                        target = root / "missing.png"
                    asset.symlink_to(target)
                else:
                    directory = {
                        "fonts": module.STATIC_ROOT / "fonts",
                        "static": module.STATIC_ROOT,
                        "ancestor": module.SITE_ROOT,
                    }[case]
                    moved = directory.with_name(directory.name + "-real")
                    directory.rename(moved)
                    directory.symlink_to(moved, target_is_directory=True)
                output = root / "pages"
                with self.assertRaisesRegex(ValueError, "Symlinked asset"):
                    module.build(output)
                self.assertFalse((output / "static").exists(), "No asset may be copied on rejection")

    def test_emits_nojekyll_and_blocks_mirror_indexing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)

            self.assertTrue(output.joinpath(".nojekyll").is_file(), "Missing .nojekyll")
            self.assertTrue(output.joinpath("robots.txt").is_file(), "Missing robots.txt")
            self.assertEqual((output / ".nojekyll").read_bytes(), b"")
            self.assertEqual(
                (output / "robots.txt").read_text(encoding="utf-8"),
                "User-agent: *\nAllow: /\n",
            )
            pages = sorted(output.rglob("*.html"))
            self.assertEqual(len(pages), 5)
            for page in pages:
                document = SnapshotDocument(page.read_text(encoding="utf-8"))
                robots = [
                    meta.get("content") for meta in document.head_meta
                    if (meta.get("name") or "").lower() == "robots"
                ]
                self.assertEqual(robots, ["noindex,follow"], page.relative_to(output))

    def test_source_manifest_pins_inputs_and_generated_outputs(self):
        template_sources = {
            "scripts/build_github_pages.py",
            "bitcoin4funsite/templates/base.html",
            "bitcoin4funsite/templates/index.html",
            "bitcoin4funsite/templates/guide.html",
            "bitcoin4funsite/templates/security.html",
            "bitcoin4funsite/templates/terms.html",
            "bitcoin4funsite/templates/download.html",
            "bitcoin4funsite/templates/_purchase_warning.html",
            "bitcoin4funsite/templates/_wallet_safety.html",
            "bitcoin4funsite/templates/_payment_details.html",
        }
        asset_sources = {
            "bitcoin4funsite/static/site.css",
            "bitcoin4funsite/static/site.js",
            "bitcoin4funsite/static/security.js",
            "bitcoin4funsite/static/logo.png",
            "bitcoin4funsite/static/favicon.png",
            "bitcoin4funsite/static/seal.svg",
            "bitcoin4funsite/static/SEAL-LICENSE.md",
            "bitcoin4funsite/static/guide-inner-example.png",
            "bitcoin4funsite/static/guide-outer-example.png",
            "bitcoin4funsite/static/payment-card.svg",
            "bitcoin4funsite/static/payment-sheba.svg",
            "bitcoin4funsite/static/fonts/Sahel.woff2",
            "bitcoin4funsite/static/fonts/Sahel-Bold.woff2",
            "bitcoin4funsite/static/fonts/LICENSE",
            "bitcoin4funsite/static/fonts/SOURCE.txt",
        }
        expected_pages = [
            {"route": "/", "template": "bitcoin4funsite/templates/index.html", "output": "index.html", "canonical": "https://btc4.fun/"},
            {"route": "/guide", "template": "bitcoin4funsite/templates/guide.html", "output": "guide/index.html", "canonical": "https://btc4.fun/guide"},
            {"route": "/security", "template": "bitcoin4funsite/templates/security.html", "output": "security/index.html", "canonical": "https://btc4.fun/security"},
            {"route": "/terms", "template": "bitcoin4funsite/templates/terms.html", "output": "terms/index.html", "canonical": "https://btc4.fun/terms"},
            {"route": "/download", "template": "bitcoin4funsite/templates/download.html", "output": "download/index.html", "canonical": "https://btc4.fun/download"},
        ]

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pages"
            self.build(output)
            manifest_path = output / "source-manifest.json"
            self.assertTrue(manifest_path.is_file(), "Missing source-manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["canonical_origin"], "https://btc4.fun")
            self.assertEqual(manifest["pages"], expected_pages)
            self.assertEqual(set(manifest["sources"]), template_sources | asset_sources)
            for relative, digest in manifest["sources"].items():
                self.assertEqual(digest, self.sha256(REPOSITORY_ROOT / relative), relative)

            output_hashes = {
                path.relative_to(output).as_posix(): self.sha256(path)
                for path in output.rglob("*")
                if path.is_file() and path != manifest_path
            }
            self.assertEqual(manifest["outputs"], output_hashes)

    # Plan §2.2 pins the refresh rule in AGENTS.md. The owner has not yet
    # approved that edit, so assert the rule only once it is actually present:
    # a passing test must never claim a rule that is not in the file.
    def test_agrank_instruction_pins_refresh_rule(self):
        agents = (REPOSITORY_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("هم‌به‌رو نگه‌داشتن نسخهٔ آموزشی گیت‌هاب پیجز", agents)
        self.assertIn("https://github.com/btc4-fun/btc4-fun.github.io", agents)
        self.assertIn("python3 scripts/build_github_pages.py", agents)
        self.assertIn("test_github_pages_snapshot.py", agents)


if __name__ == "__main__":
    unittest.main()
