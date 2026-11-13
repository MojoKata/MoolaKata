"""The ui-kit's pages packed into one file that opens on its own (requirements S17.3.10.4): a pull
request's run keeps it as its artifact, and main's is published on the Pages site under /kit/.

    python3 web/ui/kit/pages/pack.py OUT        writes OUT/kit.html

The pages' modules and the vendored libraries they load sit in the file as text; a small loader
gives each a blob: address, names them all in an import map and starts the catalog, as the
generated mockup does. The stylesheets and the icon sprite are inlined. Standard library only.
"""

import json
import re
import sys
from pathlib import Path

PAGES = Path(__file__).resolve().parent
UI = PAGES.parents[1]
# What names another module: an import, an export from one, a side-effect import, import().
IMPORTS = re.compile(
    r"""((?:^|\n)\s*(?:import|export)\s[^'"]*?from\s*|(?:^|\n)\s*import\s*|\bimport\(\s*)(['"])([^'"]+)\2"""
)


def import_map() -> dict[str, str]:
    """The vendored libraries the pages name, from their own import map, as files of ui/."""
    page = (PAGES / "index.html").read_text()
    m = re.search(r'<script type="importmap">\s*(\{.*?\})\s*</script>', page, re.S)
    assert m, "index.html has no import map"
    names = json.loads(m.group(1))["imports"]
    return {k: (PAGES / v).resolve().relative_to(UI).as_posix() for k, v in names.items()}


def modules() -> dict[str, str]:
    """Every module the catalog loads, by its path in ui/, its imports named by those paths."""
    bare = import_map()
    out: dict[str, str] = {}
    # The libraries whole, each as its import map names it: their own code asks for one
    # another by name, in a form the rewrite below may not see.
    todo = [PAGES / "catalog.js", *(UI / p for p in bare.values())]
    while todo:
        path = todo.pop()
        name = path.relative_to(UI).as_posix()
        if name in out:
            continue
        text = path.read_text()

        def rewrite(m: re.Match, path=path) -> str:
            spec = m.group(3)
            if spec.startswith("."):
                target = (path.parent / spec).resolve()
            elif spec in bare:
                target = UI / bare[spec]
            else:
                return m.group(0)
            todo.append(target)
            return f"{m.group(1)}{m.group(2)}@ui/{target.relative_to(UI).as_posix()}{m.group(2)}"

        out[name] = IMPORTS.sub(rewrite, text)
    return out


def embed(name: str, text: str) -> str:
    """A module's source, which sits in a <script> element as it is."""
    if re.search(r"</script|<!--", text, re.I):
        sys.exit(f"{name} holds </script or <!--, which the packed page cannot embed")
    return text


LOADER = """
(() => {
  // The modules sit in the page as text. Each gets a blob: address, an import map names them
  // all (and the libraries by their own names, as their own code asks for them), and then the
  // catalog starts.
  const urls = {};
  for (const s of document.querySelectorAll('script[data-module]')) {
    urls['@ui/' + s.dataset.module] = URL.createObjectURL(
      new Blob([s.textContent || ''], {
        type: s.dataset.module.endsWith('.json') ? 'application/json' : 'text/javascript',
      }),
    );
  }
  const bare = JSON.parse(document.getElementById('kit-bare').textContent);
  for (const [name, path] of Object.entries(bare)) urls[name] = urls['@ui/' + path];
  const map = document.createElement('script');
  map.type = 'importmap';
  map.textContent = JSON.stringify({ imports: urls });
  document.head.append(map);
  const main = document.createElement('script');
  main.type = 'module';
  main.textContent = "import '@ui/kit/pages/catalog.js';";
  document.body.append(main);
})();
"""


def pack() -> str:
    page = (PAGES / "index.html").read_text()
    css = "\n".join(
        (UI / p).read_text()
        for p in (
            "kit/theme/tokens.css",
            "kit/theme/base.css",
            "kit/theme/kit.css",
            "vendor/prosemirror-view/style/prosemirror.css",
            "kit/pages/pages.css",
        )
    )
    sprite = (UI / "kit" / "theme" / "icons.svg").read_text()
    sprite = re.sub(r"<\?xml.*?\?>\s*", "", sprite)
    hidden = '<svg id="mk-icons" aria-hidden="true" width="0" height="0" '
    sprite = sprite.replace("<svg ", hidden, 1)
    code = modules()
    scripts = "".join(
        f'<script type="text/plain" data-module="{n}">\n{embed(n, code[n])}</script>\n'
        for n in sorted(code)
    )
    # The packed page loads nothing from elsewhere: its policy, the page's own CSP, is left out,
    # since its modules run from blob: addresses and its styles sit in the page.
    page = re.sub(r'\s*<meta http-equiv="Content-Security-Policy"[^>]*>', "", page)
    page = re.sub(r"\s*<!--.*?-->", "", page, flags=re.S)
    page = re.sub(r'\s*<link rel="stylesheet"[^>]*>', "", page)
    page = re.sub(r'\s*<script type="importmap">.*?</script>', "", page, flags=re.S)
    page = re.sub(r'\s*<script type="module"[^>]*></script>', "", page)
    page = page.replace("</head>", f"<style>\n{css}\n</style>\n</head>", 1)
    page = page.replace('<div id="kit"></div>', f'{sprite.strip()}\n<div id="kit"></div>', 1)
    bare = json.dumps(import_map())
    return page.replace(
        "</body>",
        f'{scripts}<script type="application/json" id="kit-bare">{bare}</script>\n'
        f"<script>{LOADER}</script>\n</body>",
        1,
    )


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "kit.html").write_text(pack())
    print(out / "kit.html")


if __name__ == "__main__":
    main()
