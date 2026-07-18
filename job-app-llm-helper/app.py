# app.py
"""Flask app for Job App LLM Helper (public, self-hosted edition).

Stateless by design: the applicant profile (name, background, contact, optional
writing samples and story notes) is supplied by the browser with each request and
remembered client-side in localStorage. The server reads and writes no per-user
files — only the provider config (API-key selection) lives on disk, via platformdirs.

Self-host only: the import (sources.py) and CLI-login (cli_auth.py) routes read local
files / launch local processes, so this must not run as a shared multi-tenant server.
"""

import profile as profile_mod
import re
from datetime import date

from flask import Flask, Response, jsonify, render_template, request

import cli_auth
from docx_writer import build_coaching_docx, build_cover_letter_docx, extract_cover_letter_section
from generator import (
    analyze_fit,
    answer_application_questions,
    extract_contact_fields,
    extract_job_fields,
    generate_clarifying_questions,
    generate_cover_letter,
    generate_interview_followup,
    generate_interview_prep,
    generate_questions,
    generate_resume_tuning,
    refine_letter,
    summarize_org,
)
from providers.config import ProviderConfig
from providers.detect import detect_providers
from providers.registry import list_models
from sources import SourceError, crawl_site, load_source, load_upload

# Contact fields recoverable without a model. LinkedIn/email/phone are regular enough
# for regex; name and city/state are left to the LLM (extract_contact_fields).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\d(])(\+?\(?\d[\d().\-\s]{7,}\d)(?!\d)")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[^\s)>\]]+", re.I)


def _regex_contact(text: str) -> dict:
    """Pull email / phone / LinkedIn out of resume text — no model needed."""
    email = _EMAIL_RE.search(text)
    linkedin = _LINKEDIN_RE.search(text)
    phone = _PHONE_RE.search(text)
    fields = {}
    if email:
        fields["email"] = email.group(0)
    if phone:
        fields["phone"] = phone.group(1).strip()
    if linkedin:
        url = linkedin.group(0)
        fields["linkedin"] = url if url.startswith("http") else f"https://{url}"
    return fields


app = Flask(__name__)


def _profile_from(data: dict) -> dict:
    """Pull the applicant profile out of a request body, defaulting to empty."""
    profile = data.get("profile")
    return profile if isinstance(profile, dict) else {}


def _job_fields(data: dict) -> tuple[str, str, str, str]:
    return (
        data.get("job_title", "").strip(),
        data.get("org_name", "").strip(),
        data.get("job_description", "").strip(),
        data.get("org_about", "").strip(),
    )


