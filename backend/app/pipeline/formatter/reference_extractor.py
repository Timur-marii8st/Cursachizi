"""Extract inline references from LLM-generated section text and build a
unified bibliography with globally renumbered citations.

LLM often appends a block of references at the end of each section like:

    [1] Russell, S. J. Artificial Intelligence. Pearson, 2021.
    [2] Kaplan, A. Siri, Siri... Business Horizons, 2019.

This module:
1. Extracts those reference blocks from each section's content
2. Deduplicates references across sections (fuzzy title match)
3. Assigns global sequential numbers
4. Renumbers inline citations [N] in the text to match global numbers
5. Returns cleaned sections + ordered bibliography list
"""

import re
from dataclasses import dataclass, field

import structlog

from shared.schemas.pipeline import SectionContent

logger = structlog.get_logger()

# Pattern for a reference line: starts with [N] or N. followed by author/title
_REF_LINE_RE = re.compile(
    r"^\s*\[?(\d{1,3})\]?\s*[.)]?\s*(.+)$"
)

# Pattern for a block of consecutive reference lines at the end of text
# A reference line: starts with [N] and has substantial text after it
_REF_BLOCK_LINE_RE = re.compile(
    r"^\s*\[(\d{1,3})\]\s+(.{15,})$"
)


@dataclass
class ExtractedReference:
    """A single bibliographic reference extracted from section text."""

    local_number: int
    text: str
    source_section: str = ""


@dataclass
class RenumberingResult:
    """Result of extracting and renumbering references across all sections."""

    sections: list[SectionContent] = field(default_factory=list)
    bibliography: list[str] = field(default_factory=list)


def strip_reference_blocks(sections: list[SectionContent]) -> list[SectionContent]:
    """Strip trailing bibliography blocks from section text WITHOUT renumbering.

    Use this when a BibliographyRegistry is provided and inline citations
    already use correct global numbers. We only want to remove any residual
    bibliography blocks the LLM might have appended despite being told not to.
    """
    result = []
    for section in sections:
        _refs, clean_body = _split_reference_block(section.content)
        if _refs:
            logger.info(
                "stripped_residual_ref_block",
                section=section.section_title[:50],
                refs_stripped=len(_refs),
            )
        result.append(SectionContent(
            chapter_number=section.chapter_number,
            section_title=section.section_title,
            content=clean_body,
            citations=section.citations,
            word_count=len(clean_body.split()),
        ))
    return result


def extract_and_renumber_references(
    sections: list[SectionContent],
) -> RenumberingResult:
    """Extract references from all sections and build a unified bibliography.

    Returns new SectionContent objects with cleaned text and renumbered
    inline citations, plus an ordered bibliography list.
    """
    # Step 1: Extract reference blocks from each section
    all_refs: list[ExtractedReference] = []
    cleaned_sections: list[tuple[SectionContent, dict[int, str]]] = []

    for section in sections:
        content = section.content
        ref_block, body_text = _split_reference_block(content)

        local_refs: dict[int, str] = {}
        for num, text in ref_block:
            local_refs[num] = text.strip()
            all_refs.append(ExtractedReference(
                local_number=num,
                text=text.strip(),
                source_section=section.section_title,
            ))

        cleaned_sections.append((section, local_refs))
        # Store body_text temporarily — we'll use it after building the global map

    # Step 2: Deduplicate references and assign global numbers
    global_refs: list[str] = []
    ref_text_to_global: dict[str, int] = {}

    for ref in all_refs:
        normalized = _normalize_ref(ref.text)
        # Check for duplicate (fuzzy match on first 60 chars of normalized text)
        existing_num = _find_duplicate(normalized, ref_text_to_global)
        if existing_num is not None:
            continue
        global_num = len(global_refs) + 1
        global_refs.append(ref.text)
        ref_text_to_global[normalized] = global_num

    # Step 3: Build local→global mapping per section and renumber inline citations
    result_sections: list[SectionContent] = []

    for section, local_refs in cleaned_sections:
        content = section.content
        _, clean_body = _split_reference_block(content)
        # Build local→global map for this section
        local_to_global: dict[int, int] = {}
        for local_num, ref_text in local_refs.items():
            normalized = _normalize_ref(ref_text)
            existing = _find_duplicate(normalized, ref_text_to_global)
            if existing is not None:
                local_to_global[local_num] = existing

        # Renumber inline citations in the body text
        renumbered_text = _renumber_citations(clean_body, local_to_global)

        result_sections.append(SectionContent(
            chapter_number=section.chapter_number,
            section_title=section.section_title,
            content=renumbered_text,
            citations=section.citations,
            word_count=len(renumbered_text.split()),
        ))

    logger.info(
        "references_extracted",
        total_refs=len(global_refs),
        sections_processed=len(sections),
    )

    return RenumberingResult(
        sections=result_sections,
        bibliography=global_refs,
    )


def _split_reference_block(text: str) -> tuple[list[tuple[int, str]], str]:
    """Split text into (reference_entries, body_text).

    Finds the reference block at the end of the text — consecutive lines
    starting with [N] pattern.

    Returns:
        Tuple of (list of (number, ref_text), cleaned body text without refs).
    """
    lines = text.split("\n")

    # Scan backwards to find the start of reference block
    ref_start_idx = len(lines)
    consecutive_refs = 0

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            # Empty line — continue scanning (refs might have gaps)
            if consecutive_refs > 0:
                continue
            else:
                # No refs found yet, keep going
                continue
        if _REF_BLOCK_LINE_RE.match(line):
            consecutive_refs += 1
            ref_start_idx = i
        else:
            # Non-reference line encountered
            if consecutive_refs >= 1:
                # We found at least 1 reference — stop here
                break
            else:
                # No refs found, this is just body text
                break

    if consecutive_refs == 0:
        return [], text

    # Extract reference lines
    refs: list[tuple[int, str]] = []
    for i in range(ref_start_idx, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        m = _REF_BLOCK_LINE_RE.match(line)
        if m:
            refs.append((int(m.group(1)), m.group(2)))

    # Body text is everything before the reference block
    body_lines = lines[:ref_start_idx]
    # Remove trailing empty lines
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    body_text = "\n".join(body_lines)
    return refs, body_text


def _normalize_ref(text: str) -> str:
    """Normalize reference text for deduplication."""
    # Lowercase, remove extra spaces, remove punctuation differences
    normalized = text.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    # Remove leading/trailing punctuation
    normalized = normalized.strip("., ;:")
    return normalized


def _find_duplicate(
    normalized: str, existing: dict[str, int]
) -> int | None:
    """Find if a reference already exists (fuzzy match on first 60 chars)."""
    key = normalized[:60]
    for existing_norm, num in existing.items():
        if existing_norm[:60] == key:
            return num
    return None


def _renumber_citations(text: str, local_to_global: dict[int, int]) -> str:
    """Replace inline [N] citations with global numbers."""
    if not local_to_global:
        return text

    def _replace(match: re.Match) -> str:
        local_num = int(match.group(1))
        global_num = local_to_global.get(local_num)
        if global_num is not None:
            return f"[{global_num}]"
        return match.group(0)

    return re.sub(r"\[(\d{1,3})\]", _replace, text)
