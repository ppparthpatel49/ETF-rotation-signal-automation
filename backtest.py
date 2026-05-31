"""
NIFTYBEES / GOLDBEES Donchian Ratio Rotation Backtest
======================================================
Indicator : Daily Ratio = NIFTYBEES Close / GOLDBEES Close
Channel   : 20-day Donchian (uses PREVIOUS 20 days only -> zero look-ahead)
Signals   :
    Ratio > prev 20d High -> Buy NIFTYBEES
    Ratio < prev 20d Low  -> Buy GOLDBEES
    else                  -> Hold current position
Execution : Signal locked at EOD close. Position assumed entered the NEXT
            trading day; daily strategy return = next-day close-to-close
            return of the held ETF (CNC / delivery, no leverage).
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DONCHIAN = 20
INITIAL_CAPITAL = 100_000.0

# ---------------------------------------------------------------- load data
def load(path, name):
    # yfinance multi-index style: row0 header, row1 ticker, row2 'Date' label
    df = pd.read_csv(path, skiprows=3, header=None,
                     names=["Date", "Close", "High", "Low", "Open", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df[["Close"]].rename(columns={"Close": name})

nifty = load("uploads/NIFTYBEES.NS.csv", "NIFTY")
gold  = load("uploads/GOLDBEES.NS.csv",  "GOLD")

df = nifty.join(gold, how="inner").dropna()
print(f"Data range: {df.index.min().date()} -> {df.index.max().date()}  ({len(df)} trading days)")

# ---------------------------------------------------------------- indicator
df["Ratio"] = df["NIFTY"] / df["GOLD"]

# Previous 20-day Donchian (shift(1) => excludes today => no look-ahead)
df["Up"]  = df["Ratio"].rolling(DONCHIAN).max().shift(1)
df["Dn"]  = df["Ratio"].rolling(DONCHIAN).min().shift(1)

# ---------------------------------------------------------------- signals
# Raw breakout signal each day (NaN where no breakout)
sig = np.where(df["Ratio"] > df["Up"], "NIFTY",
      np.where(df["Ratio"] < df["Dn"], "GOLD", None))
df["Signal"] = pd.Series(sig, index=df.index, dtype="object")

# Target position = forward-fill last breakout (hold otherwise)
df["Target"] = pd.Series(df["Signal"], index=df.index).ffill()

# ---------------------------------------------------------------- execution
# Daily returns of each ETF
df["RetN"] = df["NIFTY"].pct_change()
df["RetG"] = df["GOLD"].pct_change()

# Position decided at EOD today is held over NEXT day -> shift target by 1
df["Held"] = df["Target"].shift(1)

# Strategy daily return = next-day return of the held asset
df["StratRet"] = np.where(df["Held"] == "NIFTY", df["RetN"],
                  np.where(df["Held"] == "GOLD",  df["RetG"], 0.0))

# Only trade once we actually have a position (post warm-up)
df.loc[df["Held"].isna(), "StratRet"] = 0.0

# ---------------------------------------------------------------- equity curves
df["StratEq"] = INITIAL_CAPITAL * (1 + df["StratRet"]).cumprod()
df["NiftyEq"] = INITIAL_CAPITAL * (1 + df["RetN"].fillna(0)).cumprod()
df["GoldEq"]  = INITIAL_CAPITAL * (1 + df["RetG"].fillna(0)).cumprod()
# 50/50 daily-rebalanced benchmark
df["BalEq"]   = INITIAL_CAPITAL * (1 + 0.5*df["RetN"].fillna(0) + 0.5*df["RetG"].fillna(0)).cumprod()

# count trades (switches in held asset)
switches = (df["Target"] != df["Target"].shift(1)) & df["Target"].notna()
n_trades = int(switches.sum())

# ---------------------------------------------------------------- metrics
def metrics(eq, ret, label):
    eq = eq.dropna()
    ret = ret.dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/yrs) - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = (ret.mean() * 252) / (ret.std() * np.sqrt(252)) if ret.std() > 0 else np.nan
    dd = eq / eq.cummax() - 1
    maxdd = dd.min()
    # downside / sortino
    downside = ret[ret < 0].std() * np.sqrt(252)
    sortino = (ret.mean() * 252) / downside if downside > 0 else np.nan
    win = (ret > 0).mean()
    return dict(label=label, total=total, cagr=cagr, vol=vol, sharpe=sharpe,
                sortino=sortino, maxdd=maxdd, win=win, final=eq.iloc[-1])

# evaluate strategy over period where it is active
active = df[df["Held"].notna()]
res = [
    metrics(active["StratEq"], active["StratRet"], "Strategy (Donchian Rotation)"),
    metrics(df["NiftyEq"], df["RetN"], "Buy & Hold NIFTYBEES"),
    metrics(df["GoldEq"], df["RetG"], "Buy & Hold GOLDBEES"),
    metrics(df["BalEq"], 0.5*df["RetN"].fillna(0)+0.5*df["RetG"].fillna(0), "50/50 Rebalanced"),
]

# ---------------------------------------------------------------- report
print("\n" + "="*78)
print("BACKTEST RESULTS")
print("="*78)
hdr = f"{'Strategy':<32}{'Total':>9}{'CAGR':>8}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}{'Win%':>7}"
print(hdr); print("-"*78)
for r in res:
    print(f"{r['label']:<32}{r['total']*100:>8.1f}%{r['cagr']*100:>7.1f}%"
          f"{r['vol']*100:>7.1f}%{r['sharpe']:>8.2f}{r['maxdd']*100:>8.1f}%{r['win']*100:>6.1f}%")
print("-"*78)
print(f"Number of switches (trades): {n_trades}")
print(f"Time in NIFTYBEES: {(active['Held']=='NIFTY').mean()*100:.1f}%   "
      f"Time in GOLDBEES: {(active['Held']=='GOLD').mean()*100:.1f}%")
print(f"Strategy final value (start Rs {INITIAL_CAPITAL:,.0f}): Rs {active['StratEq'].iloc[-1]:,.0f}")

# ---------------------------------------------------------------- trade log
trades = df[switches].copy()
trade_log = pd.DataFrame({
    "Date": trades.index,
    "SwitchTo": trades["Target"].values,
    "Ratio": trades["Ratio"].round(4).values,
    "Up(20)": trades["Up"].round(4).values,
    "Dn(20)": trades["Dn"].round(4).values,
})
trade_log.to_csv("trade_log.csv", index=False)
print(f"\nTrade log saved -> trade_log.csv ({len(trade_log)} switches)")
print(trade_log.head(12).to_string(index=False))

# full daily output
df.to_csv("backtest_daily.csv")

# ---------------------------------------------------------------- plots
fig, axes = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={"height_ratios":[2,1]})

ax = axes[0]
ax.plot(df.index, df["StratEq"], label="Donchian Rotation", lw=2, color="#1f77b4")
ax.plot(df.index, df["NiftyEq"], label="Buy & Hold NIFTYBEES", lw=1.2, color="#2ca02c", alpha=.8)
ax.plot(df.index, df["GoldEq"], label="Buy & Hold GOLDBEES", lw=1.2, color="#d4af37", alpha=.8)
ax.plot(df.index, df["BalEq"], label="50/50 Rebalanced", lw=1.0, color="grey", ls="--", alpha=.7)
ax.set_yscale("log")
ax.set_title("Equity Curve (log scale) — Start ₹100,000", fontsize=13, weight="bold")
ax.set_ylabel("Portfolio Value (₹)")
ax.legend(loc="upper left"); ax.grid(alpha=.3)

ax2 = axes[1]
ax2.plot(df.index, df["Ratio"], color="black", lw=.9, label="NIFTY/GOLD Ratio")
ax2.plot(df.index, df["Up"], color="green", lw=.7, ls="--", alpha=.6, label="Prev 20d High")
ax2.plot(df.index, df["Dn"], color="red", lw=.7, ls="--", alpha=.6, label="Prev 20d Low")
# shade held asset
nifty_mask = df["Held"]=="NIFTY"
ax2.fill_between(df.index, df["Ratio"].min(), df["Ratio"].max(),
                 where=nifty_mask, color="green", alpha=.06)
ax2.set_title("Ratio vs Donchian Channel (green shade = holding NIFTYBEES)", fontsize=11)
ax2.set_ylabel("Ratio"); ax2.legend(loc="upper left", fontsize=8); ax2.grid(alpha=.3)

plt.tight_layout()
plt.savefig("backtest_chart.png", dpi=120)
print("\nChart saved -> backtest_chart.png")
