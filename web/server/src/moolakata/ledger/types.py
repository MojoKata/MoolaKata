"""What account types are and how they group (requirements S1.1)."""

GROUPS = {
    "checking": "banking",
    "savings": "banking",
    "money-market": "banking",
    "cd": "banking",
    "cash": "banking",
    "payment-app": "banking",
    "credit-card": "liabilities",
    "brokerage": "investing",
    "ira": "retirement",
    "roth-ira": "retirement",
    "401k": "retirement",
    "403b": "retirement",
    "457b": "retirement",
    "hsa": "retirement",
    "mortgage": "liabilities",
    "heloc": "liabilities",
    "auto-loan": "liabilities",
    "student-loan": "liabilities",
    "personal-loan": "liabilities",
    "loan": "liabilities",
    "529": "education",
    "daf": "giving",
    "crypto-exchange": "crypto",
    "crypto-wallet": "crypto",
    "precious-metals": "physical-assets",
    "collectables": "physical-assets",
    "real-estate": "physical-assets",
    "vehicle": "physical-assets",
    "other-asset": "physical-assets",
}
GROUP_ORDER = [
    "banking",
    "investing",
    "retirement",
    "education",
    "crypto",
    "giving",
    "liabilities",
    "physical-assets",
]
LABELS = {
    "checking": "Checking",
    "savings": "Savings",
    "money-market": "Money market",
    "cd": "CD",
    "cash": "Cash",
    "payment-app": "Payment app",
    "credit-card": "Credit card",
    "brokerage": "Brokerage",
    "ira": "Traditional IRA",
    "roth-ira": "Roth IRA",
    "401k": "401(k)",
    "403b": "403(b)",
    "457b": "457(b)",
    "hsa": "HSA",
    "mortgage": "Mortgage",
    "heloc": "HELOC",
    "auto-loan": "Auto loan",
    "student-loan": "Student loan",
    "personal-loan": "Personal loan",
    "loan": "Loan",
    "529": "529 plan",
    "daf": "Donor-advised fund",
    "crypto-exchange": "Crypto exchange",
    "crypto-wallet": "Self-custody wallet",
    "precious-metals": "Precious metals",
    "collectables": "Collectables",
    "real-estate": "Real estate",
    "vehicle": "Vehicle",
    "other-asset": "Other asset",
}
TAX = {
    "checking": "taxable",
    "savings": "taxable",
    "money-market": "taxable",
    "cd": "taxable",
    "cash": None,
    "payment-app": None,
    "credit-card": None,
    "brokerage": "taxable",
    "ira": "deferred",
    "roth-ira": "free",
    "401k": "deferred",
    "403b": "deferred",
    "457b": "deferred",
    "hsa": "free",
    "mortgage": None,
    "heloc": None,
    "auto-loan": None,
    "student-loan": None,
    "personal-loan": None,
    "loan": None,
    "529": "free",  # for qualified expenses (S1.8.3)
    "daf": None,  # deducted when contributed; its money is given away
    "crypto-exchange": "taxable",
    "crypto-wallet": "taxable",
    # A sale's gain is taxable; metals and collectables at the collectables rate (S1.10.5).
    "precious-metals": "taxable",
    "collectables": "taxable",
    "real-estate": "taxable",
    "vehicle": "taxable",
    "other-asset": "taxable",
}


def investing(account_type: str) -> bool:
    """Holds instruments, so it has Holdings and Positions tabs."""
    return GROUPS[account_type] in ("investing", "retirement", "education", "giving", "crypto")


def reconcilable(account_type: str) -> bool:
    """Every account kept from files or statements has a Reconcile tab (S1.11): banking, cards,
    brokerage, retirement and plan accounts, 529s, DAFs and exchanges. A loan is checked
    against its servicer's balance on its own screen (S1.9.4); a watched wallet, cash on hand
    and a physical asset have no statements."""
    from ..loans import is_loan

    if is_loan(account_type) or account_type in ("crypto-wallet", "cash"):
        return False
    return GROUPS[account_type] != "physical-assets"


def retirement(account_type: str) -> bool:
    return GROUPS[account_type] == "retirement"