def _missing_job():
    return (
        jsonify(
            {
                "success": False,
                "error": "Please fill in Job Title, Organization Name, and Job Description",
            }
        ),
        400,
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/profile-status", methods=["POST"])
def profile_status():
    """Report whether the supplied profile has enough background to generate from."""
    profile = _profile_from(request.get_json(silent=True) or {})
    return jsonify(
        {
            "ready": profile_mod.has_minimum_profile(profile),
            "name": profile_mod.applicant_name(profile),
        }
    )


@app.route("/load-source", methods=["POST"])
def load_source_route():
    """Extract text from a local file path or web URL (self-host only — see sources.py)."""
    data = request.get_json(silent=True) or {}
    ref = (data.get("ref") or "").strip()
    if not ref:
        return jsonify({"ok": False, "error": "provide a file path or URL"}), 400
    try:
        result = load_source(ref)
    except SourceError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the UI
        return jsonify({"ok": False, "error": f"could not load source: {e}"})
    return jsonify(
        {
            "ok": True,
            "kind": result["kind"],
            "text": result["text"],
            "chars": len(result["text"]),
        }
    )


@app.route("/upload-source", methods=["POST"])
def upload_source_route():
    """Parse a browser-uploaded resume/sample/posting file (self-host only — see sources.py)."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "no file uploaded"}), 400
    try:
        text = load_upload(f.filename, f.read())
        text = (text or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "no readable text found in that file"})
    except SourceError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the UI
        return jsonify({"ok": False, "error": f"could not read file: {e}"})
    return jsonify({"ok": True, "kind": "file", "text": text, "chars": len(text)})


@app.route("/extract-contact", methods=["POST"])
def extract_contact_route():
    """Best-effort structured contact extraction from imported resume text.

    Regex fills email/phone/LinkedIn (always); the LLM fills name + city/state when
    a provider is configured. Never an error — missing fields just stay blank.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    fields = _regex_contact(text)
    try:
        fields.update({k: v for k, v in extract_contact_fields(text).items() if v})
    except Exception:  # noqa: BLE001,S110 — no provider / model error: keep regex fields
        pass
    return jsonify({"ok": True, "fields": fields})


@app.route("/extract-job", methods=["POST"])
def extract_job_route():
    """Split imported job-posting text into structured fields via the LLM.

    Falls back to dumping the raw text into job_description when no provider is set
    up or the model can't parse it, so import always yields something usable.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "no text to parse"}), 400
    try:
        fields = extract_job_fields(text)
        if fields.get("job_description"):
            return jsonify({"ok": True, "fields": fields})
    except Exception:  # noqa: BLE001,S110 — degrade to raw dump below
        pass
    return jsonify({"ok": True, "fallback": True, "fields": {"job_description": text}})


@app.route("/import-org", methods=["POST"])
def import_org_route():
    """Crawl an org website (about/mission/news/blog) and summarize it via the LLM.

    Falls back to the raw crawled text when no provider is configured or the model
    fails. Self-host only — fetches arbitrary URLs on the host (see sources.py).
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "provide a website URL"}), 400
    try:
        crawled = crawl_site(url)
    except SourceError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:  # noqa: BLE001 — surface any unexpected fetch failure
        return jsonify({"ok": False, "error": f"could not crawl site: {e}"})
    try:
        summary = summarize_org(crawled)
        if summary:
            return jsonify({"ok": True, "text": summary, "chars": len(summary)})
    except Exception:  # noqa: BLE001,S110 — degrade to raw crawled text below
        pass
    return jsonify({"ok": True, "fallback": True, "text": crawled, "chars": len(crawled)})


@app.route("/analyze-fit", methods=["POST"])
def analyze_fit_route():
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    if not job_title or not org_name or not job_description:
        return _missing_job()
    return jsonify(
        analyze_fit(_profile_from(data), job_title, org_name, job_description, org_about)
    )


@app.route("/clarify-application-questions", methods=["POST"])
def clarify_application_questions():
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    questions = data.get("questions", [])
    if (
        not job_title
        or not org_name
        or not job_description
        or not isinstance(questions, list)
        or not questions
    ):
        return _missing_job()
    return jsonify(
        generate_clarifying_questions(
            _profile_from(data),
            questions=questions,
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
        )
    )


@app.route("/answer-application-questions", methods=["POST"])
def answer_application_questions_route():
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    questions = data.get("questions", [])
    clarifying_answers = data.get("clarifying_answers", [])
    if (
        not job_title
        or not org_name
        or not job_description
        or not isinstance(questions, list)
        or not questions
    ):
        return _missing_job()
    return jsonify(
        answer_application_questions(
            _profile_from(data),
            questions=questions,
            clarifying_answers=clarifying_answers,
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
        )
    )


@app.route("/get-questions", methods=["POST"])
def get_questions():
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    prior_qa = data.get("prior_qa", [])
    if not job_title or not org_name or not job_description:
        return _missing_job()
    return jsonify(
        generate_questions(
            _profile_from(data),
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
            prior_qa=prior_qa,
        )
    )


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    additional_notes = data.get("additional_notes", "").strip()
    experience_answers = data.get("experience_answers", [])
    application_answers = data.get("application_answers", [])
    if not job_title or not org_name or not job_description:
        return _missing_job()
    return jsonify(
        generate_cover_letter(
            _profile_from(data),
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
            additional_notes=additional_notes,
            experience_answers=experience_answers or None,
            application_answers=application_answers or None,
        )
    )


def _coaching_route(generate_fn):
    """Shared body for the résumé-tuning and interview-prep endpoints.

    Split into two calls (not one combined coaching pass) because interview
    prep typically happens weeks after the application is submitted.
    """
    data = request.json or {}
    job_title, org_name, job_description, org_about = _job_fields(data)
    experience_answers = data.get("experience_answers", [])
    if not job_title or not org_name or not job_description:
        return _missing_job()
    return jsonify(
        generate_fn(
            _profile_from(data),
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
            experience_answers=experience_answers or None,
        )
    )


