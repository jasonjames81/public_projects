"""Offline end-to-end smoke tests — no network, no real provider.

Monkeypatches generator.call_llm so the full prompt-build → parse → response path is
exercised against a canned model reply. Verifies the public app is de-personalized
(profile threads through) and the Flask routes wire up.
"""

import json
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import profile as profile_mod  # noqa: E402

import generator  # noqa: E402
from app import app  # noqa: E402

SAMPLE_PROFILE = {
    "applicant_name": "Ada Lovelace",
    "contact": {
        "name": "Ada Lovelace",
        "city_state": "London, UK",
        "email": "ada@example.com",
    },
    "background": (
        "Mathematician and writer. Built the first published algorithm intended for a "
        "machine. Collaborated with Charles Babbage on the Analytical Engine, translating "
        "and extending Menabrea's memoir with extensive original notes."
    ),
    "writing_samples": "I believe the engine might act upon other things besides number.\n\n"
    "During my time studying the machine, I saw how symbols could be woven like a loom.",
    "stories": "Wrote Note G, the algorithm to compute Bernoulli numbers on the Analytical Engine.",
}

JOB = {
    "job_title": "Research Engineer",
    "org_name": "Analytical Engines Ltd",
    "job_description": "Seeking someone to design algorithms for novel computing machines.",
    "org_about": "We build mechanical computers.",
}


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_profile_blocks_are_depersonalized():
    summary = profile_mod.build_profile_summary(SAMPLE_PROFILE)
    assert "ADA LOVELACE" in summary
    assert "Jason" not in summary
    voice = profile_mod.build_voice_fingerprint(SAMPLE_PROFILE)
    assert "Jason" not in voice
    assert profile_mod.applicant_name(SAMPLE_PROFILE) == "Ada Lovelace"


def test_voice_fingerprint_without_samples():
    block = profile_mod.build_voice_fingerprint({"background": "x" * 50})
    assert "No writing samples" in block
    assert "Do NOT use" in block


def test_generate_route_threads_profile(client, monkeypatch):
    captured = {}
    canned = (
        "## 1. TAILORED COVER LETTER\n\n"
        "Dear Hiring Manager,\n\nI am applying for the Research Engineer role.\n\n"
        "Sincerely,\nAda Lovelace\n\n"
        "## 2. RESUME TAILORING SUGGESTIONS\n- emphasize algorithms\n\n"
        "## 3. JOB FIT ANALYSIS\nMatch score: 90\n"
    )

    def fake_call(prompt, **kw):
        captured["prompt"] = prompt
        return canned

    monkeypatch.setattr(generator, "call_llm", fake_call)

    res = client.post("/generate", json={**JOB, "profile": SAMPLE_PROFILE})
    body = res.get_json()
    assert body["success"], body
    assert "Research Engineer" in body["content"]
    # the applicant name, not Jason, reached the prompt
    assert "Ada Lovelace" in captured["prompt"]
    assert "Jason" not in captured["prompt"]


def test_coaching_route_threads_profile(client, monkeypatch):
    captured = {}
    canned = (
        "## 1. RÉSUMÉ TAILORING SUGGESTIONS\n- emphasize algorithm design\n\n"
        "## 2. INTERVIEW PREPARATION\nMatch score: 90\n- Talking point: Note G.\n"
    )

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return canned

    monkeypatch.setattr(generator, "call_llm", fake)
    res = client.post(
        "/coaching",
        json={
            **JOB,
            "profile": SAMPLE_PROFILE,
            "experience_answers": [{"question": "Hardest?", "answer": "Note G."}],
        },
    )
    body = res.get_json()
    assert body["success"], body
    assert "INTERVIEW PREPARATION" in body["content"]
    assert "Ada Lovelace" in captured["prompt"] and "Jason" not in captured["prompt"]
    assert "Note G." in captured["prompt"]  # useful details answer threaded


