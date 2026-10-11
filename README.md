# Assessment Navigator

A local prototype that helps parents understand community paediatric waiting lists and find their way through a child's neurodevelopmental assessment. It was built with Lambeth families in mind.

The app has four tabs:

1. **My child's next steps**: your child's referral dates, current stage, a checklist and questions for your next conversation. This is information you enter.
2. **Assessment pathway**: a typical route in five stages, with sourced guidance and service contacts.
3. **Waiting-list picture**: community paediatric figures from the NHS England Community Health Services waiting-list workbook.
4. **AI assistant**: a plain-English explanation of the selected provider's figures, with follow-up questions. It uses Groq and is optional.

The app does not diagnose, predict appointment dates or give clinical advice.

## Install

The project uses [uv](https://docs.astral.sh/uv/) to manage Python and its dependencies.

1. Install uv (once per computer). On a Mac with Homebrew:

   ```bash
   brew install uv
   ```

   For other options, see the uv documentation.

2. In the project folder, install everything:

   ```bash
   uv sync
   ```

`uv sync` creates `.venv/` with Python 3.13 and the exact versions in `uv.lock`.

## Set your password

The app won't open until a password is set.

1. Open `.streamlit/secrets.toml`. If it doesn't exist, copy `.streamlit/secrets.toml.example` to that name.
2. Put your password between the quotes: `APP_PASSWORD = "your-password-here"`
3. Save the file.

`secrets.toml` is in `.gitignore`, so it is never committed to GitHub.

The password page is a simple access gate for a prototype. It is not a complete security solution, so don't rely on it to protect sensitive information.

## Set up the AI assistant (optional)

Without a Groq key, the AI assistant tab shows setup instructions and the other three tabs work as normal.

1. Sign in at <https://console.groq.com>, open **API Keys** and create a key.
2. In `.streamlit/secrets.toml`, paste the key between the quotes:

   ```toml
   GROQ_API_KEY = "gsk_..."
   ```

3. Optionally, choose a model. The default is `openai/gpt-oss-120b`. For a faster, cheaper option, use `openai/gpt-oss-20b`:

   ```toml
   GROQ_MODEL = "openai/gpt-oss-120b"
   ```

4. Save the file and restart the app.

Keep the key private. Never paste it into the app, a chat or any file other than `secrets.toml`.

### What is sent to Groq

When you press **Generate explanation** or ask a question, the app sends:

- the public NHS figures for the selected provider. These are calculated in Python and include their missing-data status.
- the sourced pathway guidance, with unverified items marked as unverified.
- the question you typed.

The app does **not** send anything from *My child's next steps*: no dates, stage, checklist or notes. It doesn't send the whole workbook or the uploaded file's name either. You can see exactly what is sent in the **What is sent to Groq** panel on the AI assistant tab.

Groq is only contacted when you press the button or send a question. Please don't type names, dates of birth, NHS numbers or other identifying details into the chat.

### Limits

- **Questions:** up to 500 characters each.
- **Chat length:** up to 10 follow-up questions per chat. Use **Start a new chat** to continue.
- **History sent:** the last 6 questions and answers go with each new question.
- **Context size:** the information sent is capped at 24,000 characters. If needed, later guidance stages are left out first. Figures are never trimmed.
- **Provider or dataset changes:** the chat restarts with the new context.

AI answers can contain mistakes. Check important points with the service.

## Launch

```bash
uv run streamlit run app.py
```

Open <http://127.0.0.1:8501> in your browser. The app only listens on this computer (`server.address = "127.0.0.1"` in `.streamlit/config.toml`), so other devices on your network can't open it. To stop the app, press `Ctrl+C` in the terminal.

## Run the checks

```bash
uv run pytest
```

The tests cover:

- workbook parsing and missing data
- the guidance file
- saving and deleting personal information
- the password page and the four tabs
- the AI assistant: context building, exclusion of personal information, limits, error handling, and no Groq calls on ordinary reruns

Groq is replaced by a fake client in the tests, so they need no API key and make no paid calls. These tests check the app's own code. They don't show that a real model's answers are accurate.

## Managing dependencies

- Add a package: `uv add <package>`. For a development-only package: `uv add --dev <package>`.
- Update locked versions: `uv lock --upgrade`, then `uv sync`.
- `requirements.txt` is kept for hosting services that expect it. It is generated from `uv.lock`, so regenerate it after any dependency change:

  ```bash
  uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt
  ```

  A test checks that it lists every dependency in `pyproject.toml`.

## The NHS data

- The August 2026 workbook (`Community-health-services-waiting-lists-2026-27-August.xlsx`) is included and loads by default. It is public NHS England data.
- To use a newer month, upload the original Excel file on the Waiting-list picture tab. The app finds the sheets and headings by reading their titles, not by fixed positions.
- Blank cells are shown as **Not reported** and are never treated as zero. Where the workbook explains blanks or markers, the app quotes that explanation. Undocumented markers are shown as they appear.
- "Waiting over 52 weeks" adds the published 52–104 week and over-104 week bands. It is only shown when both bands have reported numbers.
- The bands are only compared with the total when every band and the total are reported numbers. Otherwise the comparison is labelled incomplete.
- These are **community paediatric** figures for the whole provider. They are not autism-only or Lambeth-only figures, and they cannot predict when a child will be seen.

## Editing the guidance

Pathway guidance lives in `guidance/pathway.json`, separate from the code.

- Each source has a URL and a `verified_on` date.
- Each item has `"status": "verified"` (with a `source`) or `"status": "unverified"` (shown with a **Not verified** warning).
- Only mark an item verified when the linked official page supports it. Don't add contacts, timescales or local targets without an official source.
- The app checks the file when it starts and shows an error if it's malformed. `uv run pytest` checks it too.

## Your information

- When the app runs on your computer, **Save** writes what you entered on *My child's next steps* to `local_data/my_child.json`, which only your user account can read. **Delete saved information** removes it.
- `local_data/` is in `.gitignore`, so it is never committed.
- None of this is sent to Groq or any other service, cached or logged by the app. Streamlit usage statistics are turned off in `.streamlit/config.toml`.

## Put the code on GitHub

The project is a Git repository. To copy it to GitHub:

1. Sign in at <https://github.com> and choose **New repository** (the **+** at the top right).
2. Name it, for example `assessment-navigator`, and choose **Private** if you prefer.
3. Leave "Add a README", ".gitignore" and "licence" **unticked**, because the project already has them. Then choose **Create repository**.
4. Before pushing, run `git status --ignored` and check that `.streamlit/secrets.toml` and `local_data/` are listed as ignored.
5. In a terminal in the project folder, run (replace `YOUR-USERNAME`):

   ```bash
   git remote add origin https://github.com/YOUR-USERNAME/assessment-navigator.git
   git push -u origin main
   ```

   If GitHub asks you to sign in, follow the browser prompt or use a personal access token. The GitHub CLI (`gh auth login`) makes this easier.

After that, `git add`, `git commit` and `git push` will send future changes.

## Hosting later (not set up yet)

GitHub stores the code but doesn't run Streamlit apps. When you're ready to share the app online, [Streamlit Community Cloud](https://share.streamlit.io) can deploy it from your GitHub repository:

1. Sign in with GitHub, choose **Create app**, pick the repository and set the main file to `app.py`.
2. Under **Advanced settings → Secrets**, paste:

   ```toml
   APP_PASSWORD = "choose-a-password"
   HOSTED = true
   GROQ_API_KEY = "gsk_..."
   GROQ_MODEL = "openai/gpt-oss-120b"
   ```

   `HOSTED = true` hides Save and Delete, so nothing personal is written to the server's disk.

3. The app is set to listen only on `127.0.0.1` for local use. A hosting service needs it to listen more widely. Change this setting only when deploying, and only for the hosted copy, because it makes the app reachable over the network.

Remember that a hosted app processes what people type on the hosting server, and the shared password is a basic gate, not strong security.
