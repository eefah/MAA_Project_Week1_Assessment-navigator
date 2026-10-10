# Assessment Navigator

A local prototype that helps parents understand community paediatric waiting lists and find their way through a child's neurodevelopmental assessment. It was built with Lambeth families in mind.

The app has three tabs:

1. **My child's next steps**: your child's referral dates, current stage, a checklist and questions for your next conversation. This is information you enter.
2. **Assessment pathway**: a typical route in five stages, with sourced guidance and service contacts.
3. **Waiting-list picture**: community paediatric figures from the NHS England Community Health Services waiting-list workbook.

The app does not diagnose, predict appointment dates or give clinical advice. It has no AI features yet. The question box at the bottom is a placeholder and is switched off.

## Install

You need Python 3.11 or newer.

```bash
cd "MAA_Project_Week1"
python3 -m venv .venv            # skip if .venv already exists
source .venv/bin/activate
pip install -r requirements.txt
```

## Set your password

The app won't open until a password is set.

1. Open `.streamlit/secrets.toml`. If it doesn't exist, copy `.streamlit/secrets.toml.example` to that name.
2. Put your password between the quotes: `APP_PASSWORD = "your-password-here"`
3. Save the file.

`secrets.toml` is in `.gitignore`, so it is never committed to GitHub.

The password page is a simple access gate for a prototype. It is not a complete security solution, so don't rely on it to protect sensitive information.

## Launch

```bash
source .venv/bin/activate
streamlit run app.py
```

Your browser opens at <http://localhost:8501>. Only this computer can open the app (`server.address = "localhost"` in `.streamlit/config.toml`). To stop the app, press `Ctrl+C` in the terminal.

## Run the checks

```bash
source .venv/bin/activate
python -m pytest -q
```

The tests cover:

- parsing the bundled NHS workbook, including Guy's and St Thomas' and England figures
- missing data on synthetic workbooks: blanks, markers such as `*`, `-` and `N/A`, real zeros, and headers in different positions
- the guidance file
- saving and deleting personal information
- the password page and the tab order

## The NHS data

- The August 2026 workbook (`Community-health-services-waiting-lists-2026-27-August.xlsx`) is included and loads by default. It is public NHS England data.
- To use a newer month, upload the original Excel file on the Waiting-list picture tab. The app finds the sheets and headings by reading their titles, not by fixed positions.
- Blank cells are shown as **Not reported** and are never treated as zero. Where the workbook explains blanks or markers, the app quotes that explanation. Undocumented markers are shown as they appear.
- "Waiting over 52 weeks" adds the published 52–104 week and over-104 week bands. It is only shown when both bands have reported numbers.
- These are **community paediatric** figures for the whole provider. They are not autism-only or Lambeth-only figures, and they cannot predict when a child will be seen.

## Editing the guidance

Pathway guidance lives in `guidance/pathway.json`, separate from the code.

- Each source has a URL and a `verified_on` date.
- Each item has `"status": "verified"` (with a `source`) or `"status": "unverified"` (shown with a **Not verified** warning).
- Only mark an item verified when the linked official page supports it. Don't add contacts, timescales or local targets without an official source.
- The app checks the file when it starts and shows an error if it's malformed. `python -m pytest -q` checks it too.

## Your information

- When the app runs on your computer, **Save** writes what you entered to `local_data/my_child.json`, which only your user account can read. **Delete saved information** removes it.
- `local_data/` is in `.gitignore`, so it is never committed.
- Nothing you enter is sent to any external service, cached or logged by the app. Streamlit usage statistics are turned off in `.streamlit/config.toml`.

## Put the code on GitHub

The project is already a Git repository with a first commit. To copy it to GitHub:

1. Sign in at <https://github.com> and choose **New repository** (the **+** at the top right).
2. Name it, for example `assessment-navigator`, and choose **Private** if you prefer.
3. Leave "Add a README", ".gitignore" and "licence" **unticked**, because the project already has them. Then choose **Create repository**.
4. In a terminal in the project folder, run (replace `YOUR-USERNAME`):

   ```bash
   git remote add origin https://github.com/YOUR-USERNAME/assessment-navigator.git
   git push -u origin main
   ```

   If GitHub asks you to sign in, follow the browser prompt or use a personal access token. The GitHub CLI (`gh auth login`) makes this easier.

5. Before pushing, you can run `git status --ignored` to confirm that `.streamlit/secrets.toml` and `local_data/` are listed as ignored.

After that, `git add`, `git commit` and `git push` will send future changes.

## Hosting later (not set up yet)

GitHub stores the code but doesn't run Streamlit apps. When you're ready to share the app online, [Streamlit Community Cloud](https://share.streamlit.io) can deploy it from your GitHub repository:

1. Sign in with GitHub, choose **Create app**, pick the repository and set the main file to `app.py`.
2. Under **Advanced settings → Secrets**, paste:

   ```toml
   APP_PASSWORD = "choose-a-password"
   HOSTED = true
   ```

   `HOSTED = true` hides Save and Delete, so nothing personal is written to the server's disk.
3. If the deployment fails to start, remove the `address = "localhost"` line from `.streamlit/config.toml`. It is only needed when running on your own computer.

Remember that a hosted app processes what people type on the hosting server, and the shared password is a basic gate, not strong security.
