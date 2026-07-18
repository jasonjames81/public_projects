# Job App LLM Helper

> 🌐 **New here? Start at the friendly setup page → https://job-app-helper-iota.vercel.app**

Two ways to use this project:

1. **Use in Browser** — set up a reusable job-application assistant using Claude Projects, ChatGPT Projects, or Gemini Notebooks. No install, no API key. Your resume and writing samples live in your platform's project files; the assistant builds a voice fingerprint from them.
2. **Download the app** — a self-hosted Flask app that does the same thing locally, with your own API key, CLI login, or Ollama model. Your data stays on your machine.

Both follow the same workflow: job fit check → useful details → employer questions → draft cover letter → voice polish → refine → résumé & LinkedIn tune-up → interview prep.

---

## Use it in your browser (no install needed)

You can set up a job-application assistant using Claude Projects, ChatGPT Projects, or Gemini Notebooks — all work on free tiers. The LLM handles the full workflow using your resume and writing samples stored in the project — it builds a voice fingerprint from them.

### Free vs paid

| | Claude | ChatGPT | Gemini |
|---|---|---|---|
| Free tier | Yes (5 projects, Sonnet) | Yes (unlimited, 5 files/project) | Yes (Notebooks: 100 notebooks, 50 sources, 50 chats/day, 32k context) |
| Paid tier | Pro $20/mo (Opus, unlimited) | Plus $20/mo (25 files) | Advanced $20/mo |
| Best for | Long-form writing, nuanced voice matching | Broad tool integration, fastest iteration | Google ecosystem users |

All three work great on free tier. Paid adds more files and better models.

### Setup (one-time, ~10 min)

1. Pick your platform → [Claude](platform-guide/setup-claude.md) | [ChatGPT](platform-guide/setup-chatgpt.md) | [Gemini](platform-guide/setup-gemini.md)
2. Follow the setup guide — create a Project/Notebook, upload resume + writing samples, paste project instructions (the assistant builds your voice fingerprint on first run)
3. Paste the [kickoff message](platform-guide/kickoff-template.md) with the job posting to start — or, if you only need to prep for an interview on a role you applied to elsewhere, paste the [interview-prep message](platform-guide/interview-prep-template.md) instead

**Link-fetch note:** If a URL fails to load, the LLM will ask you to paste the text instead. This is normal — paste the job description directly when that happens.

