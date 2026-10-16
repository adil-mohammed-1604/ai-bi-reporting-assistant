"""Generate a synthetic retail transactions dataset (no real customer data).

Includes deliberate data-quality problems so the quality engine has work to do:
missing descriptions/customer IDs, cancellations (C-prefixed invoices, negative
quantity), invalid dates, non-numeric prices, negative prices, exact duplicate rows.

Usage: python data/generate_sample_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
OUT_DIR = Path(__file__).parent

PRODUCTS = [
    ("P1001", "CERAMIC MUG BLUE", 4.50), ("P1002", "GLASS TEA LIGHT SET", 6.25),
    ("P1003", "WOODEN CHOPPING BOARD", 12.90), ("P1004", "COTTON TOTE BAG", 3.75),
    ("P1005", "SCENTED CANDLE LAVENDER", 8.40), ("P1006", "NOTEBOOK A5 DOTTED", 5.10),
    ("P1007", "STAINLESS WATER BOTTLE", 14.20), ("P1008", "DESK LAMP LED", 24.99),
    ("P1009", "KNITTED THROW BLANKET", 29.50), ("P1010", "WALL CLOCK MINIMAL", 18.75),
    ("P1011", "PLANT POT TERRACOTTA", 7.30), ("P1012", "PICTURE FRAME OAK", 11.60),
]
COUNTRIES = ["United Kingdom", "France", "Germany", "Spain", "Netherlands", "Ireland", "Canada"]
COUNTRY_P = [0.55, 0.10, 0.10, 0.07, 0.07, 0.06, 0.05]


def generate(n_invoices: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    start = pd.Timestamp("2025-01-01")
    rows = []
    for i in range(n_invoices):
        inv = f"{540000 + i}"
        ts = start + pd.Timedelta(days=int(rng.integers(0, 365)),
                                  hours=int(rng.integers(8, 19)),
                                  minutes=int(rng.integers(0, 60)))
        cust = f"C{int(rng.integers(10000, 10400))}"
        country = rng.choice(COUNTRIES, p=COUNTRY_P)
        for p in rng.choice(len(PRODUCTS), size=int(rng.integers(1, 6)), replace=False):
            code, desc, price = PRODUCTS[p]
            rows.append([inv, code, desc, int(rng.integers(1, 13)), ts, price, cust, country])

    df = pd.DataFrame(rows, columns=["InvoiceNo", "StockCode", "Description", "Quantity",
                                     "InvoiceDate", "UnitPrice", "CustomerID", "Country"])

    # Cancellations: ~3% of invoices become C-prefixed with negative quantity
    cancel_inv = rng.choice(df["InvoiceNo"].unique(), size=int(0.03 * n_invoices), replace=False)
    m = df["InvoiceNo"].isin(cancel_inv)
    df.loc[m, "InvoiceNo"] = "C" + df.loc[m, "InvoiceNo"]
    df.loc[m, "Quantity"] = -df.loc[m, "Quantity"]

    # Missing customer IDs / descriptions
    df.loc[df.sample(frac=0.08, random_state=1).index, "CustomerID"] = np.nan
    df.loc[df.sample(frac=0.01, random_state=2).index, "Description"] = np.nan

    # Convert dates to strings so we can inject invalid ones
    df["InvoiceDate"] = df["InvoiceDate"].dt.strftime("%Y-%m-%d %H:%M:%S")
    bad_dates = df.sample(n=6, random_state=3).index
    df.loc[bad_dates, "InvoiceDate"] = ["not a date", "2025-13-45 10:00:00", "", "32/01/2025",
                                        "yesterday", "2025-02-30 09:00:00"]

    # Bad prices
    df["UnitPrice"] = df["UnitPrice"].astype(object)
    idx = df.sample(n=5, random_state=4).index
    df.loc[idx[:3], "UnitPrice"] = ["abc", "N/A", "12,5x"]
    df.loc[idx[3:], "UnitPrice"] = [-4.5, -1.0]

    # Zero quantity
    df.loc[df.sample(n=3, random_state=5).index, "Quantity"] = 0

    # Exact duplicate rows
    df = pd.concat([df, df.sample(n=15, random_state=6)], ignore_index=True)
    return df.sample(frac=1, random_state=7).reset_index(drop=True)


if __name__ == "__main__":
    df = generate()
    df.to_csv(OUT_DIR / "sample_retail_transactions.csv", index=False)
    df.to_excel(OUT_DIR / "sample_retail_transactions.xlsx", index=False)
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
