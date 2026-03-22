"""Post-processor that remaps LLM-generated citations to real bibliography registry entries.

LLM often ignores instructions to use specific source numbers and instead:
1. Generates its own sequential [1]-[N] per section
2. Fabricates bibliography blocks with fake book references
3. Uses inconsistent numbering across sections

This module fixes all of that by:
1. Extracting LLM bibliography blocks (fake sources with descriptive text)
2. Fuzzy-matching each fake source to the closest real registry entry
3. Building old→new number mappings per section
4. Applying mappings to all inline [N] citations in text
5. Stripping all bibliography blocks and headers
"""

import re

import structlog

from shared.schemas.pipeline import BibliographyRegistry, SectionContent

logger = structlog.get_logger()

# Headers that LLM sometimes adds before bibliography blocks
_BIB_HEADER_PATTERNS = [
    r"^\s*Библиографически[ей]\s+(ссылк|списо)[а-яё]*\s*:?\s*$",
    r"^\s*Список\s+(использованн|литерату)[а-яё]*\s*:?\s*$",
    r"^\s*Источники\s*:?\s*$",
    r"^\s*Литература\s*:?\s*$",
    r"^\s*References\s*:?\s*$",
]
_BIB_HEADER_RE = re.compile("|".join(_BIB_HEADER_PATTERNS), re.IGNORECASE)

# Reference line: [N] followed by substantial text (a fake source entry)
_REF_LINE_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.{15,})$")

# Inline citation in text: [N]
_INLINE_CITE_RE = re.compile(r"\[(\d{1,3})\]")

# Section heading patterns that LLM might prepend to body text
_SECTION_HEADING_PATTERNS = [
    # "РАЗДЕЛ: 2.2 Title..." or "Раздел 2.2 Title"
    re.compile(r"^\s*(?:РАЗДЕЛ|Раздел)\s*:?\s*\d", re.IGNORECASE),
    # "1.1 Title" or "1.1. Title" at the very start
    re.compile(r"^\s*\d+\.\d+\.?\s+"),
    # "Глава N" or "ГЛАВА N"
    re.compile(r"^\s*(?:ГЛАВА|Глава)\s+\d", re.IGNORECASE),
]


def fix_citations(
    sections: list[SectionContent],
    bibliography: BibliographyRegistry,
) -> list[SectionContent]:
    """Fix all citation issues in sections using the real bibliography registry.

    This is the main post-processing entry point. It:
    1. Extracts fake bibliography blocks from each section
    2. Maps fake source entries to real registry entries
    3. Remaps inline [N] citations in text
    4. Strips bibliography blocks, headers, and duplicate section headings
    5. Returns cleaned sections ready for DOCX generation

    Args:
        sections: Written sections with potentially broken citations.
        bibliography: Real bibliography registry from research sources.

    Returns:
        Cleaned sections with citations mapped to registry numbers.
    """
    if not bibliography.entries:
        logger.warning("citation_fixer_no_registry", sections=len(sections))
        return sections

    registry_size = len(bibliography.entries)
    result: list[SectionContent] = []
    total_remapped = 0
    total_invalid = 0

    for section in sections:
        content = section.content

        # Step 1: Extract bibliography block (fake sources)
        fake_refs, clean_body = _extract_bibliography_block(content)

        # Step 2: Strip bibliography headers
        clean_body = _strip_bibliography_headers(clean_body)

        # Step 3: Strip duplicate section heading from body text
        clean_body = _strip_section_heading(clean_body, section.section_title)

        # Step 4: Build old→new mapping via fuzzy matching
        mapping = _build_citation_mapping(fake_refs, bibliography)

        # Step 5: Find all citations in text and remap
        remapped_text, remapped_count, invalid_count = _remap_citations(
            clean_body, mapping, registry_size
        )

        total_remapped += remapped_count
        total_invalid += invalid_count

        # Step 6: Extract final citation list
        citations = list(set(re.findall(r"\[(\d+)\]", remapped_text)))

        result.append(SectionContent(
            chapter_number=section.chapter_number,
            section_title=section.section_title,
            content=remapped_text,
            citations=citations,
            word_count=len(remapped_text.split()),
        ))

    logger.info(
        "citation_fixer_complete",
        sections=len(sections),
        total_remapped=total_remapped,
        total_invalid=total_invalid,
        registry_size=registry_size,
    )

    return result


