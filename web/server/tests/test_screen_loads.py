"""A screen waiting on what it loads shows a load's failure, never a skeleton forever, so
it settles (requirements S17.5: no Loading placeholder showing): every `useApi`/`useList`
whose data a `Loading` return waits on has its `.error` read in the same function. The Users
screen waited on its groups without reading their error, so a refused request (a 429 in a quick
run through every screen) left it loading.

Read from the source: each function's `const` declarations are followed from the Loading
condition's names back to the loads they come from.
"""

import re

from moolakata import paths

DECL = re.compile(r"const (?:\{[^}]*\}|\[[^\]]*\]|(\w+)) = ([^;]*);", re.S)
LOAD = re.compile(r"\buse(?:Api|List)\(")
GUARD = re.compile(r"if \(([^)]*(?:\([^)]*\)[^)]*)*)\)\s*(?:\{\s*)?return html`<\$\{Loading\}")
NAME = re.compile(r"\b([A-Za-z_]\w*)\b")


def functions(src: str):
    """Each top-level function's body, cut at the next one."""
    starts = [m.start() for m in re.finditer(r"^(?:export )?(?:default )?function ", src, re.M)]
    for a, b in zip(starts, [*starts[1:], len(src)], strict=False):  # none: nothing
        yield src[a:b]


def waits_without_error(body: str) -> list[str]:
    decls = {m[1]: m[2] for m in DECL.finditer(body) if m[1]}
    loads = {n for n, init in decls.items() if LOAD.search(init)}
    out = []
    for g in GUARD.finditer(body):
        seen, todo, hit = set(), NAME.findall(g[1]), set()
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in loads:
                hit.add(n)
            elif n in decls:
                todo += NAME.findall(decls[n])
        out += [n for n in sorted(hit) if not re.search(rf"\b{n}\.error\b", body)]
    return out


def test_a_screen_waiting_on_a_load_shows_its_failure():
    wrong = []
    for p in sorted(paths.UI.glob("*/*.js")):
        if p.parent.name in ("vendor", "mockup", "tests"):
            continue
        for body in functions(p.read_text()):
            name = re.match(r"(?:export )?(?:default )?function (\w*)", body)[1]
            wrong += [f"{p.relative_to(paths.UI)} {name}: {n}" for n in waits_without_error(body)]
    assert not wrong, "waits on a load whose error it never shows:\n" + "\n".join(wrong)


def test_the_check_finds_a_load_waited_on_through_a_name():
    body = """function Users() {
  const users = useList('/users');
  const groups = useList('/groups');
  const u = /** @type {any[]} */ (users.data);
  const g = /** @type {any[]} */ (groups.data);
  if (users.error) return html`<${Failed} error=${users.error} />`;
  if (!u || !g) return html`<${Loading} lines=${8} />`;
}"""
    assert waits_without_error(body) == ["groups"]
    assert (
        waits_without_error(body.replace("if (users.error)", "if (users.error || groups.error)"))
        == []
    )