def test_generate_cover_letter_excludes_coaching_sections(client, monkeypatch):
    """The cover-letter route returns the letter alone (no résumé/interview sections)."""
    monkeypatch.setattr(
        generator,
        "call_llm",
        lambda prompt, **kw: (
            "Dear Hiring Manager,\n\nBody about machines.\n\nSincerely,\nAda"
        ),
    )
    res = client.post("/generate", json={**JOB, "profile": SAMPLE_PROFILE})
    body = res.get_json()
    assert body["success"], body
    assert "RESUME TAILORING" not in body["content"].upper()
    assert "INTERVIEW" not in body["content"].upper()


def test_generate_appends_employer_qa(client, monkeypatch):
    """Drafted employer answers are appended verbatim as a section after the letter."""
    monkeypatch.setattr(
        generator,
        "call_llm",
        lambda prompt, **kw: "Dear Hiring Manager,\n\nBody.\n\nSincerely,\nAda",
    )
    res = client.post(
        "/generate",
        json={
            **JOB,
            "profile": SAMPLE_PROFILE,
            "application_answers": [{"question": "Why us?", "answer": "The machines."}],
        },
    )
    content = res.get_json()["content"]
    assert "EMPLOYER APPLICATION QUESTIONS" in content
    assert "Why us?" in content and "The machines." in content


def test_analyze_fit_route(client, monkeypatch):
    monkeypatch.setattr(
        generator,
        "call_llm",
        lambda prompt, **kw: json.dumps(
            {
                "match_score": 88,
                "recommendation": "proceed",
                "rationale": "strong fit",
                "keywords_matched": ["algorithms"],
                "keywords_missing": [],
                "strengths": ["pioneering work"],
                "concerns": ["era gap"],
            }
        ),
    )
    res = client.post("/analyze-fit", json={**JOB, "profile": SAMPLE_PROFILE})
    body = res.get_json()
    assert body["success"] and body["recommendation"] == "proceed"


def test_generate_requires_background(client):
    res = client.post("/generate", json={**JOB, "profile": {"background": "too short"}})
    # job fields present, but downstream still runs; guard is on the client.
    # Here we assert the server doesn't crash and returns JSON.
    assert res.get_json() is not None


