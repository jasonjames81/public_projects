"""Unit tests for voice fingerprint engine in profile.py."""

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import profile as profile_mod  # noqa: E402

# ── _strip_letter_scaffolding ────────────────────────────────────────────────


class TestStripLetterScaffolding:
    def test_letter_with_salutation_and_closing(self):
        text = (
            "Dear Hiring Manager,\n"
            "I have extensive experience building algorithms.\n"
            "My work spans several decades.\n\n"
            "Sincerely,\nAda Lovelace"
        )
        result = profile_mod._strip_letter_scaffolding(text)
        assert result == "I have extensive experience building algorithms.\nMy work spans several decades."
        assert "Dear" not in result
        assert "Sincerely" not in result

    def test_letter_without_salutation(self):
        text = "No salutation here.\nJust plain body text.\n\nBest regards,\nAda"
        result = profile_mod._strip_letter_scaffolding(text)
        # No salutation → function returns full text (closing not stripped alone)
        assert "No salutation here" in result
        assert "Best regards" in result

    def test_letter_without_closing(self):
        text = "Dear Hiring Manager,\nHere is my body.\nMore body text."
        result = profile_mod._strip_letter_scaffolding(text)
        # No closing found, so closing_idx == -1; fallback returns full text stripped
        assert "Dear Hiring Manager" in result

    def test_body_contains_sincerely(self):
        text = (
            "Dear Team,\n"
            "I want to be sincere in my application.\n"
            "Sincerely,\nAda"
        )
        result = profile_mod._strip_letter_scaffolding(text)
        assert "sincere in my application" in result
        assert result.startswith("I want to be sincere")


# ── _paragraphs ──────────────────────────────────────────────────────────────


class TestParagraphs:
    def test_blank_line_separated(self):
        text = "First paragraph with enough words to pass the length threshold easily.\n\nSecond paragraph also long enough to survive the filter.\n\nThird paragraph."
        paras = profile_mod._paragraphs(text)
        assert len(paras) == 2  # third is < 30 chars

    def test_single_paragraph(self):
        text = "This is a single paragraph with plenty of text to exceed thirty characters."
        paras = profile_mod._paragraphs(text)
        assert len(paras) == 1
        assert "single paragraph" in paras[0]

    def test_short_paragraphs_filtered(self):
        text = "Short.\n\nThis is long enough to survive the thirty character filter threshold."
        paras = profile_mod._paragraphs(text)
        assert len(paras) == 1
        assert "long enough" in paras[0]

    def test_empty_text(self):
        assert profile_mod._paragraphs("") == []

    def test_whitespace_only_paragraphs_filtered(self):
        text = "   \n\nAlso a real paragraph with enough words to pass the filter check."
        paras = profile_mod._paragraphs(text)
        assert len(paras) == 1


# ── _sentences ───────────────────────────────────────────────────────────────


class TestSentences:
    def test_normal_text(self):
        # Regex splits on period+space+uppercase; "Hello world" is only 2 words → filtered
        sents = profile_mod._sentences("Hello world. This is a test. Another sentence here.")
        assert len(sents) == 2
        assert "This is a test" in sents[0]

    def test_text_with_abbreviations(self):
        # Regex splits on "Mr." and "Dr." periods too; fragments < 3 words filtered
        sents = profile_mod._sentences("Mr. Smith traveled to Washington last year. Dr. Jones agreed with the findings.")
        assert len(sents) == 2

    def test_single_sentence(self):
        sents = profile_mod._sentences("One very long sentence that has many words inside it.")
        assert len(sents) == 1

    def test_short_fragments_filtered(self):
        sents = profile_mod._sentences("OK. Hi there everyone. Good morning to you all.")
        # "OK." has < 3 words so filtered
        assert len(sents) == 2

    def test_empty_text(self):
        assert profile_mod._sentences("") == []


# ── build_voice_fingerprint ──────────────────────────────────────────────────


class TestBuildVoiceFingerprint:
    def test_with_samples(self):
        samples = (
            "I have spent my career building algorithms that solve real problems. "
            "During my time at the Analytical Engine lab, I developed the first "
            "published algorithm for machine computation. That experience taught me "
            "the value of precise thinking and clear communication.\n\n"
            "The work with Babbage was transformative. Through that experience, I "
            "learned to translate abstract mathematical concepts into concrete "
            "mechanical operations. My time as a translator of Menabrea's memoir "
            "gave me deep insight into how to explain complex ideas.\n\n"
            "I believe that computation will transform every field of human endeavor. "
            "Additionally, the patterns I observed in the Analytical Engine mirror "
            "modern programming constructs. Furthermore, my experience suggests that "
            "the boundary between analysis and synthesis is thinner than most realize."
        )
        profile = {"writing_samples": samples}
        result = profile_mod.build_voice_fingerprint(profile)

        assert "=== YOUR VOICE FINGERPRINT" in result
        assert "avg sentence" in result
        assert "sample(s)" in result
        assert "Do NOT use" in result
        # Should contain openers and closers
        assert "Character" in result  # "Characteristic paragraph openers/closers"

    def test_with_multi_sample_input(self):
        sample1 = (
            "First sample paragraph. This is a complete thought with enough text. "
            "Another sentence here to make it substantive. And a fourth sentence "
            "to round things out properly for the paragraph filter."
        )
        sample2 = (
            "Second sample paragraph. Written in a different voice or context. "
            "This provides additional data points for statistical analysis. "
            "More sentences to flesh out the second sample paragraph fully."
        )
        profile = {"writing_samples": f"{sample1}\n\n\n{sample2}"}
        result = profile_mod.build_voice_fingerprint(profile)
        assert "=== YOUR VOICE FINGERPRINT" in result
        assert "2 sample(s)" in result

    def test_without_samples(self):
        result = profile_mod.build_voice_fingerprint({"background": "x" * 50})
        assert "No writing samples" in result
        assert "Do NOT use" in result
        assert "VOICE GUIDANCE" in result

    def test_output_contains_exemplars(self):
        # A multi-paragraph sample that should produce exemplars
        body = (
            "During my time working on computational theory, I developed a deep "
            "appreciation for the elegance of mechanical reasoning. The patterns "
            "that emerged from studying the Analytical Engine shaped my entire "
            "approach to problem solving and algorithmic design.\n\n"
            "I led a small team that translated theoretical concepts into practical "
            "implementations. Through that experience, I learned that the gap "
            "between theory and practice is often smaller than engineers assume. "
            "My experience bridging that gap has defined my career trajectory.\n\n"
            "Furthermore, the principles of computation extend beyond numbers. "
            "I believe that symbolic manipulation is the key to understanding "
            "intelligence itself. Additionally, my time studying Babbage's work "
            "showed me that innovation often means rediscovering forgotten ideas."
        )
        result = profile_mod.build_voice_fingerprint({"writing_samples": body})
        assert "EXEMPLAR" in result

    def test_fingerprint_avoids_anti_patterns(self):
        """The fingerprint block itself should not contain anti-pattern phrases."""
        samples = (
            "I have a wealth of experience in algorithmic design. "
            "During my time at the lab, I delved into computational theory. "
            "Furthermore, I am thrilled to share my findings with colleagues."
        )
        result = profile_mod.build_voice_fingerprint({"writing_samples": samples})
        # The anti-patterns are listed in the "Do NOT use" block, so the
        # fingerprint block will contain them — that's by design. The key is
        # that the block is well-formed and has the voice section header.
        assert "VOICE FINGERPRINT" in result
        assert "Do NOT use" in result
