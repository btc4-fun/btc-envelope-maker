#!/usr/bin/env python3
"""Build the allowlisted educational snapshot for GitHub Pages."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = REPOSITORY_ROOT / "bitcoin4funsite"
TEMPLATE_ROOT = SITE_ROOT / "templates"
STATIC_ROOT = SITE_ROOT / "static"

# Only these reviewed public files may cross into the Pages artifact. In
# particular, operator wallet images and the server-backed calculator are not
# candidates even when they exist in the source directory.
ASSET_ALLOWLIST = tuple(
    Path(name)
    for name in (
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
    )
)
FORBIDDEN_ASSET_NAMES = frozenset({"privatekey.png", "publickey.png", "calculator.js"})
TEMPLATE_SOURCE_ALLOWLIST = tuple(
    Path(name)
    for name in (
        "base.html",
        "index.html",
        "guide.html",
        "security.html",
        "terms.html",
        "download.html",
        "_purchase_warning.html",
        "_wallet_safety.html",
        "_payment_details.html",
    )
)

# This is the complete HTML publication allowlist. Server-backed routes are not
# rendered and the authoritative canonical origin stays on the Flask site.
PAGES = (
    ("/", "index.html", Path("index.html"), "https://btc4.fun/"),
    ("/guide", "guide.html", Path("guide/index.html"), "https://btc4.fun/guide"),
    ("/security", "security.html", Path("security/index.html"), "https://btc4.fun/security"),
    ("/terms", "terms.html", Path("terms/index.html"), "https://btc4.fun/terms"),
    ("/download", "download.html", Path("download/index.html"), "https://btc4.fun/download"),
)
DYNAMIC_ROUTE_PREFIXES = ("/costs", "/contact", "/lookup", "/api", "/aml")
LOCAL_ATTRIBUTE = re.compile(
    r"(?P<prefix>\b(?:href|src|action)\s*=\s*)(?P<quote>[\"'])(?P<url>/[^\"']*)(?P=quote)",
    re.IGNORECASE,
)


def rewrite_links(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        reference = match.group("url")
        path = reference.split("#", 1)[0].split("?", 1)[0]
        if any(path == prefix or path.startswith(prefix + "/") for prefix in DYNAMIC_ROUTE_PREFIXES):
            reference = "https://btc4.fun" + reference
        elif path == "/t":
            reference = "/terms" + reference[len(path):]
        return match.group("prefix") + match.group("quote") + reference + match.group("quote")

    return LOCAL_ATTRIBUTE.sub(replace, source)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_output(output: Path) -> Path:
    expanded = output.expanduser()
    if expanded.is_symlink():
        raise ValueError("Refusing to replace a symlinked output directory")
    resolved = expanded.resolve()
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError("Output path must be a directory")
        populated = next(resolved.iterdir(), None) is not None
        generated = (resolved / ".nojekyll").is_file() and (resolved / "source-manifest.json").is_file()
        if populated and not generated:
            raise ValueError("Refusing to replace an unmarked non-empty directory")
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)
    return resolved


def build(output: Path) -> None:
    # Check lexical paths before resolve() can hide a symlink, including links
    # in STATIC_ROOT or any ancestor. Validate the entire list before any I/O
    # that copies or hashes asset contents (or replaces an existing snapshot).
    static_root = STATIC_ROOT.resolve()
    assets = []
    for relative in ASSET_ALLOWLIST:
        if relative.name.lower() in FORBIDDEN_ASSET_NAMES:
            raise ValueError(f"Forbidden asset in publication allowlist: {relative}")
        source = STATIC_ROOT / relative
        if any(path.is_symlink() for path in (source, *source.parents)):
            raise ValueError(f"Symlinked asset input: {relative}")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(static_root) or not resolved.is_file():
            raise ValueError(f"Invalid allowlisted asset: {relative}")
        assets.append((relative, resolved))

    output = prepare_output(output)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=select_autoescape(["html"]),
    )
    output.mkdir(parents=True, exist_ok=True)
    for _route, template_name, relative_output, canonical in PAGES:
        target = output / relative_output
        target.parent.mkdir(parents=True, exist_ok=True)
        rendered = environment.get_template(template_name).render(canonical_url=canonical)
        # Crawlers must be allowed to fetch the page to observe this directive.
        rendered = rendered.replace(
            "</head>", '<meta name="robots" content="noindex,follow">\n</head>', 1
        )
        target.write_text(rewrite_links(rendered), encoding="utf-8")

    static_output = output / "static"
    for relative, source in assets:
        target = static_output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    (output / ".nojekyll").write_bytes(b"")
    (output / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n",
        encoding="utf-8",
    )

    source_paths = (
        (Path(__file__).resolve(),)
        + tuple(TEMPLATE_ROOT / path for path in TEMPLATE_SOURCE_ALLOWLIST)
        + tuple(STATIC_ROOT / path for path in ASSET_ALLOWLIST)
    )
    sources = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): sha256(path)
        for path in sorted(source_paths)
    }
    manifest_path = output / "source-manifest.json"
    outputs = {
        path.relative_to(output).as_posix(): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    manifest = {
        "schema_version": 1,
        "canonical_origin": "https://btc4.fun",
        "pages": [
            {
                "route": route,
                "template": (TEMPLATE_ROOT / template).relative_to(REPOSITORY_ROOT).as_posix(),
                "output": relative_output.as_posix(),
                "canonical": canonical,
            }
            for route, template, relative_output, canonical in PAGES
        ],
        "sources": sources,
        "outputs": outputs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="directory to replace with the static snapshot")
    arguments = parser.parse_args()
    build(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
