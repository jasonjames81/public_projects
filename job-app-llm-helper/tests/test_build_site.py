import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
sys.path.insert(0, str(SITE))

import build_site as bs  # noqa: E402


def test_extract_below_divider():
    md = "# Title\n\nintro\n\n---\n\nreal body\nmore\n"
    assert bs.extract_below_divider(md) == "real body\nmore"


def test_extract_message_body():
    md = "# Title\n\ntip\n\n---\n\nbody line 1\nbody line 2\n\n---\n\n## Tips\n- x\n"
    assert bs.extract_message_body(md) == "body line 1\nbody line 2"


def test_render_block_escapes():
    out = bs.render_block('a < b & "c"')
    assert "&lt;" in out and "&amp;" in out and "&quot;" in out
    assert out.startswith('<pre class="paste-block">')
    assert out.endswith("</pre>")


def test_inject_replaces_region_and_is_idempotent():
    html = "X<!-- INJECT:foo -->OLD<!-- /INJECT:foo -->Y"
    once = bs.inject(html, "foo", "NEW")
    assert once == "X<!-- INJECT:foo -->NEW<!-- /INJECT:foo -->Y"
    twice = bs.inject(once, "foo", "NEW")
    assert twice == once


def test_inject_preserves_backslashes():
    html = "<!-- INJECT:b -->X<!-- /INJECT:b -->"
    block = bs.render_block(r"path C:\Users \d+ \1 done")
    out = bs.inject(html, "b", block)
    assert r"C:\Users" in out and r"\d+" in out and r"\1" in out


def test_assemble_instructions_joins_core_and_delta(tmp_path):
    guide = tmp_path
    (guide / "project-instructions-core.md").write_text(
        "# header\n\n---\n\nCORE BODY\n", encoding="utf-8"
    )
    (guide / "platform-delta-claude.md").write_text(
        "# header\n\n---\n\nDELTA BODY\n", encoding="utf-8"
    )
    assert bs.assemble_instructions(guide, "claude") == "CORE BODY\n\nDELTA BODY"


def test_committed_index_html_is_current():
    """The committed index.html must equal a fresh build from the source markdown."""
    project_dir = SITE.parent
    current = (SITE / "index.html").read_text(encoding="utf-8")
    assert bs.build(project_dir) == current, (
        "site/index.html is stale — run `python site/build_site.py` and commit the result"
    )


def test_committed_per_platform_md_is_current():
    """Each committed project-instructions-<platform>.md must equal a fresh assembly."""
    guide = SITE.parent / "platform-guide"
    for key, label, loc in bs.PLATFORMS:
        current = (guide / f"project-instructions-{key}.md").read_text(encoding="utf-8")
        assert bs.assembled_md(guide, key, label, loc) == current, (
            f"project-instructions-{key}.md is stale — run "
            "`python site/build_site.py` and commit the result"
        )
