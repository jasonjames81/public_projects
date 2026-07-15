# Setting Up with Gemini Notebooks

One-time setup (~10 minutes). Free tier works great.

## Steps

1. Go to [gemini.google.com](https://gemini.google.com) and sign up or log in
2. Click **Notebooks** in the left sidebar → **New notebook**
3. Name it something like "Job Applications"
4. Upload your core assets as **Sources**:
   - Your resume/CV (PDF or DOCX)
   - *(Optional)* LinkedIn profile — to include it, open your own profile on linkedin.com, click **More → Save to PDF**, then upload that PDF. (A URL or exported text also works.)
   - 2-4 recent writing samples — ideally past cover letters and reports (essays, blog posts, or emails also work), anything in your natural voice. The assistant uses these to build your voice fingerprint on first run, and matches a cover letter's formatting if you include one.
5. Add the project instructions: open the **⋮** menu next to NotebookLM (top-right) → **Notebook settings** → **Instructions**, and paste the contents of [project-instructions-gemini.md](project-instructions-gemini.md) — no edits needed; your name comes from your uploaded Sources.
6. For each new application, start a **new chat** within the notebook and paste the [kickoff message](kickoff-template.md) (or the [interview-prep message](interview-prep-template.md) to prep for a role you applied to elsewhere)

[Screenshot: Notebooks sidebar with "Create Notebook" button highlighted]

[Screenshot: Notebook with uploaded Sources visible]

[Screenshot: Notebook chat with kickoff message]

## How it works

Gemini Notebooks are a structured workspace — you upload core assets (resume, LinkedIn, writing samples, and optionally a voice fingerprint) as permanent Sources, then start a new chat for each application. The Sources stay loaded across chats, so you don't re-upload everything each time.

Notebooks sync with NotebookLM, so you can also access your materials there.

## Free tier limits

- 100 notebooks, 50 sources per notebook
- 50 chat queries per day (resets the next day)
- 32k context window
- Works across web, Android, and iOS

## Model notes

Gemini uses the latest available model — no selection needed.

## Tips

- If Gemini can't fetch a URL you paste, it'll ask you to paste the text instead. This is normal.
- Start a **new chat** for each application to keep context clean.
- You can add or replace sources later if you update your resume or voice fingerprint.
