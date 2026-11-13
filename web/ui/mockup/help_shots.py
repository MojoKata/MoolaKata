"""Makes the help guides' screenshots (requirements S12.7.5) from the generated mockup:
docs/mockups/MoolaKata-app.html opened from disk in headless Chromium, dark theme, 1280 px
wide, saved as PNG quantized to 256 colours in web/ui/guides/shots/. Run web/dev.sh mockup first
when the app changed.

    python web/ui/mockup/help_shots.py [key ...]   every screenshot, or the ones named
"""

import argparse
import io
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parents[1]
ROOT = UI.parents[1]
PAGE = ROOT / "docs" / "mockups" / "MoolaKata-app.html"
SHOTS = UI / "guides" / "shots"
SIZE = {"width": 1280, "height": 800}
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("keys", nargs="*", help="only these screenshots")
    args = p.parse_args(argv)
    if not PAGE.exists():
        sys.exit(
            f"no {PAGE.relative_to(ROOT)}: build it (web/dev.sh mockup), or save main's from "
            "https://mojokata.github.io/MoolaKata/mockup/MoolaKata-app.html there"
        )
    keys = set(args.keys) or wanted()

    from PIL import Image
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, color_scheme="dark", reduced_motion="reduce")
        # The screen alone: the help pane is where the screenshot is shown.
        ctx.add_init_script("localStorage.setItem('mk-help-open', 'false')")
        page = ctx.new_page()
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        url = PAGE.as_uri() + "#"
        page.goto(url + "/ui/")
        page.wait_for_selector(".side")
        paths = routes(page)
        unknown = sorted(keys - paths.keys())
        if unknown:
            sys.exit(f"no screen for {', '.join(unknown)}: add it to routes() in help_shots.py")
        for key in sorted(keys):
            page.goto(url + paths[key])
            page.wait_for_selector(".content > *")
            for _ in range(100):
                if not page.evaluate("!!document.querySelector('[aria-busy=\"true\"]')"):
                    break
                page.wait_for_timeout(50)
            page.wait_for_timeout(600)
            shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
            shot = shot.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
            shot.save(SHOTS / f"{key}.png", optimize=True)
            print(f"shots/{key}.png")
        browser.close()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
