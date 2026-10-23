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

`run_web.ps1` starts a hidden supervisor that runs the server and restarts it within seconds if it exits, then returns straight away; running it again while the page is up does nothing. Two scheduled tasks call it: **jobscout web** at logon and **jobscout web watchdog** every 5 minutes (in case the supervisor itself was stopped). Both run it through `conhost.exe --headless`, so no window opens. On Windows 11, `-WindowStyle Hidden` alone still opens a Windows Terminal tab, and closing that tab used to kill the page. To register them once (normal PowerShell, from the project folder):

    $action   = New-ScheduledTaskAction -Execute "C:\Windows\System32\conhost.exe" -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PWD\scripts\run_web.ps1`"" -WorkingDirectory "$PWD"
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "jobscout web" -Action $action -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Settings $settings
    Register-ScheduledTask -TaskName "jobscout web watchdog" -Action $action -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)) -Settings $settings

Stop the page with `powershell -ExecutionPolicy Bypass -File scripts\run_web.ps1 -Stop` (otherwise the supervisor restarts it); run `run_web.ps1` again to start it, for example after changing the code.

## Application files

On the page, every Applied and Kept card and every ad page (`/ad/<id>`) has a **Files** section for the CV, cover letter or other documents you sent for that job. PDF, DOCX and DOC only (checked by content, not just by name), up to 10 MB each and 10 per job. Applied cards show a file count and a **CV** button that opens the newest CV.

The files are stored in `data\applications\<job id>\` under random names; the original file names are kept only in the database (`application_documents` table). The folder is git-ignored and never leaves your PC. Deleting a file on the page removes both the database row and the file. Undo, Skip and Applied never touch files.

## Backup

Everything personal stays out of git, so back these up yourself (for example by copying them to OneDrive or a USB drive):

- `jobscout.db`: ads, labels, applications, replies and the list of saved files
- `data\applications\`: the files themselves (keep it together with `jobscout.db`, from the same moment)
- `data\profile\`: your master CV and profile
- `.env`: your keys and passwords (store it somewhere private)

## Troubleshooting

Scheduled tasks run jobscout: **jobscout daily** (07:30, collect and email the digest), **jobscout web** (at logon) and **jobscout web watchdog** (every 5 minutes), which both start the triage page. Check when they last ran and how they ended:

    Get-ScheduledTaskInfo -TaskName "jobscout daily"        | Select-Object LastRunTime, LastTaskResult, NextRunTime
    Get-ScheduledTaskInfo -TaskName "jobscout web"          | Select-Object LastRunTime, LastTaskResult
    Get-ScheduledTaskInfo -TaskName "jobscout web watchdog" | Select-Object LastRunTime, LastTaskResult, NextRunTime

`LastTaskResult` 0 means success. 267009 means still running; the web tasks finish within seconds, so a web task stuck on Running needs `Stop-ScheduledTask`. 3221225786 (0xC000013A) means the process was closed from outside (a closed console window or Ctrl+C). Any other value is the exit code of a failed run; the log says why.

If the page is down (connection refused):

1. `Get-NetTCPConnection -LocalPort 8765 -State Listen`: nothing listening means the server is not running.
2. Look at the end of `data\output\web.log`. "exited with code N; restarting" lines come from the supervisor. A "Not starting: ..." line means `.env` is missing `WEB_PIN` or `WEB_SECRET_KEY`.
3. Start it: `powershell -ExecutionPolicy Bypass -File scripts\run_web.ps1` (or wait at most 5 minutes for the watchdog).
4. Works on the PC but not on the phone: check Tailscale is connected on both, and use the PC's Tailscale address (`tailscale ip -4`) with port 8765.

Logs (UTF-8, newest at the bottom):

- `data\output\daily.log`: one block per daily run, from "starting jobscout daily" to "finished, exit code N". A good run includes "Digest sent". `daily.old.log` holds output from before 23 Oct 2026 (UTF-16).
- `data\output\web.log`: "starting jobscout web" and "exited with code N" lines from the supervisor, plus anything the page prints.

Run them by hand from the project folder:

    powershell -ExecutionPolicy Bypass -File scripts\run_daily.ps1          # same as the task, logs to daily.log
    .venv\Scripts\python.exe -m jobscout.daily --no-collect --dry-run      # print the digest, send nothing
    .venv\Scripts\python.exe -m jobscout.daily --test                      # send a test email
    powershell -ExecutionPolicy Bypass -File scripts\run_web.ps1            # start the page (no-op if it is up)
    powershell -ExecutionPolicy Bypass -File scripts\run_web.ps1 -Stop      # stop the page
    Start-ScheduledTask -TaskName "jobscout daily"                         # or trigger a task directly

## Stack

Python, requests, BeautifulSoup, SQLAlchemy, scikit-learn, pandas, SMTP.