**Privacy note:** Your resume, writing samples, and voice fingerprint live with the platform provider (Anthropic, OpenAI, or Google). Consumer tiers may use your data to improve models unless you opt out. If you need everything to stay on your machine, use the [downloadable app](#download-the-app) instead.

---

## Download the app

A self-hosted Flask app that turns a job posting into a tailored, voice-matched cover letter —
plus a fit check, drafted answers to employer questions, and interview prep — all grounded in
your own resume and writing samples. It runs on **whatever LLM access you have**: a
bring-your-own API key (Anthropic / OpenAI / Google), a logged-in AI CLI (Claude / Codex /
Gemini), or a local Ollama model.

Everything runs on your own machine. Your profile lives in your browser's `localStorage`; your
API key is stored locally (file permissions `0600`). Nothing is uploaded except the request to
the provider you pick.

### Download & run

1. Download `job-app-llm-helper.zip` from the
   [**Releases**](https://github.com/jasonjames81/bkjsun_public_projects/releases) page, unzip it,
   and open the `job-app-llm-helper` folder.
2. Start the launcher for your OS. It sets up a virtualenv on first run (~1 min), then opens the
   app in your browser. Keep the window open while you use it; close it to stop.

- **Linux:** `./start.sh` (run `chmod +x start.sh` first if needed)
- **macOS:** right-click `start-mac.command` → **Open** → **Open**
- **Windows:** double-click `start-windows.bat` (if SmartScreen warns: **More info → Run anyway**)

Requires **Python 3** — the launcher links you to it if it's missing.

### macOS one-time security unblock
> **macOS shows "Apple could not verify…" with only *Move to Trash*?** (Sequoia removed the
> right-click bypass.) Open **System Settings → Privacy & Security**, scroll down, click **Open
> Anyway**, then relaunch. Still stuck? In Terminal, type `xattr -cr ` (with a trailing space),
> drag the `job-app-llm-helper` folder onto the window, and press Return.

### Updating

You only download and approve once. On each launch the app checks for a newer release and updates
itself in place — on macOS it also clears the quarantine flag, so there's **no re-download and no
"Open Anyway" dialog** after the first time. Just relaunch as usual.

Your settings are kept: provider/API-key config lives in your OS config folder and your profile
lives in the browser, so updates never touch them. To pin a version (or stay offline), set
`JALLM_NO_UPDATE=1`. *(Auto-update applies to v0.2.5 and later; a one-time manual re-download is
needed to get onto it from an older copy.)*

### Connect an LLM

You don't need an API key — pick whatever you already have. The app auto-detects what's
available and marks it ✓ in *AI provider*.

| You have… | Use | How |
|---|---|---|
| An **API key** (Anthropic / OpenAI / Google) | matching API-key provider | paste it into *AI provider* |
| **Claude Pro/Max** | **Claude Code (CLI login)** | install [Claude Code](https://docs.anthropic.com/claude-code), run `claude` once to log in |
| **ChatGPT Plus** | **Codex (CLI login)** | install the Codex CLI, sign in with your ChatGPT account |
| **Google / Gemini** | **Gemini (CLI login)** | install the Gemini CLI, sign in with Google |
| **Nothing / offline** | **Ollama (local model)** | install [Ollama](https://ollama.com), pull a model |

For a CLI provider that's installed but not signed in, click **Connect — open login** in the
app: it opens the browser sign-in and flips to *Connected ✓* when you're done.

> A web subscription alone (claude.ai, the ChatGPT or Gemini websites) has no API behind it and
> can't be automated within those services' terms. The official CLIs are the supported way to
> use a subscription — same account, no extra cost.

### How it works

```
Your profile (once) + a job posting
   └─ Check fit ─► (optional) useful details ─► (optional) employer questions
      ─► Generate (draft + voice polish) ─► Refine ─► Interview prep ─► Download .docx
```

1. **Provider** — pick one in *AI provider*; *Generate* unlocks once one is ready.
2. **Your profile** — **Import resume or CV** (file, link, or public LinkedIn; up to 2, e.g.
   your resume *and* LinkedIn) fills your background and auto-detects name, email, phone,
   city/state, and LinkedIn. Optionally **import writing samples** (up to 4) to match your voice.
3. **The job** — **Import job posting** (file or link) splits out title / organization /
   description. Optionally **Import org website** to crawl about/mission/news and summarize it
   (recent-post coverage depends on what the site exposes).
4. **Check fit** — proceed / caution / skip, with match score, strengths, concerns, and keyword
   overlap, before you spend a generation.
5. **Useful details** and **employer questions** *(optional)* — answer tailored prompts that
   feed grounded detail into the letter and drafted question answers.
6. **Generate → Refine → Download** — a two-pass cover letter (draft, then a voice polish that
   scrubs AI tells) plus resume tips and talking points; refine with presets or your own
   instruction; download a formatted `.docx`.
7. **Interview prep** — generate likely interview questions with talking points, or practice
   interactively with follow-up coaching.

**Imports:** `.docx` and `.pdf` use pure-Python libraries (`python-docx`, `pypdf`) — no external
tools needed. Links work for any public page or a Google Doc *Published to the web*;
private docs and LinkedIn profiles need login and won't extract.

### Run from source

```bash
./start.sh            # creates a venv, installs deps, runs the app
# …or manually:
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py         # http://localhost:5000
```

Keys are read from the `platformdirs` config dir (`0600`) or the `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `GOOGLE_API_KEY` env vars. Each key maps to its provider slot
(`ANTHROPIC_API_KEY` → Anthropic, `OPENAI_API_KEY` → OpenAI, `GOOGLE_API_KEY` → Google).

| Env var | Default | Purpose |
|---|---|---|
| `JALLM_HOST` | `127.0.0.1` | set `0.0.0.0` to reach it from your phone on the same Wi-Fi |
| `JALLM_PORT` | `5000` | port |
| `JALLM_DEBUG` | off | `1` enables Flask debug — **never** on an exposed host (RCE risk) |
| `JALLM_NO_BROWSER` | off | `1` to stop auto-opening the browser on launch |
| `JALLM_NO_UPDATE` | off | `1` to skip the self-update check / stay offline |
| `CLAUDE_MODEL` | `sonnet` | model for the Claude CLI provider |
| `CLAUDE_TIMEOUT_SECONDS` | `300` | per-subprocess timeout for CLI providers |
| `WERKZEUG_RUN_MAIN` | (internal) | set by Flask's debug reloader; not user-set |

> **Self-host, one user per instance.** The API key and provider choice live on the server, and
> imports read local files / fetch URLs on the host — so a shared public instance would let
> visitors spend your key and expose your filesystem. Don't deploy it multi-tenant.

### Architecture

```
app.py          Flask routes; stateless, profile carried per request
generator.py    LLM prompts + provider routing
profile.py      Prompt blocks + voice fingerprint from the user's profile
sources.py      File-upload / path / URL import + org-site crawl (self-host only)
providers/      API / CLI / Ollama adapters, key storage, detection
cli_auth.py     CLI login probe + browser-login launch
docx_writer.py  .docx rendering (contact header from the profile)
templates/      Single-page, mobile-first UI
config.py       Default CLI model + subprocess timeout
tests/          Offline smoke tests (mock provider, no network)
```

### Tests

```bash
source venv/bin/activate && pip install pytest
python -m pytest tests/ -v   # offline — the LLM call is mocked
```

## License

[GPL-3.0](../LICENSE).
