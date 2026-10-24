"""The categories that ship (requirements S7.2): a two-level tree, each an expense, income,
savings or transfer category, some with the tax tag that feeds Taxes."""

# (key, name, kind, tax tag, children: [(key, name, tax tag[, kind])]); a child is its parent's
# kind unless it says otherwise.
DEFAULTS = [
    (
        "income",
        "Income",
        "income",
        None,
        [
            ("income.salary", "Salary", None),
            ("income.interest", "Interest", None),
            ("income.dividends", "Dividends", None),
            ("income.refunds", "Refunds", None),
            ("income.other", "Other income", None),
        ],
    ),
    (
        "housing",
        "Housing",
        "expense",
        None,
        [
            ("housing.rent", "Rent", None),
            ("housing.mortgage", "Mortgage", None),
            ("housing.utilities", "Utilities", None),
            ("housing.insurance", "Insurance", None),
            ("housing.maintenance", "Maintenance", None),
            ("housing.property-tax", "Property tax", "property-tax"),
        ],
    ),
    (
        "food",
        "Food",
        "expense",
        None,
        [("food.groceries", "Groceries", None), ("food.dining", "Dining out", None)],
    ),
    (
        "transport",
        "Transportation",
        "expense",
        None,
        [
            ("transport.fuel", "Fuel", None),
            ("transport.insurance", "Car insurance", None),
            ("transport.maintenance", "Car maintenance", None),
            ("transport.transit", "Public transit", None),
            ("transport.parking", "Parking", None),
        ],
    ),
    (
        "health",
        "Health",
        "expense",
        None,
        [
            ("health.doctor", "Doctor", "medical"),
            ("health.pharmacy", "Pharmacy", "medical"),
            ("health.insurance", "Health insurance", "medical"),
        ],
    ),
    (
        "personal",
        "Personal",
        "expense",
        None,
        [
            ("personal.clothing", "Clothing", None),
            ("personal.care", "Personal care", None),
            ("personal.subscriptions", "Subscriptions", None),
        ],
    ),
    ("childcare", "Childcare", "expense", "childcare", []),
    ("education", "Education", "expense", "education", []),
    ("entertainment", "Entertainment", "expense", None, []),
    ("travel", "Travel", "expense", None, []),
    ("gifts", "Gifts", "expense", None, []),
    ("giving", "Giving", "expense", "charitable", []),
    ("business", "Business", "expense", "business", []),
    ("taxes", "Taxes", "expense", None, []),
    ("fees", "Fees and charges", "expense", None, []),
    # Cash taken out and spent, or moved to a cash account outside a budget (S7.3.2).
    ("cash", "Cash", "expense", None, []),
    (
        "savings",
        "Savings",
        "savings",
        None,
        [
            ("savings.emergency", "Emergency fund", None),
            ("savings.retirement", "Retirement", None),
            ("savings.investing", "Investing", None),
            ("savings.education", "Education", None),
        ],
    ),
    # A loan payment counts in a budget by these parts (S1.9.7), principal as saved.
    (
        "loans",
        "Loan payments",
        "expense",
        None,
        [
            ("loans.interest", "Interest", "loan-interest"),
            ("loans.escrow", "Escrow", None),
            ("loans.pmi", "PMI", None),
            ("loans.fees", "Fees", None),
            ("loans.principal", "Principal", None, "savings"),
        ],
    ),
    (
        "transfer",
        "Transfers",
        "transfer",
        None,
        [
            ("transfer.card", "Credit card payment", None),
            ("transfer.savings", "To savings", None),
            ("transfer.loan", "Loan principal", None),
        ],
    ),
]
