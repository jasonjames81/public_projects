# Setting Up with Claude Projects

One-time setup (~10 minutes). Free tier works.

## Steps

1. Go to [claude.ai](https://claude.ai) and sign up or log in
2. Click **Projects** in the left sidebar → **New Project**
3. Name it something like "Job Applications" (adding a description is optional), then click **Create project**
4. Open the project and, under **Files**, upload:
   - Your resume/CV (PDF or DOCX)
   - *(Optional)* LinkedIn profile — to include it, open your own profile on linkedin.com, click **More → Save to PDF**, then upload that PDF. (A URL or exported text also works.)
   - 2-4 recent writing samples — ideally past cover letters and reports (essays, blog posts, or emails also work), anything in your natural voice. The assistant uses these to build your voice fingerprint on first run, and matches a cover letter's formatting if you include one.
   - If you used the local helper app, copy the fingerprint block it generated (it starts with === YOUR VOICE FINGERPRINT ===), save it as voice-fingerprint.txt, and upload it with your other files.
5. Under **Project Instructions**, paste the contents of [project-instructions-claude.md](project-instructions-claude.md) — no edits needed; your name comes from your uploaded files.
6. Pick the strongest model your plan offers (see below)
7. Start a new chat → paste the [kickoff message](kickoff-template.md) for your first application (or the [interview-prep message](interview-prep-template.md) to prep for a role you applied to elsewhere)

## Model notes

| Plan | Model | Notes |
|---|---|---|
| Free | Sonnet | Good for cover letters and voice matching. |
| Pro ($20/mo) | Opus | Best for nuanced voice matching and long-form writing. Recommended for frequent applicants. |

## Free tier limits

- 5 projects, 20 files per project (30 MB each), Sonnet only
- Files persist across conversations

## Tips

- **First run:** The LLM will ask you to upload any missing materials and generate your voice fingerprint from your writing samples.
- The voice fingerprint makes cover letters sound like *you* instead of AI. Generate once, reuse forever.
- Start a **new chat** for each application to keep context clean.
