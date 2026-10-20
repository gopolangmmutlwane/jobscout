# jobscout

A personal job-search agent. Every morning it collects new graduate and entry-level job ads, ranks them against my profile, and emails me the best matches.

## How it works

1. **Collect.** Graduates24 listing and ad pages (HTML scraping with a robots.txt check, a 2-second delay between requests and an honest user agent; it stops if a bot-check page appears) and, optionally, the Adzuna API (personal job-search use, with a local call cap).
2. **Store.** SQLite through SQLAlchemy. Duplicates are removed by URL and by a title and company fingerprint.
3. **Rank.** Filters first: closed ads, seniority words in the title, location, experience demanded, and fields clearly outside my degree. Then a score from TF-IDF cosine similarity to my master CV, plus bonuses for skills, role titles and a degree-field check on the ad's requirement lines.
4. **Notify.** A plain-text email digest, with each ad sent once.
5. **Label.** A small command-line tool to mark ads interested or skip. The labels are the training data for a planned classifier.

It runs daily through Windows Task Scheduler.

## Status

- Done: collectors, deduplication, rule-based ranker, labelling tool, email digest, scheduling.
- Planned: a classifier trained on my labels (evaluated with precision@k), and reading job-alert emails from other sites.

## Responsible use

- It respects robots.txt and never tries to get past a bot check.
- Adzuna data is used only for my own job search, under their terms, and is not redistributed.
- My CV, profile, ad database and keys are private and git-ignored.

## Setup

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    pip install -e .
    copy .env.example .env
    python scripts\init_db.py

Then create `data\profile\master_cv.md` and `data\profile\profile.yaml` (kept private), and fill in `.env`.

## Commands

    python -m jobscout.main collect      # fetch new ads
    python -m jobscout.main match        # rank stored ads
    python scripts\label_jobs.py         # label ads
    python -m jobscout.daily             # collect, then email the digest

## Triage page (phone)

A small PIN-protected web page for working through ads on the phone: one ad at a time with Skip / Keep / Applied, plus Kept, Applied (with outcomes) and Skipped tabs.

1. In `.env` set `WEB_PIN` (6+ digits) and `WEB_SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`). Optional: `WEB_PORT` (default 8765) and `WEB_BASE_URL`, the address the phone uses (for example `http://192.168.1.20:8765`). When `WEB_BASE_URL` is set, every ad in the email digest gets a direct link to its card.
2. Start it:

        powershell -ExecutionPolicy Bypass -File scripts\run_web.ps1

   or, with the venv active, `python -m jobscout.web`. Output goes to `data\output\web.log`. Allow it through Windows Firewall on private networks when asked, then open `http://<pc-ip>:8765` on the phone (same Wi-Fi).

To start it automatically at logon and restart it if it crashes, register a scheduled task once (in PowerShell, from the project folder):

    $action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PWD\scripts\run_web.ps1`"" -WorkingDirectory "$PWD"
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "jobscout web" -Action $action -Trigger $trigger -Settings $settings -Description "jobscout triage page"

Check it with `Get-ScheduledTask -TaskName "jobscout web"`, start it now with `Start-ScheduledTask -TaskName "jobscout web"`, remove it with `Unregister-ScheduledTask -TaskName "jobscout web"`.

## Stack

Python, requests, BeautifulSoup, SQLAlchemy, scikit-learn, pandas, SMTP.