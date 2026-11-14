"""Makes the screenshots of the app (requirements S12.7.5) from the generated mockup,
docs/mockups/MoolaKata-app.html opened from disk in headless Chromium, each saved as PNG
quantized to 256 colours. CI makes them on every run and publishes main's; they aren't
committed.

    guides    each help guide's screen, dark, 1280 px wide: web/ui/guides/shots/<key>.png
    readme    the README's dashboard, light and dark, 1440 px at twice the density
    truenas   the TrueNAS catalog's four pictures of the app, dark, 1280 x 800

    web/dev.sh make-screenshots [--set guides|readme|truenas] [--out DIR] [--check] [key ...]
    web/dev.sh download-screenshots          main's help screenshots, from the Pages site

With --out, each set goes to DIR/<set>/; without it, the guides' to web/ui/guides/shots/ (where
the dev server finds them) and the rest to web/.dev/screenshots/<set>/. --check fails when a
guide shows a screenshot no screen makes, or a screen is made that no guide shows.
"""

import argparse
import io
import re
import sys
import urllib.request
from pathlib import Path

UI = Path(__file__).resolve().parents[1]
ROOT = UI.parents[1]
PAGE = ROOT / "docs" / "mockups" / "MoolaKata-app.html"
SHOTS = UI / "guides" / "shots"
OTHERS = UI.parent / ".dev" / "screenshots"
PAGES = "https://mojokata.github.io/MoolaKata/screenshots"
SIZE = {"width": 1280, "height": 800}
SETS = ("guides", "readme", "truenas")
# The TrueNAS catalog's pictures of the app, in the order its listing shows them.
TRUENAS = ("dashboard", "accounts", "account-holdings", "budgets-month")
SETTINGS = (
    "general",
    "email",
    "sessions",
    "signup",
    "passwords",
    "prices",
    "bitcoin",
    "links",
    "connector",
    "imports",
    "receipts",
    "tax-tables",
    "backups",
    "storage",
    "keys",
    "network",
    "alerts",
)


def wanted() -> set[str]:
    """Every screenshot a guide shows."""
    keys = set()
    for md in (UI / "guides").glob("*.md"):
        keys |= set(re.findall(r"\(shots/([\w-]+)\.png\)", md.read_text()))
    return keys


def routes(page) -> dict[str, str]:
    accounts = page.evaluate("async () => (await (await fetch('/ui/api/accounts')).json()).items")
    ports = page.evaluate("async () => (await (await fetch('/ui/api/portfolios')).json()).items")
    by_type = {a["type"]: a["id"] for a in accounts}
    budgets = page.evaluate("async () => (await (await fetch('/ui/api/budgets')).json()).items")
    budget = budgets[0]["id"]
    checking, brokerage, port = by_type["checking"], by_type["brokerage"], ports[0]["id"]
    out = {
        "dashboard": "/ui/",
        "accounts": "/ui/accounts",
        "transactions": "/ui/transactions",
        "portfolios": "/ui/portfolios",
        "positions-open": "/ui/positions/open",
        "positions-strategies": "/ui/positions/strategies",
        "positions-closed": "/ui/positions/closed",
        "positions-trades": "/ui/positions/trades",
        "positions-gains": "/ui/positions/gains",
        "activity": "/ui/activity",
        "alerts": "/ui/alerts",
        "receipts": "/ui/receipts",
        "projections": "/ui/projections",
        "budgets-month": f"/ui/budgets/{budget}/month",
        "users": "/ui/users",
        "profile": "/ui/profile",
        "account-overview": f"/ui/accounts/{checking}/overview",
        "account-transactions": f"/ui/accounts/{checking}/transactions",
        "account-reconcile": f"/ui/accounts/{checking}/reconcile",
        "account-sharing": f"/ui/accounts/{checking}/sharing",
        "account-settings": f"/ui/accounts/{checking}/settings",
        "account-holdings": f"/ui/accounts/{brokerage}/holdings",
        "account-schedule": f"/ui/accounts/{by_type['mortgage']}/schedule",
        "account-payoff": f"/ui/accounts/{by_type['mortgage']}/payoff",
        "account-items": f"/ui/accounts/{by_type['precious-metals']}/items",
        "account-contributions": f"/ui/accounts/{by_type['529']}/contributions",
        "account-withdrawals": f"/ui/accounts/{by_type['529']}/withdrawals",
        "account-goal": f"/ui/accounts/{by_type['529']}/goal",
        "gifts-upcoming": "/ui/gifts/upcoming",
        "gifts-people": "/ui/gifts/people",
        "gifts-gifts": "/ui/gifts/gifts",
        "gifts-spending": "/ui/gifts/spending",
        "giving-overview": "/ui/giving/overview",
        "giving-donations": "/ui/giving/donations",
        "giving-organisations": "/ui/giving/organisations",
        "giving-fund": "/ui/giving/fund",
        "taxes-summary": "/ui/taxes/summary",
        "taxes-filings": "/ui/taxes/filings",
        "taxes-documents": "/ui/taxes/documents",
        **{
            f"taxes-{k}": f"/ui/taxes/{k}"
            for k in (
                "gains",
                "income",
                "retirement",
                "deductions",
                "giving",
                "education",
                "property",
                "issues",
            )
        },
        "portfolio-performance": f"/ui/portfolios/{port}/performance",
        "portfolio-holdings": f"/ui/portfolios/{port}/holdings",
    }
    out.update({f"settings-{s}": f"/ui/settings/{s}" for s in SETTINGS})
    return out


