"""Visual template matching loop.

Takes a reference .docx (or its screenshots), takes screenshots of our generated .docx,
sends both to a vision model (Gemini via OpenRouter), gets format difference analysis,
applies corrections, and repeats until the format matches or max iterations reached.

Flow per iteration:
1. Render reference doc → PNG pages
2. Render our doc → PNG pages
3. Send both to vision model: "compare formatting, list differences"
4. Parse differences into actionable fixes
5. Apply fixes to our document
6. Re-render and check again (or stop if converged / max iterations)
"""

import json

import structlog

from backend.app.llm.openrouter import OpenRouterProvider
from backend.app.pipeline.formatter.document_renderer import DocumentRenderer
from backend.app.pipeline.formatter.docx_generator import DocxGenerator
from shared.schemas.pipeline import (
    Outline,
    SectionContent,
    Source,
    VisualMatchResult,
)
from shared.schemas.template import (
    FontConfig,
    GostTemplate,
    HeadingStyle,
    MarginConfig,
    ParagraphStyle,
)

logger = structlog.get_logger()

ANALYZE_REFERENCE_PROMPT = """Ты — эксперт по форматированию документов по российским стандартам ГОСТ.

Проанализируй скриншот(ы) этого документа-образца и опиши его форматирование МАКСИМАЛЬНО ТОЧНО.

Определи:
1. Шрифт основного текста (название, размер)
2. Шрифт заголовков (название, размер, жирный/обычный, выравнивание)
3. Межстрочный интервал (1.0 / 1.15 / 1.5 / 2.0)
4. Отступ первой строки абзаца (в мм, примерно)
5. Поля страницы (левое, правое, верхнее, нижнее в мм)
6. Выравнивание основного текста (по ширине / по левому краю)
7. Нумерация страниц (позиция: внизу по центру / внизу справа / вверху)
8. Заголовки: ПРОПИСНЫЕ или Обычные

Ответь строго в JSON:
{
  "font_name": "Times New Roman",
  "font_size_pt": 14,
  "heading_font_size_pt": 16,
  "heading_bold": true,
  "heading_alignment": "center",
  "heading_uppercase": true,
  "line_spacing": 1.5,
  "first_line_indent_mm": 12.5,
  "margins": {"top_mm": 20, "bottom_mm": 20, "left_mm": 30, "right_mm": 15},
  "text_alignment": "justify",
  "page_numbering_position": "bottom_center"
}"""

COMPARE_DOCUMENTS_PROMPT = """Ты — эксперт по форматированию документов по ГОСТ.

Сравни два документа. Первое изображение — ОБРАЗЕЦ (правильное форматирование).
Второе изображение — НАШ ДОКУМЕНТ (нужно проверить).

Найди ВСЕ различия в форматировании:
- Шрифт (название, размер)
- Поля страницы
- Межстрочный интервал
- Отступы абзацев
- Заголовки (размер, жирность, выравнивание, регистр)
- Нумерация страниц
- Любые другие визуальные отличия

Оцени соответствие по шкале от 0 до 10 (10 = идеально).

Ответь строго в JSON:
{
  "score": 7.5,
  "issues": [
    "Шрифт основного текста: у нас 14pt, в образце 12pt",
    "Левое поле: у нас 30мм, в образце 25мм"
  ],
  "fixes": {
    "font_size_pt": 12,
    "margins": {"left_mm": 25}
  }
}

Если различий нет или они минимальны (score >= 8.5), в issues напиши ["Форматирование соответствует образцу"]."""


