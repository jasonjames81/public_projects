# generator.py
"""LLM generation for the public cover-letter app.

Forked from the personal edition's claude_generator.py and de-personalized: every
prompt is parameterized by the runtime ``profile`` dict (see profile.py) instead of a
hardcoded applicant and disk-loaded documents. Provider routing is unchanged — it
flows through providers/ and works with any configured CLI, API key, or local model.
"""

from __future__ import annotations

import json
import re

import profile as profile_mod
from providers.base import ProviderError
from providers.config import ProviderConfig
from providers.registry import get_provider

# Default word cap used when a question carries no explicit length limit.
_DEFAULT_ANSWER_LIMIT = "~150 words"


def _hard_constraints(name: str) -> str:
    """Shared hard constraints, parameterized by applicant name."""
    return f"""\
=== HARD CONSTRAINTS ===

1. QUANTIFIED CLAIMS: Use only numbers, percentages, dates, dollar amounts, durations, team
   sizes, or other quantities that appear verbatim in {name}'s background, story notes, or
   answers above. Do not infer, estimate, round, or extrapolate. If a number would be helpful
   but is not provided, write the qualitative claim without a number rather than fabricating one.

2. STORY USE: Only deploy accomplishments whose subject matter matches the JD. Do not invent
   specifics, quotes, or numbers beyond what {name} wrote. Do not combine details across
   separate stories into a single anecdote.

3. VOICE: Match the voice fingerprint above — sentence length distribution, paragraph rhythm,
   characteristic openers/transitions/closers. Avoid every phrase in the "Do NOT use" list.

4. NO AI TELLS: Do not write meta-language about being thrilled, excited to apply, writing
   to express interest, finding the role compelling, or being a perfect fit. Do not use
   triadic flourishes ("I bring rigor, empathy, and vision"). Do not write a closing line
   that summarizes the letter you just wrote. Do not use negative/contrastive parallelism —
   "it's not X, it's Y", "not just X, but Y", "X rather than Y"; state the point directly.
   Do not pad with trailing "-ing" analysis clauses ("...positioning me to add value",
   "...underscoring my commitment"). Avoid copulative-dodging verbs ("serves as a testament
   to", "stands as") — just use "is/am". Avoid buzzword filler (leverage, utilize, delve,
   robust, seamless, results-driven, proven track record, passionate) and stock openers
   ("I hope this finds you well", "I am writing to express my interest")."""


def _load_provider_config() -> ProviderConfig:
    # Re-reads from disk each call so a provider selection saved by the web UI
    # takes effect on the next generation — no module-level cache.
    return ProviderConfig().load()


def _selected_provider_name(cfg: ProviderConfig) -> str:
    # Default to the Claude CLI when nothing is selected, so a machine with `claude`
    # logged in works out of the box; public users instead pick an API-key provider.
    return cfg.selected() or "claude_cli"


def _extract_json(response: str, *, array: bool = False):
    """Extract and parse a JSON value from an LLM response string."""
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", response.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    pattern = r"\[[\s\S]*\]" if array else r"\{[\s\S]*\}"
    match = re.search(pattern, response)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"no JSON {'array' if array else 'object'} found in response")


def call_llm(prompt: str, *, retries: int = 1) -> str:
    """Generate text from the user's selected LLM provider and return it stripped."""
    cfg = _load_provider_config()
    name = _selected_provider_name(cfg)
    try:
        provider = get_provider(name, cfg)
        result = provider.generate(prompt)
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc
    return result.strip()