def settle(page) -> None:
    """Until the screen has drawn what it asked for: nothing marked busy, then a moment for the
    charts to finish (a tool's wait, not a test's)."""
    page.wait_for_selector(".content > *")
    page.wait_for_function("() => !document.querySelector('[aria-busy=\"true\"]')")
    page.wait_for_timeout(600)


def save(png: bytes, path: Path) -> None:
    from PIL import Image

    shot = Image.open(io.BytesIO(png)).convert("RGB")
    shot = shot.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    path.parent.mkdir(parents=True, exist_ok=True)
    shot.save(path, optimize=True)
    print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def opened(browser, theme: str, scale: int = 1, size: dict | None = None):
    ctx = browser.new_context(
        viewport=size or SIZE, color_scheme=theme, reduced_motion="reduce",
        device_scale_factor=scale,
    )  # fmt: skip
    # The screen alone: the help pane is where a guide's screenshot is shown.
    ctx.add_init_script("localStorage.setItem('mk-help-open', 'false')")
    page = ctx.new_page()
    return ctx, page


def download(out: Path) -> int:
    """Main's help screenshots, as the Pages site has them, for each one a guide shows."""
    out.mkdir(parents=True, exist_ok=True)
    missing = []
    for key in sorted(wanted()):
        url = f"{PAGES}/guides/shots/{key}.png"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - a fixed https host
                (out / f"{key}.png").write_bytes(r.read())
        except OSError as e:
            missing.append(f"{key}: {e}")
    print(f"{len(wanted()) - len(missing)} screenshots in {out.relative_to(ROOT)}")
    if missing:
        print("not on the Pages site:\n  " + "\n  ".join(missing), file=sys.stderr)
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("keys", nargs="*", help="only these guides' screenshots")
    p.add_argument("--set", choices=SETS, action="append", help="only this set (repeatable)")
    p.add_argument("--out", type=Path, help="each set into OUT/<set>/")
    p.add_argument("--check", action="store_true", help="guides and screens agree")
    p.add_argument("--download", action="store_true", help="main's, from the Pages site")
    args = p.parse_args(argv)
    if args.download:
        return download(args.out / "guides" if args.out else SHOTS)
    if not PAGE.exists():
        sys.exit(
            f"no {PAGE.relative_to(ROOT)}: build it (web/dev.sh mockup), or save main's from "
            "https://mojokata.github.io/MoolaKata/mockup/MoolaKata-app.html there"
        )
    sets = args.set or list(SETS)

    def where(name: str) -> Path:
        if args.out:
            return args.out / name / ("shots" if name == "guides" else "")
        return SHOTS if name == "guides" else OTHERS / name

    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        url = PAGE.as_uri() + "#"
        ctx, page = opened(browser, "dark")
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.goto(url + "/ui/")
        page.wait_for_selector(".side")
        paths = routes(page)
        if args.check:
            shown, made = wanted(), set(paths)
            problems += [
                f"a guide shows shots/{k}.png, which no screen makes" for k in shown - made
            ]
            problems += [f"{k} is made, but no guide shows it" for k in made - shown]
        if "guides" in sets:
            keys = set(args.keys) or wanted()
            unknown = sorted(keys - paths.keys())
            if unknown:
                sys.exit(
                    f"no screen for {', '.join(unknown)}: add it to routes() in screenshots.py"
                )
            for key in sorted(keys):
                page.goto(url + paths[key])
                settle(page)
                save(page.screenshot(), where("guides") / f"{key}.png")
        if "truenas" in sets:
            for n, key in enumerate(TRUENAS, 1):
                page.goto(url + paths[key])
                settle(page)
                save(page.screenshot(), where("truenas") / f"moolakata-{n}.png")
        ctx.close()
        if "readme" in sets:
            for theme in ("light", "dark"):
                ctx, page = opened(browser, theme, 2, {"width": 1440, "height": 1080})
                page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
                page.goto(url + "/ui/")
                settle(page)
                save(page.screenshot(), where("readme") / f"dashboard-{theme}.png")
                ctx.close()
        browser.close()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
