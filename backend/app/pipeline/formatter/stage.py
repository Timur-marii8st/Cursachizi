"""Complete formatting stage — template application and document generation."""

import structlog

from backend.app.pipeline.formatter.docx_generator import DocxGenerator
from shared.schemas.pipeline import (
    FactCheckResult,
    Outline,
    SectionContent,
    Source,
)
from shared.schemas.template import GostTemplate

logger = structlog.get_logger()


class FormatterStage:
    """Orchestrates document formatting and output generation."""

    def __init__(self, template: GostTemplate | None = None) -> None:
        self._template = template or GostTemplate()
        self._generator = DocxGenerator(self._template)

    def run(
        self,
        outline: Outline,
        sections: list[SectionContent],
        sources: list[Source],
        fact_check: FactCheckResult | None = None,
        university: str = "",
        discipline: str = "",
        author: str = "",
    ) -> bytes:
        """Generate the final .docx document.

        Returns:
            Bytes of the .docx file.
        """
        logger.info("formatting_stage_start", sections=len(sections))

        doc_bytes = self._generator.generate(
            outline=outline,
            sections=sections,
            sources=sources,
            fact_check=fact_check,
            university=university,
            discipline=discipline,
            author=author,
        )

        logger.info("formatting_stage_complete", size_kb=len(doc_bytes) // 1024)
        return doc_bytes
