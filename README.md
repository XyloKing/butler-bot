# 🫡 Butler Bot

Personal Telegram assistant built for night-shift healthcare workers with ADHD.
Tracks bills, partner dates, car maintenance, professional credentials, medications,
and nags you until things get done.

**Button-first design** — you barely have to type. Just tap.

## Features

- 📅 **Today / Tonight** — shift-aware daily summary
- 📆 **Week View** — ASCII calendar with all events
- 💸 **Money & Bills** — payday-centered, aggressive nag-until-paid
- 💜 **People & Dates** — partner tracking, birthdays, date scheduling
- 🚗 **Car / Admin** — oil, inspection, registration countdowns
- 🎓 **Credentials** — license numbers, expiry dates, CEU tracking
- 💊 **Medications** — daily check-ins, nags every 2 hours until confirmed
- 📒 **Notes** — quick capture, attachable to any item
- ➕ **Capture / Inbox** — one-tap add anything
- 🔔 **Auto Reminders** — afternoon digest, evening check-in, weekly summary

## Quick Start

### 1. Create Your Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Follow prompts — give it a name and username
4. Copy the **bot token** it gives you

### 2. Deploy on Railway

**Option A — No GitHub needed (easiest):**

1. Install the [Railway CLI](https://docs.railway.app/guides/cli):
   ```bash
   npm i -g @railway/cli
   # or: brew install railway
   ```
2. Log in and create a project:
   ```bash
   railway login
   cd butler-bot
   railway init
   ```
3. Set your bot token:
   ```bash
   railway variables set TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
   ```
4. Deploy:
   ```bash
   railway up
   ```
5. That's it. Railway detects the Dockerfile and runs the bot.

**Option B — Via GitHub:**

1. Go to [railway.app](https://railway.app) and sign up
2. Push this folder to a GitHub repo:
   ```bash
   cd butler-bot
   git init && git add . && git commit -m "Initial butler bot"
   git remote add origin https://github.com/YOUR_USERNAME/butler-bot.git
   git push -u origin main
   ```
3. In Railway: **New Project** → **Deploy from GitHub Repo** → select your repo
4. Add environment variable: `TELEGRAM_BOT_TOKEN` = your bot token
5. Railway auto-deploys on every push

### 3. Start Using It

1. Open your bot in Telegram
2. Send `/start`
3. Follow the onboarding questionnaire (all buttons, barely any typing)
4. Send `/menu` anytime to access everything

## How It Works

### Only 2 Commands
- `/start` — first time setup / onboarding
- `/menu` — your home screen

Everything else is **buttons**. The bot sends you inline keyboards
and you tap what you need. No memorizing commands.

### Automated Schedule (all times Eastern)

| Time | What |
|------|------|
| 12:01 AM | Daily reset (meds, monthly bill cycle on 1st) |
| 5:30 AM – 3:30 PM | Med nag (every 2 hours if not taken) |
| 2:00 PM | Afternoon digest (wake-up summary) |
| 9 AM, 12 PM, 3 PM Fri | Payday bill nag (until all marked paid) |
| 10:00 PM | Evening check-in (night shift companion) |
| Sunday 12 PM | Weekly summary |

### Data Storage

SQLite database stored locally alongside the bot. Simple, fast, no extra services needed.

## File Structure

```
butler-bot/
├── bot.py              # Main entry — wires everything together
├── config.py           # All settings in one place
├── database.py         # SQLite schema and helpers
├── helpers.py          # Date math, formatting, calendar
├── keyboards.py        # ALL button layouts (the UX lives here)
├── modules/
│   ├── onboarding.py   # First-time setup questionnaire
│   ├── today.py        # 📅 Today / Tonight view
│   ├── week_view.py    # 📆 ASCII week calendar
│   ├── bills.py        # 💸 Money & Bills
│   ├── partners.py     # 💜 People & Dates
│   ├── car.py          # 🚗 Car / Admin
│   ├── credentials.py  # 🎓 Professional Credentials
│   ├── meds.py         # 💊 Medications
│   ├── notes.py        # 📒 Notes / Capture
│   └── scheduler.py    # Automated reminders & digests
├── requirements.txt
├── Dockerfile
├── railway.toml
└── Procfile
```

## Sharing With Others

The bot supports multiple users out of the box. Anyone who sends `/start`
gets their own onboarding flow and separate data. Built to be shared
with other night-shift healthcare workers.

## Customizing

- **Notification times**: Edit `config.py` or use ⚙️ Settings in the bot
- **Add new modules**: Create a file in `modules/`, add a callback handler,
  register it in `bot.py`'s `button_router`
- **Change reminder aggressiveness**: Edit intervals in `bot.py`'s `setup_jobs()`
