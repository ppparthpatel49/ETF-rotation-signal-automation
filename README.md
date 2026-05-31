# NIFTYBEES / GOLDBEES Donchian Rotation — Automated Daily Signal

Automatically generates a daily **HOLD / SWITCH / ENTER** signal for rotating
between **NIFTYBEES** and **GOLDBEES** based on a 20-day Donchian channel of the
price ratio, then:

- 📧 emails you the signal,
- 💬 sends a Telegram alert,
- 📈 appends every day to `signal_log.csv` (committed to this repo = your history).

It runs **100% free on GitHub Actions** — no server, no PC needs to stay on.

---

## The strategy (recap)

```
Ratio = NIFTYBEES Close / GOLDBEES Close
20-day Donchian on the PREVIOUS 20 days (no look-ahead):
    Ratio > prev 20-day High  -> Buy NIFTYBEES
    Ratio < prev 20-day Low    -> Buy GOLDBEES
    otherwise                  -> Hold current position
Execute the next trading day (~9:20 AM, CNC/delivery).
```

---

## Files

| File | Purpose |
|---|---|
| `run_signal.py` | Main script: fetch data → signal → log → email/telegram |
| `live_signal.py` | Manual one-off check (prints a detailed report to terminal) |
| `backtest.py` | The original backtest |
| `.github/workflows/daily-signal.yml` | Scheduler (runs every weekday after close) |
| `requirements.txt` | Python dependencies |
| `signal_log.csv` | Daily history (auto-created & committed) |
| `position_state.json` | Remembers your current holding (auto-committed) |
| `.env.example` | Template for local testing |

---

## Setup — Step by Step

### 1) Put this project on GitHub
```bash
git init
git add .
git commit -m "ETF rotation signal automation"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO>.git
git push -u origin main
```
> A **private repo** is fine and recommended (your log stays private).

### 2) Set your starting position (important!)
The bot needs to know what you hold today. Edit `position_state.json`:
```json
{ "position": "GOLD", "since": "2026-05-29", "last_signal_date": null }
```
Use `"GOLD"`, `"NIFTY"`, or `null` if you currently hold neither. Commit it.
> Leave `last_signal_date` as `null` so the first run isn't skipped as a duplicate.

### 3) Choose alert mode (optional)
In your repo: **Settings → Secrets and variables → Actions → Variables tab → New variable**
- `ALERT_MODE` = `always` (alert every day) **or** `switch_only` (alert only when it tells you to switch/enter).

---

## Option A — Telegram alerts (easiest, recommended)

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
2. Send any message to your new bot (so it's allowed to message you).
3. Get your **chat id**: open this URL in a browser (replace token):
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Look for `"chat":{"id":123456789 ...}` → that number is your chat id.
4. In GitHub repo **Settings → Secrets and variables → Actions**:
   - **Variables** tab: add `TELEGRAM_ENABLED` = `true`
   - **Secrets** tab: add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`

---

## Option B — Email alerts (Gmail example)

1. Enable **2-Step Verification** on your Google account.
2. Create an **App Password**: Google Account → Security → App passwords → generate one (16 chars).
3. In GitHub repo **Settings → Secrets and variables → Actions**:
   - **Variables** tab: add `EMAIL_ENABLED` = `true`
   - **Secrets** tab:
     - `SMTP_HOST` = `smtp.gmail.com`
     - `SMTP_PORT` = `587`
     - `SMTP_USER` = `youremail@gmail.com`
     - `SMTP_PASS` = the 16-char **app password** (not your normal password)
     - `EMAIL_TO`  = where to send (can be the same email; comma-separate for multiple)

> Other providers work too — just change `SMTP_HOST`/`SMTP_PORT`.
> Outlook: `smtp.office365.com` / `587`.

You can enable **both** Telegram and Email, or just one.

---

## 4) Turn it on
- Go to the **Actions** tab in your repo → enable workflows if prompted.
- Click **Daily ETF Rotation Signal → Run workflow** to test it immediately.
- After it runs, check:
  - your Telegram / email for the alert,
  - `signal_log.csv` in the repo for a new row,
  - `position_state.json` updated.

The schedule (`.github/workflows/daily-signal.yml`) is set to **10:30 UTC = 16:00 IST**,
every weekday (after NSE close). Edit the `cron:` line to change the time.

---

## Test locally first (optional)
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in your values
python run_signal.py          # runs signal, logs CSV, sends alerts if enabled
# or a detailed one-off report without sending alerts:
python live_signal.py
```

---

## How the CSV log looks
```
run_utc,data_date,nifty_close,gold_close,ratio,up_band,dn_band,breakout,prev_position,target_position,decision,action
2026-05-31T08:05:52+00:00,2026-05-29,267.78,128.65,2.081461,2.231737,2.014878,,,GOLD,ENTER,ENTER GOLD (first position)
```
Each weekday adds one row. Because the Action commits it back, your full
history is permanently stored and version-controlled in GitHub.

---

## Important notes & caveats

- **Holidays:** GitHub cron still fires on NSE holidays, but the script just
  re-logs the last available close. The duplicate-guard prevents repeat rows /
  repeat alerts for the same `data_date`, so you won't get spammed.
- **Data source:** yfinance is free but unofficial; occasionally a stale/zero-volume
  row appears near the latest date. For real money, confirm against your broker's
  official close before trading.
- **Timing:** Signal is on the **close**; you act the **next morning** (your 9:20 AM
  CNC rule). Don't act intraday on the same day's forming ratio.
- **This is not financial advice.** The backtest showed the strategy underperformed
  simply buy-and-holding GOLDBEES over 2021–2026 and had a lower Sharpe than a
  50/50 rebalance. Use position sizing and your own judgment.
- **Secrets safety:** never commit `.env` or tokens. Use GitHub Secrets. `.gitignore`
  already excludes `.env`.
