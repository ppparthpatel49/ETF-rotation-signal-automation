"""
NIFTYBEES / GOLDBEES Donchian Ratio Rotation — LIVE SIGNAL
=========================================================
Pulls the last ~45 trading days from yfinance and prints the current
position recommendation using the exact same logic as the backtest:

    Ratio = NIFTYBEES Close / GOLDBEES Close
    20-day Donchian on the PREVIOUS 20 days (shift(1) -> zero look-ahead)
        Ratio > prev 20d High -> Buy NIFTYBEES
        Ratio < prev 20d Low  -> Buy GOLDBEES
        else                  -> Hold current position

Execution note: signal is locked at today's EOD close; you act on the
NEXT trading day (your 9:20 AM CNC rule). Run this AFTER market close.

Usage:
    python live_signal.py                 # uses last known position from state file
    python live_signal.py --position GOLD # override current holding
    python live_signal.py --days 60       # pull more history
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run:  pip install yfinance")

DONCHIAN = 20
NIFTY_TICKER = "NIFTYBEES.NS"
GOLD_TICKER = "GOLDBEES.NS"
STATE_FILE = "position_state.json"


# ----------------------------------------------------------------- helpers
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"position": None, "since": None, "last_signal_date": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch(days):
    """Download daily Close for both ETFs, aligned on common trading days."""
    # period must comfortably exceed DONCHIAN+1; pad for holidays
    period = f"{max(days, DONCHIAN + 10) + 20}d"
    raw = yf.download(
        [NIFTY_TICKER, GOLD_TICKER],
        period=period,
        progress=False,
        auto_adjust=False,
    )
    close = raw["Close"].copy()
    # drop rows where either is missing or volume-less placeholder (NaN)
    close = close.dropna()
    # Some yfinance rows can be a non-trading "carry" with 0 volume; keep only
    # rows that actually moved or have valid data — dropna above is enough here.
    close = close.rename(columns={NIFTY_TICKER: "NIFTY", GOLD_TICKER: "GOLD"})
    return close[["NIFTY", "GOLD"]].sort_index()


def compute(df):
    df = df.copy()
    df["Ratio"] = df["NIFTY"] / df["GOLD"]
    # Donchian on PREVIOUS 20 days (exclude today -> no look-ahead)
    df["Up"] = df["Ratio"].rolling(DONCHIAN).max().shift(1)
    df["Dn"] = df["Ratio"].rolling(DONCHIAN).min().shift(1)
    sig = np.where(df["Ratio"] > df["Up"], "NIFTY",
          np.where(df["Ratio"] < df["Dn"], "GOLD", None))
    df["Signal"] = pd.Series(sig, index=df.index, dtype="object")
    df["Target"] = df["Signal"].ffill()
    return df


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--position", choices=["NIFTY", "GOLD"], default=None,
                    help="Override your current holding (otherwise read from state file).")
    ap.add_argument("--days", type=int, default=45,
                    help="Approx number of trading days of history to fetch.")
    args = ap.parse_args()

    state = load_state()
    current = args.position or state.get("position")

    print("Fetching live data from yfinance ...")
    df = fetch(args.days)
    if len(df) < DONCHIAN + 1:
        sys.exit(f"Not enough data: only {len(df)} usable trading days "
                 f"(need >= {DONCHIAN + 1}).")

    d = compute(df)
    last = d.iloc[-1]
    asof = d.index[-1].date()

    ratio = last["Ratio"]
    up = last["Up"]
    dn = last["Dn"]
    raw_signal = last["Signal"]          # NIFTY / GOLD / None (breakout today?)
    target = last["Target"]             # what the strategy says to hold now

    # Decide action vs current holding
    if target is None:
        # No breakout has ever happened in this short window AND no prior position
        decision = "NO SIGNAL YET (no breakout in available history)"
        action = "STAY IN CASH / keep current holding"
        to_hold = current or "—"
    else:
        to_hold = target
        if current is None:
            action = f"ENTER {to_hold}  (first position)"
            decision = "BUY"
        elif current == to_hold:
            action = f"HOLD {to_hold}  (no change)"
            decision = "HOLD"
        else:
            action = f"SWITCH: SELL {current}  ->  BUY {to_hold}"
            decision = "SWITCH"

    # Distance to the bands (how close to flipping)
    dist_to_up = (up / ratio - 1) * 100 if pd.notna(up) else np.nan
    dist_to_dn = (1 - dn / ratio) * 100 if pd.notna(dn) else np.nan

    # ------------------------------------------------------------- print
    line = "=" * 64
    print("\n" + line)
    print(f"  NIFTYBEES / GOLDBEES  DONCHIAN ROTATION  —  LIVE SIGNAL")
    print(line)
    print(f"  Data as of close      : {asof}")
    print(f"  NIFTYBEES close        : {last['NIFTY']:.2f}")
    print(f"  GOLDBEES  close        : {last['GOLD']:.2f}")
    print(f"  Ratio (today)          : {ratio:.4f}")
    print(f"  Prev 20d High (Up band): {up:.4f}")
    print(f"  Prev 20d Low  (Dn band): {dn:.4f}")
    print(line)
    print(f"  Breakout today?        : "
          f"{'YES -> ' + raw_signal if raw_signal else 'No (inside channel)'}")
    print(f"  Strategy target hold   : {to_hold}")
    print(f"  Your current holding   : {current or 'unknown / none'}")
    print(line)
    print(f"  >>> DECISION: {decision}")
    print(f"  >>> ACTION  : {action}")
    print(f"      (Lock at today's close; execute next trading day ~9:20 AM, CNC)")
    print(line)
    if pd.notna(dist_to_up) and pd.notna(dist_to_dn):
        print(f"  Ratio is {dist_to_up:+.2f}% below the upper band "
              f"and {dist_to_dn:+.2f}% above the lower band.")
    print(line)

    # Show last 10 days for context
    tail = d.tail(10)[["NIFTY", "GOLD", "Ratio", "Up", "Dn", "Target"]].copy()
    tail.index = [i.date() for i in tail.index]
    pd.set_option("display.width", 120)
    print("\n  Last 10 trading days:")
    print(tail.round(4).to_string())

    # ------------------------------------------------------------- save state
    state["position"] = to_hold if target is not None else current
    if target is not None and current != to_hold:
        state["since"] = str(asof)
    state["last_signal_date"] = str(asof)
    save_state(state)
    print(f"\n  State saved to {STATE_FILE} (position={state['position']}, "
          f"since={state['since']}).")


if __name__ == "__main__":
    main()
