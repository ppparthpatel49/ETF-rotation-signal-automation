"""
NIFTYBEES / GOLDBEES Donchian Rotation — AUTOMATED DAILY SIGNAL
==============================================================
Designed to run on GitHub Actions (or any cron). Each run:

  1. Pulls last ~65 trading days from yfinance.
  2. Computes the Donchian ratio signal (zero look-ahead, same as backtest).
  3. Decides HOLD / SWITCH / ENTER vs the last saved position.
  4. Appends a row to signal_log.csv  (committed back to the repo = your GitHub log).
  5. Sends an email (SMTP) and/or a Telegram alert.

Position memory lives in position_state.json (committed to the repo).

CONFIG via environment variables (set as GitHub Secrets):
  ALERT_MODE        : "always" (default) or "switch_only"
  # Email (optional)
  EMAIL_ENABLED     : "true" / "false"
  SMTP_HOST         : e.g. smtp.gmail.com
  SMTP_PORT         : e.g. 587
  SMTP_USER         : your email / SMTP username
  SMTP_PASS         : SMTP password or app-password
  EMAIL_TO          : recipient (comma separated allowed)
  # Telegram (optional)
  TELEGRAM_ENABLED  : "true" / "false"
  TELEGRAM_BOT_TOKEN: from @BotFather
  TELEGRAM_CHAT_ID  : your chat id
"""

import os
import sys
import json
import smtplib
import ssl
from email.mime.text import MIMEText
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import urllib.request
import urllib.parse

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")


# Optional: load a local .env file for testing (ignored on GitHub Actions).
def _load_dotenv():
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                # strip inline comments and quotes
                v = v.split("#", 1)[0].strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)


_load_dotenv()

# ----------------------------------------------------------------- constants
DONCHIAN = 20
NIFTY_TICKER = "NIFTYBEES.NS"
GOLD_TICKER = "GOLDBEES.NS"
STATE_FILE = "position_state.json"
LOG_FILE = "signal_log.csv"


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_bool(name, default=False):
    v = env(name, str(default)).lower()
    return v in ("1", "true", "yes", "y", "on")


# ----------------------------------------------------------------- data + logic
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"position": None, "since": None, "last_signal_date": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch():
    period = f"{DONCHIAN + 45}d"
    raw = yf.download(
        [NIFTY_TICKER, GOLD_TICKER],
        period=period, progress=False, auto_adjust=False,
    )
    close = raw["Close"].dropna().rename(
        columns={NIFTY_TICKER: "NIFTY", GOLD_TICKER: "GOLD"})
    return close[["NIFTY", "GOLD"]].sort_index()


def compute(df):
    df = df.copy()
    df["Ratio"] = df["NIFTY"] / df["GOLD"]
    df["Up"] = df["Ratio"].rolling(DONCHIAN).max().shift(1)   # prev 20d high
    df["Dn"] = df["Ratio"].rolling(DONCHIAN).min().shift(1)   # prev 20d low
    sig = np.where(df["Ratio"] > df["Up"], "NIFTY",
          np.where(df["Ratio"] < df["Dn"], "GOLD", None))
    df["Signal"] = pd.Series(sig, index=df.index, dtype="object")
    df["Target"] = df["Signal"].ffill()
    return df


# ----------------------------------------------------------------- notifiers
def send_email(subject, body):
    if not env_bool("EMAIL_ENABLED"):
        return "email disabled"
    host = env("SMTP_HOST"); port = int(env("SMTP_PORT", "587"))
    user = env("SMTP_USER"); pw = env("SMTP_PASS")
    to = env("EMAIL_TO") or user
    if not (host and user and pw and to):
        return "email misconfigured (missing host/user/pass/to)"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx) as s:
                s.login(user, pw)
                s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
        else:
            with smtplib.SMTP(host, port) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
        return "email sent"
    except Exception as e:
        return f"email FAILED: {e}"


def send_telegram(text):
    if not env_bool("TELEGRAM_ENABLED"):
        return "telegram disabled"
    token = env("TELEGRAM_BOT_TOKEN"); chat = env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return "telegram misconfigured (missing token/chat id)"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            r.read()
        return "telegram sent"
    except Exception as e:
        return f"telegram FAILED: {e}"


