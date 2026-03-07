"""Tests for the visual template matcher and document renderer."""

import json

import pytest

from backend.app.llm.provider import LLMMessage, LLMResponse
from backend.app.pipeline.formatter.visual_matcher import VisualTemplateMatcher
from shared.schemas.pipeline import (
    Outline,
    OutlineChapter,
    SectionContent,
    Source,
    VisualMatchResult,
)
from shared.schemas.template import GostTemplate


class MockVisionProvider:
    """Mock OpenRouter provider that supports generate_with_vision."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_index = 0
        self.calls: list[dict] = []

    def set_responses(self, responses: list[str]) -> None:
        self._responses = responses
        self._call_index = 0

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model})
        content = ""
        if self._call_index < len(self._responses):
            content = self._responses[self._call_index]
            self._call_index += 1
        return LLMResponse(content=content, model=model or "mock", input_tokens=100, output_tokens=50)

    async def generate_with_vision(
        self,
        prompt: str,
        images: list[bytes],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append({"prompt": prompt, "images_count": len(images), "model": model})
        content = ""
        if self._call_index < len(self._responses):
            content = self._responses[self._call_index]
            self._call_index += 1
        return LLMResponse(content=content, model=model or "mock", input_tokens=200, output_tokens=100)


class MockRenderer:
    """Mock document renderer that returns fake PNGs."""

    def __init__(self, page_count: int = 2, fail: bool = False) -> None:
        self._page_count = page_count
        self._fail = fail
        self.render_count = 0

    async def render_pages(self, docx_bytes: bytes, max_pages: int = 3) -> list[bytes]:
        self.render_count += 1
        if self._fail:
            return []
        # Return fake PNG bytes
        return [b"\x89PNG\x00fake_page" for _ in range(min(self._page_count, max_pages))]


class TestVisualTemplateMatcher:
    @pytest.fixture
    def vision_llm(self) -> MockVisionProvider:
        return MockVisionProvider()

    @pytest.fixture
    def renderer(self) -> MockRenderer:
        return MockRenderer()

    @pytest.fixture
    def matcher(self, vision_llm: MockVisionProvider, renderer: MockRenderer) -> VisualTemplateMatcher:
        return VisualTemplateMatcher(
            vision_llm=vision_llm,
            renderer=renderer,
            vision_model="google/gemini-2.5-flash",
        )

    @pytest.fixture
    def sample_outline(self) -> Outline:
        return Outline(
            title="Test Paper",
            chapters=[
                OutlineChapter(number=1, title="Chapter 1", subsections=["1.1 Section"]),
            ],
        )

    @pytest.fixture
    def sample_sections(self) -> list[SectionContent]:
        return [
            SectionContent(chapter_number=0, section_title="Введение", content="Intro " * 50, word_count=50),
            SectionContent(chapter_number=1, section_title="1.1 Section", content="Body " * 100, word_count=100),
            SectionContent(chapter_number=99, section_title="Заключение", content="Conclusion " * 30, word_count=30),
        ]

    @pytest.fixture
    def sample_sources(self) -> list[Source]:
        return [
            Source(url="https://example.com/1", title="Source 1", snippet="Snippet 1"),
        ]

    async def test_analyze_reference(
        self,
        matcher: VisualTemplateMatcher,
        vision_llm: MockVisionProvider,
    ) -> None:
        vision_llm.set_responses([
            json.dumps({
                "font_name": "Times New Roman",
                "font_size_pt": 12,
                "heading_font_size_pt": 14,
                "heading_bold": True,
                "heading_alignment": "center",
                "heading_uppercase": True,
                "line_spacing": 1.5,
                "first_line_indent_mm": 12.5,
                "margins": {"top_mm": 20, "bottom_mm": 20, "left_mm": 30, "right_mm": 15},
                "text_alignment": "justify",
                "page_numbering_position": "bottom_center",
            })
        ])

        template = await matcher.analyze_reference(b"fake_docx_bytes")

        assert template.body.font.size_pt == 12.0
        assert template.body.font.name == "Times New Roman"
        assert template.margins.left_mm == 30.0
        assert len(vision_llm.calls) == 1

    async def test_analyze_reference_render_failure(
        self,
        vision_llm: MockVisionProvider,
    ) -> None:
        """When rendering fails, should return default template."""
        failing_renderer = MockRenderer(fail=True)
        matcher = VisualTemplateMatcher(
            vision_llm=vision_llm,
            renderer=failing_renderer,
        )

        template = await matcher.analyze_reference(b"fake_docx")
        # Should get default template
        assert template.body.font.size_pt == 14.0  # Default ГОСТ

    async def test_analyze_reference_invalid_json(
        self,
        matcher: VisualTemplateMatcher,
        vision_llm: MockVisionProvider,
    ) -> None:
        """When vision model returns invalid JSON, should return default template."""
        vision_llm.set_responses(["not valid json at all"])

        template = await matcher.analyze_reference(b"fake_docx")
        assert template.body.font.size_pt == 14.0  # Default

    async def test_match_iteratively_converges(
        self,
        matcher: VisualTemplateMatcher,
        vision_llm: MockVisionProvider,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_sources: list[Source],
    ) -> None:
        """Test that matching stops when score >= target."""
        # First iteration: score 9.0 (above target 8.5) → should converge immediately
        vision_llm.set_responses([
            json.dumps({
                "score": 9.0,
                "issues": ["Форматирование соответствует образцу"],
                "fixes": {},
            })
        ])

        doc_bytes, template, results = await matcher.match_iteratively(
            reference_docx_bytes=b"ref_docx",
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_sources,
            initial_template=GostTemplate(),
            max_iterations=3,
            target_score=8.5,
        )

        assert len(results) == 1
        assert results[0].score == 9.0
        assert results[0].converged is True
        assert doc_bytes is not None

    async def test_match_iteratively_max_iterations(
        self,
        matcher: VisualTemplateMatcher,
        vision_llm: MockVisionProvider,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_sources: list[Source],
    ) -> None:
        """Test that matching stops at max_iterations even without convergence."""
        # All iterations score below target
        low_score_response = json.dumps({
            "score": 5.0,
            "issues": ["Font size mismatch"],
            "fixes": {"font_size_pt": 12},
        })
        vision_llm.set_responses([low_score_response, low_score_response])

        doc_bytes, template, results = await matcher.match_iteratively(
            reference_docx_bytes=b"ref_docx",
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_sources,
            initial_template=GostTemplate(),
            max_iterations=2,
            target_score=8.5,
        )

        assert len(results) == 2
        assert all(r.converged is False for r in results)

    async def test_match_iteratively_render_failure(
        self,
        vision_llm: MockVisionProvider,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_sources: list[Source],
    ) -> None:
        """When reference render fails, should return basic doc without visual matching."""
        failing_renderer = MockRenderer(fail=True)
        matcher = VisualTemplateMatcher(
            vision_llm=vision_llm,
            renderer=failing_renderer,
        )

        doc_bytes, template, results = await matcher.match_iteratively(
            reference_docx_bytes=b"ref_docx",
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_sources,
            initial_template=GostTemplate(),
            max_iterations=3,
        )

        assert len(results) == 0  # No iterations run
        assert doc_bytes is not None  # Fallback doc generated


class TestVisualMatchResultSchema:
    def test_default_values(self) -> None:
        result = VisualMatchResult(iteration=1)
        assert result.score == 0.0
        assert result.issues == []
        assert result.fixes_applied == []
        assert result.converged is False

    def test_score_bounds(self) -> None:
        result = VisualMatchResult(iteration=1, score=10.0)
        assert result.score == 10.0

        with pytest.raises(Exception):
            VisualMatchResult(iteration=1, score=11.0)

        with pytest.raises(Exception):
            VisualMatchResult(iteration=1, score=-1.0)


class TestParseComparison:
    def test_valid_json(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        response = json.dumps({"score": 7.5, "issues": ["Font mismatch"]})
        result = matcher._parse_comparison(response, iteration=1)

        assert result.score == 7.5
        assert len(result.issues) == 1
        assert result.iteration == 1

    def test_code_fenced_json(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        response = '```json\n{"score": 8.0, "issues": []}\n```'
        result = matcher._parse_comparison(response, iteration=2)

        assert result.score == 8.0
        assert result.iteration == 2

    def test_invalid_json(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        result = matcher._parse_comparison("not json", iteration=1)

        assert result.score == 0
        assert result.issues == ["Parse error"]


class TestApplyFixes:
    def test_apply_font_size(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        template = GostTemplate()
        response = json.dumps({"fixes": {"font_size_pt": 12}})

        new_template = matcher._apply_fixes(template, response)
        assert new_template.body.font.size_pt == 12.0
        # Original unchanged
        assert template.body.font.size_pt == 14.0

    def test_apply_margins(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        template = GostTemplate()
        response = json.dumps({"fixes": {"margins": {"left_mm": 25, "right_mm": 10}}})

        new_template = matcher._apply_fixes(template, response)
        assert new_template.margins.left_mm == 25.0
        assert new_template.margins.right_mm == 10.0

    def test_apply_heading_fixes(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        template = GostTemplate()
        response = json.dumps({"fixes": {"heading_bold": False, "heading_uppercase": False}})

        new_template = matcher._apply_fixes(template, response)
        assert new_template.heading_1.font.bold is False
        assert new_template.heading_1.uppercase is False

    def test_no_fixes(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        template = GostTemplate()
        response = json.dumps({"fixes": {}})

        new_template = matcher._apply_fixes(template, response)
        assert new_template.body.font.size_pt == template.body.font.size_pt

    def test_invalid_response(self) -> None:
        matcher = VisualTemplateMatcher.__new__(VisualTemplateMatcher)
        template = GostTemplate()

        new_template = matcher._apply_fixes(template, "broken")
        assert new_template is template  # Returns original on error