def extract_contact_fields(text: str) -> dict:
    """Pull a name and city/state out of pasted resume/profile text via the LLM.

    Email, phone, and LinkedIn are recovered by regex upstream (no model needed);
    this fills only the two fields regex handles poorly. Returns {} on failure so
    the caller can degrade gracefully (the user just types those fields by hand).
    """
    text = (text or "").strip()
    if not text:
        return {}
    snippet = text[:6000]
    prompt = f"""From the resume / profile text below, extract the applicant's full name
and their location as "City, State" (or "City, Country").

Return ONLY a JSON object, no prose, no markdown fences:
{{"name": "<full name or empty string>", "city_state": "<City, State or empty string>"}}

Use an empty string for any field you cannot determine. Do not guess.

=== TEXT ===
{snippet}"""
    raw = call_llm(prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return {}
    return {
        "name": str(data.get("name") or "").strip(),
        "city_state": str(data.get("city_state") or "").strip(),
    }


def extract_job_fields(text: str) -> dict:
    """Split a pasted/imported job posting into structured fields via the LLM.

    Returns {"job_title", "org_name", "job_description", "org_about"}. Raises on
    model failure so the caller can fall back to dumping the raw text into the
    description field.
    """
    text = (text or "").strip()
    if not text:
        return {}
    snippet = text[:12000]
    prompt = f"""From the job posting below, extract these fields.

Return ONLY a JSON object, no prose, no markdown fences:
{{
  "job_title": "<the role title>",
  "org_name": "<the hiring organization / company name>",
  "job_description": "<the responsibilities, requirements, and role details, cleaned of navigation/boilerplate but otherwise verbatim>",
  "org_about": "<any 'about the company / mission / values' section, or empty string>"
}}

Use an empty string for any field not present. Do not invent details. Keep the
job_description substantive — it feeds cover-letter generation.

=== JOB POSTING ===
{snippet}"""
    raw = call_llm(prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return {}
    return {
        "job_title": str(data.get("job_title") or "").strip(),
        "org_name": str(data.get("org_name") or "").strip(),
        "job_description": str(data.get("job_description") or "").strip(),
        "org_about": str(data.get("org_about") or "").strip(),
    }


def summarize_org(text: str) -> str:
    """Condense crawled org-website text into a mission/values + recent-activity brief.

    Returns prose suitable for the "About the organization" field. Raises on model
    failure so the caller can fall back to the raw crawled text.
    """
    text = (text or "").strip()
    if not text:
        return ""
    snippet = text[:20000]
    prompt = f"""Below is text crawled from an organization's website (multiple pages,
each tagged with its URL). Write a concise brief for a job applicant, covering:

- Mission / what the organization does and the values it states.
- Any recent activity (posts, news, blog items, announcements) you can find — note the
  date only if it actually appears in the text; do not guess or assume recency.

Write plain prose (a few short paragraphs), no markdown headings, no preamble. Use only
what the text supports — do not invent programs, dates, or claims. If recent posts aren't
present, say the site didn't surface dated recent activity.

=== CRAWLED SITE TEXT ===
{snippet}"""
    return call_llm(prompt).strip()


def refine_letter(
    current_letter: str,
    instruction: str,
    profile: dict,
    job_title: str = "",
    org_name: str = "",
):
    """Revise an existing cover letter per a free-form instruction."""
    if not current_letter.strip():
        return {"success": False, "error": "current_letter is empty"}
    if not instruction.strip():
        return {"success": False, "error": "instruction is empty"}

    name = profile_mod.applicant_name(profile)
    voice_block = profile_mod.build_voice_fingerprint(profile)

    prompt = f"""You are revising {name}'s cover letter based on a specific instruction.
Maintain the writer's voice and preserve every factual claim. Output ONLY the revised letter — no
preamble, no explanation, no markdown fences, no after-notes.

{voice_block}

=== JOB CONTEXT ===
{f"Role: {job_title}" if job_title else ""}
{f"Organization: {org_name}" if org_name else ""}

=== CURRENT LETTER ===
{current_letter.strip()}

=== INSTRUCTION ===
{instruction.strip()}

=== CONSTRAINTS ===
- Preserve every factual claim. Do not invent new numbers, organizations, dates, or stories.
- Match the voice fingerprint above; avoid the "Do NOT use" phrases.
- Keep the contact block, date, salutation, and signature unless the instruction says otherwise.
- Output the full revised letter only."""

    try:
        revised = call_llm(prompt).strip()
        if not revised:
            return {"success": False, "error": "the model returned an empty letter"}
        return {"success": True, "letter": revised}
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_fit(profile: dict, job_title, org_name, job_description, org_about=""):
    """Pre-flight fit analysis with a traffic-light recommendation."""
    name = profile_mod.applicant_name(profile)
    profile_block = profile_mod.build_profile_summary(profile)
    stories_block = profile_mod.build_stories_block(profile)

    prompt = f"""You are screening a job posting against {name}'s full profile to decide
whether they should apply. Be honest — flag mismatches the applicant should know about, but
base every judgment on ALL of the materials below.

{profile_block}

{stories_block}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}

=== YOUR TASK ===

Output ONLY a JSON object with these exact keys:

{{
  "match_score": <int 0-100>,
  "recommendation": "proceed" | "caution" | "skip",
  "rationale": "<one sentence summary of the recommendation>",
  "keywords_matched": ["<3-7 JD requirements/keywords clearly satisfied by the profile>"],
  "keywords_missing": ["<3-7 JD requirements/keywords NOT clearly evidenced in the profile>"],
  "strengths": ["<3-4 specific strengths the applicant brings to THIS role; reference concrete experience>"],
  "concerns": ["<2-4 specific concerns the hiring side will likely raise>"]
}}

GUIDELINES:
- Assess fit against the FULL background and story notes above, not a single headline line.
- Before placing anything in "keywords_missing" or "concerns", confirm it is genuinely absent
  from every input above. Never assert the applicant lacks experience that a document or story shows.
- "proceed" when score >= 70 AND no fatal mismatches (location ineligibility, missing required certifications, etc.)
- "caution" when score 50-69 OR there is a meaningful mismatch worth addressing in the cover letter
- "skip" when score < 50 OR there is a fatal mismatch
- For "keywords_missing", list things the JD explicitly requires that the profile doesn't evidence — these matter for ATS / hiring screens
- For "concerns", be specific and constructive.
- No prose outside the JSON. No markdown fences."""

    try:
        response = call_llm(prompt)
        data = _extract_json(response, array=False)
        data["success"] = True
        return data
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_clarifying_questions(
    profile: dict,
    questions: list[str],
    job_title: str,
    org_name: str,
    job_description: str,
    org_about: str = "",
) -> dict:
    """Decide which pasted employer questions need more detail and ask for it."""
    name = profile_mod.applicant_name(profile)
    profile_block = profile_mod.build_profile_summary(profile)
    stories_block = profile_mod.build_stories_block(profile)
    questions_block = "\n".join(f"- {q}" for q in questions)

    prompt = f"""You are helping {name} prepare answers to supplemental application questions
for a job. Review the profile and the pasted questions, then decide whether the existing
materials already provide enough detail to answer each question fully.

{profile_block}

{stories_block}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}

=== APPLICATION QUESTIONS TO REVIEW ===
{questions_block}

=== YOUR TASK ===

For each question, determine whether the profile and story notes already supply sufficient
detail to write a strong, specific answer. For any question where important details are
missing, generate 1–2 targeted clarifying questions the applicant can answer to fill the gap.
Deduplicate across questions. When the materials already suffice, return an empty list.

Output ONLY a JSON object with this exact key:

{{"clarifying_questions": ["<clarifying question>", ...]}}

No prose, no markdown fences."""

    try:
        response = call_llm(prompt)
        data = _extract_json(response, array=False)
        return {
            "success": True,
            "clarifying_questions": data.get("clarifying_questions", []),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def answer_application_questions(
    profile: dict,
    questions: list[dict],
    clarifying_answers: list[dict],
    job_title: str,
    org_name: str,
    job_description: str,
    org_about: str = "",
) -> dict:
    """Draft answers to each employer application question, honouring length caps."""
    name = profile_mod.applicant_name(profile)
    profile_block = profile_mod.build_profile_summary(profile)
    stories_block = profile_mod.build_stories_block(profile)
    voice_block = profile_mod.build_voice_fingerprint(profile)

    questions_block_lines = []
    for i, q in enumerate(questions, 1):
        limit = q.get("limit")
        if limit:
            cap_str = f"  [LIMIT: {limit.get('value', '?')} {limit.get('unit', 'words')}]"
        else:
            cap_str = f"  [LIMIT: {_DEFAULT_ANSWER_LIMIT}]"
        questions_block_lines.append(f"{i}. {q['question']}{cap_str}")
    questions_block = "\n".join(questions_block_lines)

    if clarifying_answers:
        clarifying_section = "\n=== ADDITIONAL CONTEXT THE APPLICANT PROVIDED ===\n"
        for qa in clarifying_answers:
            clarifying_section += f"\nQ: {qa['question']}\nA: {qa['answer']}\n"
    else:
        clarifying_section = ""

    prompt = f"""You are drafting {name}'s answers to supplemental application questions
for a specific job. Match the voice precisely and rely only on facts present in the inputs below.

{voice_block}

{stories_block}

{profile_block}
{clarifying_section}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}

=== APPLICATION QUESTIONS (answer each in order) ===
{questions_block}

{_hard_constraints(name)}

5. LENGTH: Honour the per-question limit shown above. When the limit is in words, stay within
   that word count. When in characters, stay within that character count. Default ({_DEFAULT_ANSWER_LIMIT})
   applies when no explicit limit is given.

=== YOUR TASK ===

Write a direct, specific answer to each question in the applicant's voice and only verified facts.
Output ONLY a JSON array preserving the original question order:

[{{"question": "<question text>", "answer": "<drafted answer>"}}, ...]

No prose outside the JSON. No markdown fences."""

    try:
        response = call_llm(prompt)
        answers = _extract_json(response, array=True)
        return {"success": True, "answers": answers}
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_questions(
    profile: dict,
    job_title,
    org_name,
    job_description,
    org_about="",
    prior_qa: list[dict] | None = None,
):
    """Generate targeted questions to help the applicant surface useful details for the cover letter."""
    name = profile_mod.applicant_name(profile)
    prior_qa_section = ""
    if prior_qa:
        prior_qa_section = (
            "\n=== QUESTIONS ALREADY ANSWERED — do NOT ask these again ==="
            "\nThe applicant has ALREADY answered the following. Do NOT ask about them again;"
            " ask only about remaining gaps. If nothing meaningful remains, return an empty array [].\n"
        )
        for qa in prior_qa:
            prior_qa_section += f"\nQ: {qa['question']}\nA: {qa['answer']}\n"

    prompt = f"""You are helping {name} prepare to apply for a job. Before writing the cover letter,
gather useful details, specific accomplishments, and relevant stories that relate to this position.

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}
{prior_qa_section}
=== YOUR TASK ===

Analyze this job description and generate 4-5 specific, targeted questions that will help the
applicant surface useful details for the cover letter.

GUIDELINES:
- Ask about SPECIFIC experiences, projects, or accomplishments (not general questions)
- Each question should tie directly to a key requirement or skill in the job description
- Questions should prompt storytelling with details, numbers, and outcomes
- Focus on experiences that may NOT be fully detailed in a resume
- Ask about situations, challenges overcome, or impact created

EXAMPLE GOOD QUESTIONS:
- "Can you describe a time when you designed or improved a system? What metrics did you track and what decisions did the data inform?"
- "Tell me about a project where you built capacity in a team with limited resources. How did you approach it and what was the outcome?"

EXAMPLE BAD QUESTIONS:
- "Do you have experience with this?" (too general, yes/no)
- "What are your strengths?" (too generic, not job-specific)

Respond with ONLY a JSON array of 4-5 question strings, no other text:
["Question 1", "Question 2", "Question 3", "Question 4", "Question 5"]
"""

    try:
        response = call_llm(prompt)
        questions = _extract_json(response, array=True)
        return {"success": True, "questions": questions}
    except Exception as e:
        return {"success": False, "error": str(e)}


def polish_cover_letter(draft: str, profile: dict) -> str:
    """Second pass: scrub AI tells and tighten voice across the whole cover letter.

    The cover letter is now generated on its own (no résumé/fit sections appended), so
    the polish pass operates on the entire draft rather than a sliced-out section.
    """
    draft = (draft or "").strip()
    if not draft:
        return draft
    voice_block = profile_mod.build_voice_fingerprint(profile)

    polish_prompt = f"""You are revising a draft cover letter to remove AI tells and tighten the
voice match. Here is the writer's voice fingerprint:

{voice_block}

Here is the draft cover letter to revise:

---DRAFT---
{draft}
---END DRAFT---

Your task: rewrite the cover letter to fix any of the following, while preserving substance,
structure, and every factual claim:
1. Phrases on the "Do NOT use" list — replace with voice-matching alternatives.
2. Negative/contrastive parallelism — "it's not X, it's Y", "not just X, but Y", "X rather than Y". This is the single most common AI tell; rewrite every instance as a direct, positive statement.
3. Generic AI cadence — triadic flourishes, hollow superlatives, meta-statements about being thrilled or excited, copulative-dodging verbs ("serves as", "stands as" → "is"), and trailing "-ing" padding clauses ("...positioning me to...", "...underscoring my commitment").
4. Buzzword filler and stock openers — leverage, utilize, delve, robust, seamless, results-driven, proven track record, passionate; "I hope this finds you well", "I am writing to express my interest". Replace with plain, specific language.
5. Sentences that don't sound like the voice exemplars — adjust rhythm, register, and connective phrasing.
6. Summary "buttons" — any paragraph (not just the closing) that ends on a flourish restating or elevating its point. Cut the flourish; let the concrete sentence be the last one. For the final paragraph specifically, replace a summarizing close with a characteristic closer.

Constraints:
- Do not invent new facts, numbers, organizations, or stories. Every concrete claim must already be in the draft.
- Keep the same paragraphs and overall flow; this is a voice pass, not a structural rewrite.
- Output ONLY the revised cover letter — no preamble, no explanation, no markdown fences, no after-notes."""

    polished = call_llm(polish_prompt).strip()
    return polished or draft


def _format_experience_section(
    name: str, experience_answers, *, add_use_prompt: bool = False
) -> str:
    if not experience_answers:
        return ""
    suffix = " (USE THESE)" if add_use_prompt else ""
    section = f"\n=== {name.upper()}'S USEFUL DETAILS FOR THIS ROLE{suffix} ===\n"
    for qa in experience_answers:
        section += f"\nQ: {qa['question']}\nA: {qa['answer']}\n"
    return section


def _build_cover_letter_prompt(
    profile: dict,
    job_title: str,
    org_name: str,
    job_description: str,
    org_about: str,
    additional_notes: str,
    experience_answers,
    application_answers: list[dict] | None = None,
) -> str:
    name = profile_mod.applicant_name(profile)
    profile_block = profile_mod.build_profile_summary(profile)
    voice_block = profile_mod.build_voice_fingerprint(profile)
    stories_block = profile_mod.build_stories_block(profile)

    experience_section = _format_experience_section(name, experience_answers, add_use_prompt=True)

    application_answers_section = ""
    if application_answers:
        application_answers_section = (
            "\n=== APPLICATION ANSWERS THE APPLICANT IS ALREADY SUBMITTING FOR THIS ROLE ===\n"
            "The cover letter must NOT duplicate this content; cover different ground.\n"
        )
        for qa in application_answers:
            application_answers_section += f"\nQ: {qa['question']}\nA: {qa['answer']}\n"

    return f"""You are helping {name} write a tailored cover letter for a specific job. Match
{name}'s voice precisely and rely only on facts present in the inputs below.

{voice_block}

{stories_block}

{profile_block}
{experience_section}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}

Additional Notes from the applicant:
{additional_notes if additional_notes else "None"}
{application_answers_section}
{_hard_constraints(name)}

=== YOUR TASK ===

Write a complete, tailored cover letter for {name} applying to this position. Output ONLY the
cover letter — no section headers, no preamble, no explanation, no markdown fences, no after-notes.

- DO NOT simply repeat or rephrase content from the resume
- USE the specific stories and answers shared above; add details and context not already in the resume
- Reference the organization's mission/values if provided
- Keep it to one page (about 4 paragraphs of substantive prose)
- Use today's date
- Address to "Dear Hiring Manager" unless a name is known
- Close with the applicant's standard pattern (see voice fingerprint)"""


def _build_coaching_prompt(
    profile: dict,
    job_title: str,
    org_name: str,
    job_description: str,
    org_about: str,
    experience_answers,
) -> str:
    name = profile_mod.applicant_name(profile)
    profile_block = profile_mod.build_profile_summary(profile)
    stories_block = profile_mod.build_stories_block(profile)

    experience_section = _format_experience_section(name, experience_answers)

    return f"""You are coaching {name} on how to position themselves for a specific job. Base every
suggestion only on the materials below — never invent experience the applicant doesn't show.

{profile_block}

{stories_block}
{experience_section}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}

=== YOUR TASK ===

Produce two sections, in this order, with the headers exactly as shown:

## 1. RÉSUMÉ TAILORING SUGGESTIONS

Based on the job requirements, suggest:
- Which points from the background to emphasize or move to the top
- Any bullets that should be reworded to better match job keywords (give the rewrite verbatim)
- Skills to highlight
- Any gaps to address in the application

## 2. INTERVIEW PREPARATION

Provide:
- Match score (0-100) with a one-sentence explanation
- Top 3 strengths the applicant brings to this role
- Top 2-3 likely concerns the hiring side will raise, each with a concrete reframe
- 4-5 interview talking points grounded in the applicant's real experience. For each, mark how strongly the applicant's own materials support it — **Strong** (clear evidence in resume/stories), **Moderate** (partial or related evidence), or **Thin** (needs a concrete example the applicant should prepare) — so the applicant knows what is solid and what to shore up before the interview.

Format your response with clear headers using ## for main sections and --- for subsections.
Do not invent numbers, organizations, dates, or stories beyond what the materials show."""


def _application_answers_appendix(application_answers: list[dict] | None) -> str:
    """Render the applicant's already-drafted employer answers as an output section.

    Appended verbatim (not regenerated) so the answers the user reviewed/edited in the
    "Employer application questions" step travel with the cover letter in one document.
    """
    if not application_answers:
        return ""
    lines = ["## 4. EMPLOYER APPLICATION QUESTIONS", ""]
    for qa in application_answers:
        question = (qa.get("question") or "").strip()
        answer = (qa.get("answer") or "").strip()
        if not question and not answer:
            continue
        if question:
            lines.append(f"**{question}**")
            lines.append("")
        if answer:
            lines.append(answer)
            lines.append("")
    return "\n".join(lines).strip()


def generate_cover_letter(
    profile: dict,
    job_title,
    org_name,
    job_description,
    org_about="",
    additional_notes="",
    experience_answers=None,
    application_answers: list[dict] | None = None,
    polish: bool = True,
) -> dict:
    """Generate a tailored cover letter (only) via the selected provider.

    Résumé tailoring + interview prep now live in generate_coaching(); this returns the
    letter alone, with any already-drafted employer answers appended verbatim.
    """
    prompt = _build_cover_letter_prompt(
        profile,
        job_title,
        org_name,
        job_description,
        org_about,
        additional_notes,
        experience_answers,
        application_answers,
    )
    try:
        draft = call_llm(prompt)
        final = polish_cover_letter(draft, profile) if polish else draft.strip()
        appendix = _application_answers_appendix(application_answers)
        if appendix:
            final = f"{final.rstrip()}\n\n{appendix}"
        return {
            "success": True,
            "content": final,
            "polished": polish,
            "job_title": job_title,
            "org_name": org_name,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "job_title": job_title,
            "org_name": org_name,
        }


def generate_coaching(
    profile: dict,
    job_title,
    org_name,
    job_description,
    org_about="",
    experience_answers=None,
) -> dict:
    """Generate résumé-tailoring suggestions + interview prep via the selected provider."""
    prompt = _build_coaching_prompt(
        profile,
        job_title,
        org_name,
        job_description,
        org_about,
        experience_answers,
    )
    try:
        content = call_llm(prompt).strip()
        if not content:
            return {"success": False, "error": "the model returned an empty response"}
        return {
            "success": True,
            "content": content,
            "job_title": job_title,
            "org_name": org_name,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_interview_followup(
    profile: dict,
    question: str,
    user_answer: str,
    prior_qa: list[dict],
    job_title: str,
    org_name: str,
    job_description: str,
    org_about: str = "",
) -> dict:
    """Generate a coaching follow-up for an interview practice answer."""
    name = profile_mod.applicant_name(profile)
    voice_block = profile_mod.build_voice_fingerprint(profile)
    profile_block = profile_mod.build_profile_summary(profile)

    prior_section = ""
    if prior_qa:
        prior_section = "\n=== PREVIOUS Q&A IN THIS SESSION ===\n"
        for qa in prior_qa:
            prior_section += f"\nQ: {qa['question']}\nA: {qa['answer']}\n"

    prompt = f"""You are coaching {name} in a mock interview. They just answered a question.
Provide brief, specific feedback on their answer, then ask the next likely interview question.

{voice_block}

{profile_block}

=== TARGET JOB ===
Job Title: {job_title}
Organization: {org_name}

Job Description:
{job_description}

About the Organization:
{org_about if org_about else "Not provided"}
{prior_section}
=== CURRENT QUESTION & ANSWER ===
Q: {question}
A: {user_answer}

=== YOUR TASK ===

1. Give 1-2 sentences of coaching feedback on the answer (what worked, what to improve).
2. Ask the next likely interview question for this role.

Output ONLY a JSON object:
{{"feedback": "<coaching feedback>", "next_question": "<next interview question>"}}

No prose outside the JSON. No markdown fences."""

    try:
        response = call_llm(prompt)
        data = _extract_json(response, array=False)
        return {
            "success": True,
            "feedback": data.get("feedback", ""),
            "next_question": data.get("next_question", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