def _extract_bibliography_block(
    text: str,
) -> tuple[dict[int, str], str]:
    """Extract bibliography block from end of section text.

    Returns:
        Tuple of (local_num → ref_text mapping, clean body without block).
    """
    lines = text.split("\n")

    # Scan backwards to find reference block
    ref_start_idx = len(lines)
    consecutive_refs = 0

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if _REF_LINE_RE.match(line):
            consecutive_refs += 1
            ref_start_idx = i
        elif _BIB_HEADER_RE.match(line):
            # Include the header in the block to be stripped
            ref_start_idx = i
            break
        else:
            break

    if consecutive_refs == 0:
        return {}, text

    # Extract reference entries
    refs: dict[int, str] = {}
    for i in range(ref_start_idx, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        m = _REF_LINE_RE.match(line)
        if m:
            refs[int(m.group(1))] = m.group(2).strip()

    # Clean body
    body_lines = lines[:ref_start_idx]
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    return refs, "\n".join(body_lines)


def _strip_bibliography_headers(text: str) -> str:
    """Remove standalone bibliography header lines from text."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if _BIB_HEADER_RE.match(line.strip()):
            continue
        cleaned.append(line)
    # Remove trailing empty lines
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned)


def _strip_section_heading(text: str, section_title: str) -> str:
    """Strip duplicate section heading from the start of body text.

    Handles various formats:
    - "1.1 Title" / "1.1. Title"
    - "РАЗДЕЛ: 1.1 Title"
    - Exact section_title match
    - "ВВЕДЕНИЕ" / "ЗАКЛЮЧЕНИЕ" (case-insensitive)
    """
    stripped = text.lstrip()
    if not stripped:
        return text

    # Check for exact section title match at start (case-insensitive)
    title_upper = section_title.upper().strip()
    if stripped.upper().startswith(title_upper):
        after = stripped[len(title_upper):]
        after = after.lstrip(" \t\n\r.:;-—")
        if after:
            return after

    # Check for section heading patterns
    for pattern in _SECTION_HEADING_PATTERNS:
        m = pattern.match(stripped)
        if m:
            # Find end of first line (the heading line)
            first_newline = stripped.find("\n")
            if first_newline > 0:
                after = stripped[first_newline:].lstrip("\n\r")
                if after:
                    return after

    # Check for "ВВЕДЕНИЕ" / "ЗАКЛЮЧЕНИЕ" style headings
    for heading in ["ВВЕДЕНИЕ", "ЗАКЛЮЧЕНИЕ"]:
        if stripped.upper().startswith(heading):
            after = stripped[len(heading):]
            after = after.lstrip(" \t\n\r.:;-—")
            if after:
                return after

    return text


def _build_citation_mapping(
    fake_refs: dict[int, str],
    bibliography: BibliographyRegistry,
) -> dict[int, int]:
    """Map fake LLM citation numbers to real registry numbers.

    Uses fuzzy keyword matching between fake reference text and real source titles.

    Args:
        fake_refs: Mapping of local_num → fake reference text from LLM.
        bibliography: Real bibliography registry.

    Returns:
        Mapping of old_num → new_registry_num.
    """
    if not fake_refs:
        return {}

    mapping: dict[int, int] = {}
    used_registry_nums: set[int] = set()

    for local_num, fake_text in fake_refs.items():
        best_match = _find_best_match(fake_text, bibliography, used_registry_nums)
        if best_match is not None:
            mapping[local_num] = best_match
            used_registry_nums.add(best_match)
        else:
            logger.warning(
                "citation_mapping_skipped",
                local_num=local_num,
                fake_text=fake_text[:80],
                message=f"Citation [{local_num}] could not be mapped to any registry entry and will remain unresolved.",
            )

    if mapping:
        logger.info(
            "citation_mapping_built",
            fake_refs=len(fake_refs),
            mapped=len(mapping),
        )

    return mapping


def _find_best_match(
    fake_text: str,
    bibliography: BibliographyRegistry,
    used: set[int],
) -> int | None:
    """Find the best matching real source for a fake reference text.

    Uses keyword overlap scoring between the fake text and real source titles.
    """
    fake_words = _extract_keywords(fake_text)
    if not fake_words:
        return None

    best_score = 0.0
    best_num = None

    for entry in bibliography.entries:
        if entry.number in used:
            continue
        entry_words = _extract_keywords(entry.title)
        if not entry_words:
            continue
        # Calculate Jaccard-like similarity
        overlap = fake_words & entry_words
        union = fake_words | entry_words
        score = len(overlap) / len(union) if union else 0.0
        if score > best_score:
            best_score = score
            best_num = entry.number

    # Only accept matches with some overlap
    if best_score >= 0.15 and best_num is not None:
        return best_num

    logger.warning(
        "citation_match_below_threshold",
        fake_text=fake_text[:80],
        best_score=round(best_score, 3),
        message=f"Could not map citation reference '{fake_text[:80]}' to any registry entry (best score: {best_score:.3f}). Citation will be unresolved.",
    )
    return None


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text for matching.

    Filters out short words and common stopwords.
    """
    words = re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", text.lower())
    # Common Russian/English stopwords to ignore
    stopwords = {
        "для", "при", "как", "что", "это", "его", "или", "они",
        "все", "так", "уже", "было", "быть", "были", "будет",
        "она", "эти", "этот", "этой", "более",
        "the", "and", "for", "with", "that", "this", "from",
        "are", "was", "has", "have", "not", "but", "can",
    }
    return {w for w in words if w not in stopwords and len(w) >= 3}


def _remap_citations(
    text: str,
    mapping: dict[int, int],
    registry_size: int,
) -> tuple[str, int, int]:
    """Remap inline [N] citations in text using the mapping.

    For citations that can't be mapped, assigns available registry numbers
    in round-robin fashion to ensure all citations point to real sources.

    Returns:
        Tuple of (remapped text, count of remapped citations, count of invalid citations).
    """
    # Find all unique citation numbers in text
    all_cited = set(int(m) for m in re.findall(r"\[(\d{1,3})\]", text))
    if not all_cited:
        return text, 0, 0

    # Build complete mapping: ensure every cited number maps to a valid registry number
    complete_mapping: dict[int, int] = {}
    used_targets: set[int] = set(mapping.values())

    # First, apply the fuzzy-matched mapping
    for old_num, new_num in mapping.items():
        if old_num in all_cited:
            complete_mapping[old_num] = new_num

    # For unmapped citations, assign round-robin from available registry numbers
    available = [
        n for n in range(1, registry_size + 1)
        if n not in used_targets
    ]
    available_idx = 0

    for cited_num in sorted(all_cited):
        if cited_num in complete_mapping:
            continue
        if 1 <= cited_num <= registry_size:
            # Already a valid registry number — keep it
            complete_mapping[cited_num] = cited_num
        elif available:
            # Assign next available registry number
            complete_mapping[cited_num] = available[available_idx % len(available)]
            available_idx += 1
        else:
            # No available numbers and citation is out of range — keep original.
            # Silently replacing with a modulo-derived number would create many-to-one
            # mappings (e.g. [6],[11],[16] all → [1] when registry_size=5), corrupting
            # the bibliography. Better to leave the invalid number visible in the document.
            logger.warning(
                "citation_no_valid_mapping",
                citation=cited_num,
                registry_size=registry_size,
                message=f"Citation [{cited_num}] has no valid mapping and no fallback — keeping original number. Registry size: {registry_size}",
            )
            complete_mapping[cited_num] = cited_num

    # Log when all citations are identity-mapped (no bibliography block found)
    identity_mapped = sum(1 for old, new in complete_mapping.items() if old == new)
    if identity_mapped == len(complete_mapping) and len(complete_mapping) > 0 and not mapping:
        logger.warning(
            "citations_identity_mapped",
            count=identity_mapped,
            registry_size=registry_size,
            hint="LLM did not generate bibliography block — citations point to sources by position",
        )

    # Apply mapping
    remapped_count = 0
    invalid_count = 0

    def _replace(match: re.Match) -> str:
        nonlocal remapped_count, invalid_count
        old_num = int(match.group(1))
        new_num = complete_mapping.get(old_num)
        if new_num is not None and new_num != old_num:
            remapped_count += 1
            return f"[{new_num}]"
        elif new_num is None:
            invalid_count += 1
            return match.group(0)
        return match.group(0)

    result = re.sub(r"\[(\d{1,3})\]", _replace, text)
    return result, remapped_count, invalid_count


