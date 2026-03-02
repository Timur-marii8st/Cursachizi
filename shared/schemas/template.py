"""ГОСТ template schemas for document formatting."""

from pydantic import BaseModel, Field


class FontConfig(BaseModel):
    """Font configuration for a document element."""

    name: str = "Times New Roman"
    size_pt: float = 14.0
    bold: bool = False
    italic: bool = False
    color: str = "000000"


class MarginConfig(BaseModel):
    """Page margin configuration in millimeters."""

    top_mm: float = 20.0
    bottom_mm: float = 20.0
    left_mm: float = 30.0
    right_mm: float = 15.0


class HeadingStyle(BaseModel):
    """Style for a heading level."""

    level: int = Field(ge=1, le=4)
    font: FontConfig = Field(default_factory=FontConfig)
    alignment: str = "center"  # center, left, justify
    space_before_pt: float = 0.0
    space_after_pt: float = 12.0
    numbering: bool = True
    uppercase: bool = False


class ParagraphStyle(BaseModel):
    """Style for body paragraphs."""

    font: FontConfig = Field(default_factory=FontConfig)
    alignment: str = "justify"
    first_line_indent_mm: float = 12.5
    line_spacing: float = 1.5
    space_after_pt: float = 0.0


class PageNumbering(BaseModel):
    """Page numbering configuration."""

    enabled: bool = True
    position: str = "bottom_center"  # bottom_center, bottom_right, top_center, top_right
    start_from: int = 1
    font: FontConfig = Field(
        default_factory=lambda: FontConfig(size_pt=12.0),
    )


class BibliographyStyle(BaseModel):
    """Bibliography / references section formatting."""

    format: str = "gost_7_1_2003"  # ГОСТ 7.1-2003
    numbering: str = "brackets"  # [1], [2], ...
    sort_order: str = "appearance"  # appearance, alphabetical


class GostTemplate(BaseModel):
    """Complete ГОСТ-compliant document template configuration.

    Default values match ГОСТ 7.32-2017 standard for research reports,
    which is the most commonly used format for курсовые работы.
    """

    id: str = "gost_7_32_2017"
    name: str = "ГОСТ 7.32-2017"
    description: str = "Стандартный формат для отчётов о научно-исследовательской работе"

    # Page setup
    page_width_mm: float = 210.0  # A4
    page_height_mm: float = 297.0  # A4
    margins: MarginConfig = Field(default_factory=MarginConfig)

    # Typography
    body: ParagraphStyle = Field(default_factory=ParagraphStyle)
    heading_1: HeadingStyle = Field(
        default_factory=lambda: HeadingStyle(
            level=1,
            font=FontConfig(size_pt=16.0, bold=True),
            alignment="center",
            space_before_pt=0.0,
            space_after_pt=12.0,
            uppercase=True,
        ),
    )
    heading_2: HeadingStyle = Field(
        default_factory=lambda: HeadingStyle(
            level=2,
            font=FontConfig(size_pt=14.0, bold=True),
            alignment="left",
            space_before_pt=12.0,
            space_after_pt=6.0,
        ),
    )
    heading_3: HeadingStyle = Field(
        default_factory=lambda: HeadingStyle(
            level=3,
            font=FontConfig(size_pt=14.0, bold=False, italic=True),
            alignment="left",
            space_before_pt=6.0,
            space_after_pt=6.0,
        ),
    )

    # Page numbering
    page_numbering: PageNumbering = Field(default_factory=PageNumbering)

    # Bibliography
    bibliography: BibliographyStyle = Field(default_factory=BibliographyStyle)

    # Structural requirements
    requires_title_page: bool = True
    requires_table_of_contents: bool = True
    requires_introduction: bool = True
    requires_conclusion: bool = True
    requires_bibliography: bool = True
    min_bibliography_entries: int = 15