class VisualTemplateMatcher:
    """Iteratively matches document formatting to a reference using vision AI.

    Uses a vision model (Gemini via OpenRouter) to visually compare
    a reference document's formatting with our generated document,
    then applies corrections until they match.
    """

    def __init__(
        self,
        vision_llm: OpenRouterProvider,
        renderer: DocumentRenderer | None = None,
        vision_model: str = "google/google/gemini-3.1-flash-lite-preview",
    ) -> None:
        self._vision_llm = vision_llm
        self._renderer = renderer or DocumentRenderer()
        self._vision_model = vision_model

    async def analyze_reference(
        self,
        reference_docx_bytes: bytes,
    ) -> GostTemplate:
        """Analyze a reference document and extract its formatting as a GostTemplate.

        Args:
            reference_docx_bytes: The reference .docx file bytes.

        Returns:
            GostTemplate with formatting extracted from the reference.
        """
        # Render reference to images
        ref_images = await self._renderer.render_pages(reference_docx_bytes, max_pages=2)

        if not ref_images:
            logger.warning("reference_render_failed, using default template")
            return GostTemplate()

        # Send to vision model
        response = await self._vision_llm.generate_with_vision(
            prompt=ANALYZE_REFERENCE_PROMPT,
            images=ref_images,
            model=self._vision_model,
            temperature=0.2,
            max_tokens=1024,
        )

        # Parse response into template
        return self._parse_template_response(response.content)

    async def match_iteratively(
        self,
        reference_docx_bytes: bytes,
        outline: Outline,
        sections: list[SectionContent],
        sources: list[Source],
        initial_template: GostTemplate,
        max_iterations: int = 3,
        target_score: float = 8.5,
        university: str = "",
        discipline: str = "",
    ) -> tuple[bytes, GostTemplate, list[VisualMatchResult]]:
        """Iteratively refine document formatting to match a reference.

        Args:
            reference_docx_bytes: Reference document bytes.
            outline: Coursework outline.
            sections: Written sections.
            sources: Sources for bibliography.
            initial_template: Starting template (from analyze_reference or default).
            max_iterations: Max refinement iterations (cost cap).
            target_score: Score threshold to stop iterating (0-10).
            university: University name.
            discipline: Discipline name.

        Returns:
            Tuple of (final_docx_bytes, final_template, iteration_results).
        """
        template = initial_template
        results: list[VisualMatchResult] = []

        # Render reference once
        ref_images = await self._renderer.render_pages(reference_docx_bytes, max_pages=2)
        if not ref_images:
            logger.warning("reference_render_failed, skipping visual matching")
            generator = DocxGenerator(template)
            doc_bytes = generator.generate(
                outline=outline, sections=sections, sources=sources,
                university=university, discipline=discipline,
            )
            return doc_bytes, template, results

        for iteration in range(1, max_iterations + 1):
            logger.info("visual_match_iteration", iteration=iteration, max=max_iterations)

            # Generate document with current template
            generator = DocxGenerator(template)
            doc_bytes = generator.generate(
                outline=outline, sections=sections, sources=sources,
                university=university, discipline=discipline,
            )

            # Render our document
            our_images = await self._renderer.render_pages(doc_bytes, max_pages=2)
            if not our_images:
                logger.warning("our_doc_render_failed", iteration=iteration)
                results.append(VisualMatchResult(
                    iteration=iteration, score=0, issues=["Failed to render document"],
                ))
                break

            # Compare with vision model
            all_images = ref_images + our_images
            comparison_prompt = (
                f"Изображения 1-{len(ref_images)}: ОБРАЗЕЦ.\n"
                f"Изображения {len(ref_images)+1}-{len(all_images)}: НАШ ДОКУМЕНТ.\n\n"
                + COMPARE_DOCUMENTS_PROMPT
            )

            response = await self._vision_llm.generate_with_vision(
                prompt=comparison_prompt,
                images=all_images,
                model=self._vision_model,
                temperature=0.2,
                max_tokens=1024,
            )

            # Parse comparison result
            match_result = self._parse_comparison(response.content, iteration)
            results.append(match_result)

            logger.info(
                "visual_match_result",
                iteration=iteration,
                score=match_result.score,
                issues=len(match_result.issues),
            )

            # Check convergence
            if match_result.score >= target_score:
                match_result.converged = True
                logger.info("visual_match_converged", score=match_result.score)
                break

            # Apply fixes for next iteration
            template = self._apply_fixes(template, response.content)

        # Final generation with the best template
        generator = DocxGenerator(template)
        final_bytes = generator.generate(
            outline=outline, sections=sections, sources=sources,
            university=university, discipline=discipline,
        )

        return final_bytes, template, results

    def _parse_template_response(self, response_text: str) -> GostTemplate:
        """Parse the vision model's analysis of a reference doc into a GostTemplate."""
        try:
            content = response_text.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)

            margins_data = data.get("margins", {})
            margins = MarginConfig(
                top_mm=margins_data.get("top_mm", 20),
                bottom_mm=margins_data.get("bottom_mm", 20),
                left_mm=margins_data.get("left_mm", 30),
                right_mm=margins_data.get("right_mm", 15),
            )

            font_name = data.get("font_name", "Times New Roman")
            font_size = data.get("font_size_pt", 14)

            body = ParagraphStyle(
                font=FontConfig(name=font_name, size_pt=font_size),
                alignment=data.get("text_alignment", "justify"),
                first_line_indent_mm=data.get("first_line_indent_mm", 12.5),
                line_spacing=data.get("line_spacing", 1.5),
            )

            heading_size = data.get("heading_font_size_pt", 16)
            heading_bold = data.get("heading_bold", True)
            heading_align = data.get("heading_alignment", "center")
            heading_upper = data.get("heading_uppercase", True)

            heading_1 = HeadingStyle(
                level=1,
                font=FontConfig(name=font_name, size_pt=heading_size, bold=heading_bold),
                alignment=heading_align,
                uppercase=heading_upper,
            )

            template = GostTemplate(
                margins=margins,
                body=body,
                heading_1=heading_1,
            )

            logger.info("template_extracted_from_reference", font=font_name, size=font_size)
            return template

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("template_parse_failed", error=str(e))
            return GostTemplate()

    def _parse_comparison(self, response_text: str, iteration: int) -> VisualMatchResult:
        """Parse the comparison response into a VisualMatchResult."""
        try:
            content = response_text.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)

            return VisualMatchResult(
                iteration=iteration,
                score=min(float(data.get("score", 0)), 10.0),
                issues=data.get("issues", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("comparison_parse_failed", error=str(e))
            return VisualMatchResult(iteration=iteration, score=0, issues=["Parse error"])

    def _apply_fixes(self, template: GostTemplate, response_text: str) -> GostTemplate:
        """Apply formatting fixes from the comparison response to the template."""
        try:
            content = response_text.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)
            fixes = data.get("fixes", {})

            if not fixes:
                return template

            # Create a mutable copy via model_copy
            new_template = template.model_copy(deep=True)

            def _safe_float(val: object, fallback: float | None = None) -> float | None:
                """Convert to float, returning fallback if value is not numeric."""
                try:
                    return float(val)  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    logger.warning("skipping_non_numeric_fix", value=str(val)[:50])
                    return fallback

            # Apply font fixes
            if "font_size_pt" in fixes:
                v = _safe_float(fixes["font_size_pt"])
                if v is not None:
                    new_template.body.font.size_pt = v
            if "font_name" in fixes:
                new_template.body.font.name = fixes["font_name"]

            # Apply margin fixes
            if "margins" in fixes:
                m = fixes["margins"]
                for attr in ("left_mm", "right_mm", "top_mm", "bottom_mm"):
                    if attr in m:
                        v = _safe_float(m[attr])
                        if v is not None:
                            setattr(new_template.margins, attr, v)

            # Apply spacing fixes
            if "line_spacing" in fixes:
                v = _safe_float(fixes["line_spacing"])
                if v is not None:
                    new_template.body.line_spacing = v
            if "first_line_indent_mm" in fixes:
                v = _safe_float(fixes["first_line_indent_mm"])
                if v is not None:
                    new_template.body.first_line_indent_mm = v

            # Apply heading fixes
            if "heading_font_size_pt" in fixes:
                v = _safe_float(fixes["heading_font_size_pt"])
                if v is not None:
                    new_template.heading_1.font.size_pt = v
            if "heading_bold" in fixes:
                new_template.heading_1.font.bold = bool(fixes["heading_bold"])
            if "heading_alignment" in fixes:
                new_template.heading_1.alignment = fixes["heading_alignment"]
            if "heading_uppercase" in fixes:
                new_template.heading_1.uppercase = bool(fixes["heading_uppercase"])

            logger.info("fixes_applied", fixes=list(fixes.keys()))
            return new_template

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("fix_apply_failed", error=str(e))
            return template