def test_get_questions_route(client, monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return json.dumps(
            ["What algorithm did you design?", "Describe a hard delivery."]
        )

    monkeypatch.setattr(generator, "call_llm", fake)
    res = client.post("/get-questions", json={**JOB, "profile": SAMPLE_PROFILE})
    body = res.get_json()
    assert body["success"] and len(body["questions"]) == 2
    assert "Ada Lovelace" in captured["prompt"] and "Jason" not in captured["prompt"]


def test_clarify_application_questions_route(client, monkeypatch):
    monkeypatch.setattr(
        generator,
        "call_llm",
        lambda prompt, **kw: json.dumps({"clarifying_questions": ["Which year?"]}),
    )
    res = client.post(
        "/clarify-application-questions",
        json={**JOB, "profile": SAMPLE_PROFILE, "questions": ["Why us? (150 words)"]},
    )
    body = res.get_json()
    assert body["success"] and body["clarifying_questions"] == ["Which year?"]


def test_answer_application_questions_route(client, monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return json.dumps(
            [{"question": "Why us?", "answer": "Because of the machines."}]
        )

    monkeypatch.setattr(generator, "call_llm", fake)
    res = client.post(
        "/answer-application-questions",
        json={
            **JOB,
            "profile": SAMPLE_PROFILE,
            "questions": [
                {"question": "Why us?", "limit": {"value": 150, "unit": "words"}}
            ],
            "clarifying_answers": [{"question": "Which year?", "answer": "1843"}],
        },
    )
    body = res.get_json()
    assert (
        body["success"] and body["answers"][0]["answer"] == "Because of the machines."
    )
    # length cap + clarifying context reached the prompt
    assert "150 words" in captured["prompt"] and "1843" in captured["prompt"]


def test_generate_includes_useful_details_and_application_answers(client, monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured.setdefault("prompts", []).append(prompt)
        return "## 1. TAILORED COVER LETTER\n\nDear Hiring Manager,\n\nBody.\n\nSincerely,\nAda\n\n## 2. RESUME TAILORING SUGGESTIONS\n- x\n"

    monkeypatch.setattr(generator, "call_llm", fake)
    res = client.post(
        "/generate",
        json={
            **JOB,
            "profile": SAMPLE_PROFILE,
            "experience_answers": [
                {"question": "Hardest project?", "answer": "Note G."}
            ],
            "application_answers": [{"question": "Why us?", "answer": "The machines."}],
        },
    )
    assert res.get_json()["success"]
    joined = "\n".join(captured["prompts"])
    assert "Note G." in joined  # useful details answer threaded
    assert "The machines." in joined  # application answer threaded (avoid duplication)


def test_download_docx_uses_profile_contact(client):
    content = (
        "## 1. TAILORED COVER LETTER\n\nDear Hiring Manager,\n\nBody paragraph.\n\n"
        "Sincerely,\nAda Lovelace\n\n## 2. RESUME TAILORING SUGGESTIONS\n- x\n"
    )
    res = client.post(
        "/download-docx",
        json={
            "content": content,
            "profile": SAMPLE_PROFILE,
            "job_title": "Research Engineer",
            "org_name": "Analytical Engines Ltd",
        },
    )
    assert res.status_code == 200
    assert res.data[:2] == b"PK"  # .docx is a zip


def test_load_source_local_txt(tmp_path):
    import sources

    f = tmp_path / "resume.txt"
    f.write_text("Ada Lovelace — algorithm designer.\n")
    out = sources.load_source(str(f))
    assert out["kind"] == "file" and "algorithm designer" in out["text"]


def test_load_source_strips_html(tmp_path):
    import sources

    f = tmp_path / "page.html"
    f.write_text(
        "<html><body><h1>Skills</h1><p>Maths &amp; logic</p><script>x()</script></body></html>"
    )
    text = sources.load_path(str(f))
    assert "Skills" in text and "Maths & logic" in text
    assert "<p>" not in text and "x()" not in text


def test_load_source_route_and_errors(client, tmp_path):
    f = tmp_path / "bg.md"
    f.write_text("# Background\nBuilt the Analytical Engine notes.")
    ok = client.post("/load-source", json={"ref": str(f)}).get_json()
    assert ok["ok"] and ok["chars"] > 0 and "Analytical Engine" in ok["text"]

    missing = client.post(
        "/load-source", json={"ref": str(tmp_path / "nope.txt")}
    ).get_json()
    assert missing["ok"] is False and "not found" in missing["error"]

    empty = client.post("/load-source", json={"ref": ""})
    assert empty.status_code == 400


def test_cli_status_not_installed(monkeypatch):
    import cli_auth

    monkeypatch.setattr(cli_auth.shutil, "which", lambda b: None)
    s = cli_auth.status("claude_cli")
    assert s["installed"] is False and s["logged_in"] is False
    assert s["login_command"] == "claude" and s["install"]["npm"]


def test_cli_is_logged_in_probe(monkeypatch):
    import subprocess

    import cli_auth

    monkeypatch.setattr(cli_auth.shutil, "which", lambda b: "/usr/bin/" + b)

    class R:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    monkeypatch.setattr(cli_auth.subprocess, "run", lambda *a, **k: R(0, "ok"))
    assert cli_auth.is_logged_in("claude_cli") is True

    monkeypatch.setattr(cli_auth.subprocess, "run", lambda *a, **k: R(1, ""))
    assert cli_auth.is_logged_in("claude_cli") is False

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 30)

    monkeypatch.setattr(cli_auth.subprocess, "run", boom)
    assert cli_auth.is_logged_in("claude_cli") is False


def test_cli_status_route(client, monkeypatch):
    import cli_auth

    bogus = client.get("/providers/cli-status?name=not_a_cli")
    assert bogus.status_code == 400

    monkeypatch.setattr(cli_auth.shutil, "which", lambda b: None)
    s = client.get("/providers/cli-status?name=gemini_cli").get_json()
    assert s["installed"] is False and s["logged_in"] is False


def test_cli_login_route_not_installed(client, monkeypatch):
    import cli_auth

    monkeypatch.setattr(cli_auth.shutil, "which", lambda b: None)
    res = client.post("/providers/cli-login", json={"name": "claude_cli"}).get_json()
    assert res["launched"] is False and "not installed" in res["error"]

    bad = client.post("/providers/cli-login", json={"name": "nope"})
    assert bad.status_code == 400