# ----------------------------------------------------------------- main
def main():
    state = load_state()
    current = state.get("position")

    print("Fetching data from yfinance ...")
    df = fetch()
    if len(df) < DONCHIAN + 1:
        sys.exit(f"Not enough data: {len(df)} rows (need >= {DONCHIAN + 1}).")

    d = compute(df)
    last = d.iloc[-1]
    asof = str(d.index[-1].date())

    ratio = float(last["Ratio"]); up = float(last["Up"]); dn = float(last["Dn"])
    raw_signal = last["Signal"]
    target = last["Target"]

    # ---- decision vs current holding
    if target is None:
        decision, action, to_hold = "NO_SIGNAL", "Stay in cash (no breakout yet)", current
    else:
        to_hold = target
        if current is None:
            decision, action = "ENTER", f"ENTER {to_hold} (first position)"
        elif current == to_hold:
            decision, action = "HOLD", f"HOLD {to_hold} (no change)"
        else:
            decision, action = "SWITCH", f"SELL {current} -> BUY {to_hold}"

    dist_up = (up / ratio - 1) * 100 if up == up else float("nan")
    dist_dn = (1 - dn / ratio) * 100 if dn == dn else float("nan")

    # ---- duplicate-run guard: skip alerts if we already processed this date
    already_done = state.get("last_signal_date") == asof
    emoji = {"SWITCH": "\U0001F501", "ENTER": "\U0001F7E2",
             "HOLD": "\u2705", "NO_SIGNAL": "\u26AA"}.get(decision, "\u2139")

    subject = f"[ETF Rotation] {decision}: {action}  ({asof})"
    body = (
        f"NIFTYBEES / GOLDBEES Donchian Rotation Signal\n"
        f"Data as of close : {asof}\n"
        f"--------------------------------------------\n"
        f"NIFTYBEES close  : {last['NIFTY']:.2f}\n"
        f"GOLDBEES  close  : {last['GOLD']:.2f}\n"
        f"Ratio            : {ratio:.4f}\n"
        f"Prev 20d High    : {up:.4f}\n"
        f"Prev 20d Low     : {dn:.4f}\n"
        f"Breakout today   : {raw_signal or 'No (inside channel)'}\n"
        f"--------------------------------------------\n"
        f"Current holding  : {current or 'none'}\n"
        f"Target holding   : {to_hold or 'none'}\n"
        f"DECISION         : {decision}\n"
        f"ACTION           : {action}\n"
        f"(Lock at close; execute next trading day ~9:20 AM, CNC)\n"
        f"--------------------------------------------\n"
        f"Ratio is {dist_up:+.2f}% from upper band, {dist_dn:+.2f}% from lower band.\n"
    )

    tg = (
        f"{emoji} <b>ETF Rotation Signal</b> ({asof})\n"
        f"<b>{decision}</b>: {action}\n\n"
        f"NIFTYBEES: {last['NIFTY']:.2f} | GOLDBEES: {last['GOLD']:.2f}\n"
        f"Ratio: <b>{ratio:.4f}</b>\n"
        f"Bands: {dn:.4f} (low) … {up:.4f} (high)\n"
        f"Hold: <b>{to_hold or 'none'}</b> "
        f"(was {current or 'none'})\n"
        f"<i>Execute next trading day ~9:20 AM, CNC</i>"
    )

    print("\n" + body)

    # ---- append to CSV log (your GitHub-committed record)
    row = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_date": asof,
        "nifty_close": round(float(last["NIFTY"]), 4),
        "gold_close": round(float(last["GOLD"]), 4),
        "ratio": round(ratio, 6),
        "up_band": round(up, 6),
        "dn_band": round(dn, 6),
        "breakout": raw_signal or "",
        "prev_position": current or "",
        "target_position": to_hold or "",
        "decision": decision,
        "action": action,
    }
    header = list(row.keys())
    new_file = not os.path.exists(LOG_FILE)
    # avoid duplicate log rows for the same data_date
    write_log = True
    if not new_file:
        try:
            existing = pd.read_csv(LOG_FILE)
            if (existing["data_date"].astype(str) == asof).any():
                write_log = False
        except Exception:
            pass
    if write_log:
        pd.DataFrame([row], columns=header).to_csv(
            LOG_FILE, mode="a", header=new_file, index=False)
        print(f"Logged to {LOG_FILE}")
    else:
        print(f"{LOG_FILE} already has a row for {asof} — not duplicating.")

    # ---- alerts
    mode = env("ALERT_MODE", "always").lower()
    should_alert = True
    if mode == "switch_only" and decision not in ("SWITCH", "ENTER"):
        should_alert = False
    if already_done:
        should_alert = False
        print("Already processed this date previously — skipping alerts.")

    if should_alert:
        print("Email :", send_email(subject, body))
        print("Telegram:", send_telegram(tg))
    else:
        print("Alerts skipped (mode/duplicate).")

    # ---- save state
    state["position"] = to_hold if target is not None else current
    if target is not None and current != to_hold:
        state["since"] = asof
    state["last_signal_date"] = asof
    save_state(state)
    print(f"State saved: position={state['position']} since={state['since']}")


if __name__ == "__main__":
    main()