@app.route("/resume-tuning", methods=["POST"])
def resume_tuning():
    return _coaching_route(generate_resume_tuning)


@app.route("/interview-prep", methods=["POST"])
def interview_prep():
    return _coaching_route(generate_interview_prep)


@app.route("/interview-practice", methods=["POST"])
def interview_practice():
    data = request.json or {}
    question = data.get("question", "").strip()
    user_answer = data.get("user_answer", "").strip()
    prior_qa = data.get("prior_qa", [])
    job_title, org_name, job_description, org_about = _job_fields(data)
    if not question or not user_answer:
        return jsonify({"success": False, "error": "Need both question and user_answer"}), 400
    if not job_title or not org_name or not job_description:
        return _missing_job()
    return jsonify(
        generate_interview_followup(
            _profile_from(data),
            question=question,
            user_answer=user_answer,
            prior_qa=prior_qa,
            job_title=job_title,
            org_name=org_name,
            job_description=job_description,
            org_about=org_about,
        )
    )


@app.route("/download-coaching-docx", methods=["POST"])
def download_coaching_docx():
    data = request.json or {}
    content = data.get("content", "").strip()
    job_title = data.get("job_title", "").strip()
    org_name = data.get("org_name", "").strip()
    if not content:
        return jsonify({"success": False, "error": "content is required"}), 400
    docx_bytes = build_coaching_docx(content, job_title=job_title, org_name=org_name)
    safe_org = org_name.replace(" ", "_").replace("/", "_") or "Application"
    safe_role = job_title.replace(" ", "_").replace("/", "_") or "Tips"
    filename = f"CoachingTips_{safe_org}_{safe_role}.docx"
    return Response(
        docx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/compute-voice-fingerprint", methods=["POST"])
def compute_voice_fingerprint():
    profile = _profile_from(request.get_json(silent=True) or {})
    fingerprint = profile_mod.build_voice_fingerprint(profile)
    return jsonify({"ok": True, "fingerprint": fingerprint})


@app.route("/refine", methods=["POST"])
def refine():
    data = request.json or {}
    current_letter = data.get("current_letter", "").strip()
    instruction = data.get("instruction", "").strip()
    job_title = data.get("job_title", "").strip()
    org_name = data.get("org_name", "").strip()
    if not current_letter or not instruction:
        return jsonify({"success": False, "error": "Need both current_letter and instruction"}), 400
    return jsonify(
        refine_letter(current_letter, instruction, _profile_from(data), job_title, org_name)
    )


@app.route("/download-docx", methods=["POST"])
def download_docx():
    data = request.json or {}
    content = data.get("content", "").strip()
    org_name = data.get("org_name", "").strip()
    job_title = data.get("job_title", "").strip()
    if not content:
        return jsonify({"success": False, "error": "content is required"}), 400

    contact = profile_mod.contact_from_profile(_profile_from(data))
    letter_text = extract_cover_letter_section(content)
    docx_bytes = build_cover_letter_docx(letter_text, contact=contact, today=date.today())

    safe_org = org_name.replace(" ", "_").replace("/", "_") or "Application"
    safe_role = job_title.replace(" ", "_").replace("/", "_") or "CoverLetter"
    filename = f"CoverLetter_{safe_org}_{safe_role}.docx"
    return Response(
        docx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/test-api")
def test_api():
    cfg = ProviderConfig().load()
    selected = cfg.selected() or "claude_cli"
    infos = {i.name: i for i in detect_providers(cfg)}
    info = infos.get(selected)
    if info is None or not info.available:
        return jsonify(
            {
                "configured": False,
                "message": f"selected provider '{selected}' is not available",
            }
        )
    return jsonify({"configured": True, "message": f"{info.display_name} ready — {info.detail}"})


@app.route("/providers")
def list_providers_route():
    cfg = ProviderConfig().load()
    infos = detect_providers(cfg)
    return jsonify(
        {
            "selected": cfg.selected(),
            "providers": [
                {
                    "name": i.name,
                    "display_name": i.display_name,
                    "kind": i.kind,
                    "available": i.available,
                    "detail": i.detail,
                    "tier": i.tier.value,
                    "tier_verified": i.tier_verified,
                    "model": i.model,
                }
                for i in infos
            ],
        }
    )


@app.route("/providers/models")
def provider_models_route():
    cfg = ProviderConfig().load()
    name = (request.args.get("name") or "").strip()
    return jsonify({"models": list_models(name, cfg)})


@app.route("/providers/cli-status")
def cli_status_route():
    """Installed + logged-in state for a subscription CLI provider (self-host only)."""
    name = (request.args.get("name") or "").strip()
    if name not in cli_auth.BINARY:
        return jsonify({"error": f"not a CLI provider: {name!r}"}), 400
    return jsonify(cli_auth.status(name))


@app.route("/providers/cli-login", methods=["POST"])
def cli_login_route():
    """Open the CLI's browser login in a terminal (self-host only).

    Falls back to a manual command.
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if name not in cli_auth.BINARY:
        return jsonify({"launched": False, "error": f"not a CLI provider: {name!r}"}), 400
    return jsonify(cli_auth.launch_login(name))


@app.route("/providers/select", methods=["POST"])
def select_provider_route():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    cfg = ProviderConfig().load()
    known = {i.name for i in detect_providers(cfg)}
    if name not in known:
        return jsonify({"success": False, "error": f"unknown provider '{name}'"}), 400
    cfg.set_selected(name)
    model = (data.get("model") or "").strip()
    if model:
        cfg.set_model(name, model)
    cfg.save()
    return jsonify({"success": True})


@app.route("/providers/key", methods=["POST"])
def set_provider_key_route():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    key = (data.get("key") or "").strip()
    if not name or not key:
        return jsonify({"success": False, "error": "name and key are required"}), 400
    cfg = ProviderConfig().load()
    captured = {}
    cfg.set_key(name, key, on_consent=lambda msg: captured.setdefault("msg", msg))
    cfg.save()
    return jsonify({"success": True, "consent": captured.get("msg", "")})


if __name__ == "__main__":
    import os
    import sys

    # Prod-safe defaults: debug OFF, bound to localhost. Override via env when you
    # self-host. Set JALLM_HOST=0.0.0.0 to reach it from your phone on the same
    # network. Never enable debug on an exposed host (Werkzeug console is an RCE).
    debug = os.environ.get("JALLM_DEBUG", "").lower() in ("1", "true", "yes")
    host = os.environ.get("JALLM_HOST", "127.0.0.1")
    port = int(os.environ.get("JALLM_PORT", "5000"))

    print("\n" + "=" * 60)
    print("  JOB APP LLM HELPER")
    print("=" * 60)
    _selected = ProviderConfig().load().selected() or "claude_cli"
    print(f"\nGenerating via provider: {_selected} (change it in the web UI)")
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Open http://{display_host}:{port} in your browser")
    if host == "0.0.0.0":
        print("Reachable on your LAN — open http://<this-machine-ip>:%d on your phone" % port)

    # Surface a missing file-parsing dependency loudly here, in the terminal the
    # user keeps open — otherwise it only shows as an error after they try to
    # upload. Points at the most common cause: the launcher used a different
    # Python than this one (so deps installed elsewhere).
    _missing = []
    for _mod, _pkg in (("pypdf", "pypdf"), ("docx", "python-docx")):
        try:
            __import__(_mod)
        except ImportError:
            _missing.append(_pkg)
    if _missing:
        print()
        print(f"  ⚠  File upload (.pdf/.docx) is DISABLED — missing: {', '.join(_missing)}")
        print(
            f"     Install into THIS Python:  {sys.executable} -m pip install {' '.join(_missing)}"
        )
        print("     (You can still paste text directly.)")
    print()

    # Pop the browser open so the user lands in the UI instead of staring at the
    # terminal. Skip when bound to all interfaces (likely headless/LAN) or when
    # opted out via env. Guard against the debug reloader opening a second tab:
    # only the reloaded child (WERKZEUG_RUN_MAIN) — or the sole process when
    # debug is off — should open it.
    no_browser = os.environ.get("JALLM_NO_BROWSER", "").lower() in ("1", "true", "yes")
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if not no_browser and host != "0.0.0.0" and (not debug or is_reloader_child):
        import threading
        import webbrowser

        url = f"http://localhost:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(debug=debug, host=host, port=port)
