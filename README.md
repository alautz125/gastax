# BPC Gas Tax Calculator

An interactive calculator showing how the war in Iran has increased fill-up costs — and how much a federal gas tax holiday would save at the pump.

**Live tool:** `https://[your-org].github.io/[repo-name]/gas-tax-calculator.html`

---

## Files

| File | Purpose |
|---|---|
| `gas-tax-calculator.html` | The interactive calculator (self-contained, no build step) |
| `update_gas_prices.py` | Python script that fetches daily AAA prices and updates the HTML |
| `.github/workflows/update-gas-prices.yml` | GitHub Action — runs the updater every day at 8 AM ET |

---

## Setup (one time)

### 1. Create the GitHub repo

Create a new **public** repo on GitHub (e.g., `bpc-gas-calculator`). Upload all files, preserving the `.github/workflows/` folder structure.

```
bpc-gas-calculator/
├── gas-tax-calculator.html
├── update_gas_prices.py
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── update-gas-prices.yml
```

### 2. Enable GitHub Pages

Go to **Settings → Pages** and set:
- **Source:** Deploy from a branch
- **Branch:** `main` / `(root)`

Your live URL will be: `https://[your-org].github.io/[repo-name]/gas-tax-calculator.html`

### 3. Give the workflow write permission

Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**. This lets the Action commit the updated HTML back to the repo.

### 4. Run it manually to confirm it works

Go to **Actions → Update Gas Prices → Run workflow**. It should fetch today's AAA prices, update the HTML, and commit. After ~30 seconds, your GitHub Pages URL will reflect the new prices.

---

## How it works

Every day at 8 AM ET, GitHub runs `update_gas_prices.py`, which:

1. Fetches `https://gasprices.aaa.com/state-gas-price-averages/`
2. Parses all 51 state/D.C. prices (Regular, Mid-Grade, Premium, Diesel)
3. Replaces the data block in `gas-tax-calculator.html` between these sentinel comments:
   ```
   // ==BPC_PRICES_TODAY_START==
   ...
   // ==BPC_PRICES_TODAY_END==
   ```
4. Commits and pushes the updated file if prices changed

The pre-war baseline (Feb. 26, 2026) is in a separate `PRICES_PREWAR` block and is **never touched** by the updater.

---

## Data sources

- **Current prices:** [AAA State Gas Price Averages](https://gasprices.aaa.com/state-gas-price-averages/) (updated daily)
- **Pre-war baseline:** AAA prices on Feb. 26, 2026 via Wayback Machine (two days before the conflict in Iran began)
- **Tank sizes:** [Edmunds](https://www.edmunds.com/car-maintenance/how-many-gallons-of-gas-does-car-hold.html)
- **Federal gas tax:** $0.184/gallon (gas), $0.244/gallon (diesel)
- **Pass-through rates:** [Wharton Budget Model](https://budgetmodel.wharton.upenn.edu/p/2022-06-15-effects-of-a-state-gasoline-tax-holiday/)

Analysis by the [Bipartisan Policy Center](https://bipartisanpolicy.org).
