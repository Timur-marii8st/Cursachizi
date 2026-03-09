"""Headless document rendering — converts .docx to PNG screenshots.

Uses LibreOffice in headless mode to convert .docx → PDF,
then pdf2image (Poppler) to convert PDF pages → PNG images.

This works on servers without a display (no X11 required).
"""

import asyncio
import os
import tempfile

import structlog

logger = structlog.get_logger()


class DocumentRenderer:
    """Renders .docx documents to PNG page images without a display."""

    def __init__(
        self,
        libreoffice_path: str = "libreoffice",
        dpi: int = 150,
    ) -> None:
        self._libreoffice = libreoffice_path
        self._dpi = dpi

    async def render_pages(
        self,
        docx_bytes: bytes,
        max_pages: int = 3,
    ) -> list[bytes]:
        """Convert a .docx file to PNG images of its pages.

        Args:
            docx_bytes: The .docx file as bytes.
            max_pages: Maximum number of pages to render (to save resources).

        Returns:
            List of PNG image bytes, one per page (up to max_pages).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Write .docx to temp file
            docx_path = os.path.join(tmpdir, "document.docx")
            with open(docx_path, "wb") as f:
                f.write(docx_bytes)

            # Step 2: Convert .docx → PDF via LibreOffice headless
            pdf_path = os.path.join(tmpdir, "document.pdf")
            await self._docx_to_pdf(docx_path, tmpdir)

            if not os.path.exists(pdf_path):
                logger.error("libreoffice_conversion_failed", tmpdir=tmpdir)
                return []

            # Step 3: Convert PDF pages → PNG via pdf2image
            images = await self._pdf_to_images(pdf_path, max_pages)

            logger.info("document_rendered", pages=len(images), dpi=self._dpi)
            return images

    async def _docx_to_pdf(self, docx_path: str, output_dir: str) -> None:
        """Convert .docx to PDF using LibreOffice headless mode."""
        cmd = [
            self._libreoffice,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            docx_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

        if process.returncode != 0:
            logger.error(
                "libreoffice_error",
                returncode=process.returncode,
                stderr=stderr.decode()[:500],
            )

    async def _pdf_to_images(
        self, pdf_path: str, max_pages: int
    ) -> list[bytes]:
        """Convert PDF to PNG images using pdf2image."""
        # Import here to make pdf2image an optional dependency
        from pdf2image import convert_from_path

        # Run in executor since pdf2image is synchronous
        loop = asyncio.get_event_loop()
        pages = await loop.run_in_executor(
            None,
            lambda: convert_from_path(
                pdf_path,
                dpi=self._dpi,
                first_page=1,
                last_page=max_pages,
                fmt="png",
            ),
        )

        # Convert PIL images to PNG bytes
        import io
        result = []
        for page_img in pages:
            buf = io.BytesIO()
            page_img.save(buf, format="PNG")
            result.append(buf.getvalue())

        return result
