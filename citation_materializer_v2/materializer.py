from __future__ import annotations

import copy

class CitationMaterializationError(ValueError):
    pass

# Lot 5a : closed, deterministic list of type (a) layout equivalences. Case is kept; punctuation
# and words are never tolerated. Matching only: the returned citation is always the source span.
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
DASHES = "‐‑‒–—―−"
SINGLE_QUOTES = "‘’‚‛′"
DOUBLE_QUOTES = "“”„‟«»″"
SOFT_HYPHEN = "­"
BREAK = " "  # source-only marker (never produced otherwise: whitespace is folded first)
NORMALIZATION_POLICY = "LAYOUT_TYPE_A_V2"


def _canonical(text: str, *, source: bool) -> tuple[str, list[int], set[str]]:
    """Canonical form, the start offset in ``text`` of each canonical character, and the kinds used.

    Whitespace runs (any Unicode space or line break) become one space; typographic dashes and
    quotes become ASCII; ligatures are decomposed; soft hyphens are dropped. In the source only, a
    hyphen followed by whitespace that contains a line break becomes BREAK (end-of-line hyphenation).
    """
    out: list[str] = []
    pos: list[int] = []
    kinds: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if source and (ch == "-" or ch in DASHES):
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] in "\r\n":
                while j < n and text[j].isspace():
                    j += 1
                out.append(BREAK)
                pos.append(i)
                i = j
                continue
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if j - i > 1 or ch != " ":
                kinds.add("WHITESPACE")
            out.append(" ")
            pos.append(i)
            i = j
            continue
        if ch == SOFT_HYPHEN:
            kinds.add("SOFT_HYPHEN")
        elif ch in LIGATURES:
            kinds.add("LIGATURE")
            for letter in LIGATURES[ch]:
                out.append(letter)
                pos.append(i)
        elif ch in DASHES:
            kinds.add("DASH")
            out.append("-")
            pos.append(i)
        elif ch in SINGLE_QUOTES:
            kinds.add("QUOTE_MARK")
            out.append("'")
            pos.append(i)
        elif ch in DOUBLE_QUOTES:
            kinds.add("QUOTE_MARK")
            out.append('"')
            pos.append(i)
        else:
            out.append(ch)
            pos.append(i)
        i += 1
    return "".join(out), pos, kinds


def canonical_quote(quote: str) -> str:
    return _canonical(quote, source=False)[0].strip(" ")


def _match_at(src: str, k: int, q: str) -> tuple[int, bool] | None:
    """Match q from src[k:]. BREAK accepts the word joined, the hyphen kept, or hyphen + space."""
    stack = [(k, 0, False)]
    while stack:
        i, j, used = stack.pop()
        if j == len(q):
            return i, used
        if i >= len(src):
            continue
        c = src[i]
        if c == BREAK:
            stack.append((i + 1, j, True))                  # "mo-<eol>mentum" quoted "momentum"
            if q[j] == "-":
                stack.append((i + 1, j + 1, True))          # "well-<eol>known" quoted "well-known"
                if j + 1 < len(q) and q[j + 1] == " ":
                    stack.append((i + 1, j + 2, True))      # quoted "well- known"
        elif c == q[j]:
            stack.append((i + 1, j + 1, used))
    return None


def find_layout_span(quote: str, excerpt: str) -> tuple[int, int, list[str]]:
    """Unique span of ``excerpt`` equal to ``quote`` up to type (a) layout differences.

    Returns (start, end, kinds used). Raises when absent or ambiguous.
    """
    if not isinstance(quote, str) or not quote.strip():
        raise CitationMaterializationError("QUOTE_REQUIRED")
    if not isinstance(excerpt, str) or not excerpt:
        raise CitationMaterializationError("EXCERPT_REQUIRED")
    q = canonical_quote(quote)
    if not q:
        raise CitationMaterializationError("QUOTE_EMPTY_AFTER_SPLIT")
    src, pos, _ = _canonical(excerpt, source=True)
    matches = []
    for k in range(len(src)):
        if src[k] != q[0] or (k > 0 and pos[k] == pos[k - 1]):
            continue  # never start on a line-break hyphen or inside a ligature
        found = _match_at(src, k, q)
        if found is None:
            continue
        e, used_break = found
        if e < len(pos) and pos[e] == pos[e - 1]:
            continue  # never end inside a ligature
        matches.append((k, e, used_break))
    if not matches:
        raise CitationMaterializationError("QUOTE_SPAN_NOT_FOUND")
    if len(matches) != 1:
        raise CitationMaterializationError(f"QUOTE_SPAN_AMBIGUOUS:{len(matches)}")
    k, e, used_break = matches[0]
    start, end = pos[k], pos[e - 1] + 1
    exact = excerpt[start:end]
    if exact == quote:
        return start, end, []
    kinds = _canonical(exact, source=True)[2] | _canonical(quote, source=False)[2]
    if used_break:
        kinds.add("LINE_END_HYPHENATION")
    if exact.strip() != exact or quote.strip() != quote:
        kinds.add("WHITESPACE")
    return start, end, sorted(kinds)


def _punctuation_only(chars: str) -> bool:
    return all(not c.isalnum() for c in chars)


def classify_quote_gap(quote, excerpt, other_excerpts=()) -> dict:
    """Lot 5a diagnostic of one citation against its passage. Counts and offsets only, never text.

    gap_type: EXACT ; a (layout only, accepted) ; b (punctuation added/removed/changed) ;
    c (words omitted, added or replaced) ; d (absent from the cited passage).
    """
    from difflib import SequenceMatcher
    if not isinstance(quote, str) or not quote.strip():
        return dict(gap_type="d", detail="QUOTE_EMPTY", quote_chars=0)
    row = dict(quote_chars=len(quote))
    if not isinstance(excerpt, str) or not excerpt:
        located = any(_found(quote, x) for x in other_excerpts)
        return dict(row, gap_type="d", detail="CITED_PASSAGE_NOT_TRANSMITTED" + ("_FOUND_IN_OTHER_PASSAGE" if located else ""))
    if quote in excerpt:
        return dict(row, gap_type="EXACT", chunk_start_character=excerpt.index(quote))
    try:
        start, end, kinds = find_layout_span(quote, excerpt)
        return dict(row, gap_type="a", kinds=kinds, chunk_start_character=start, chunk_end_character=end)
    except CitationMaterializationError as exc:
        if str(exc).startswith("QUOTE_SPAN_AMBIGUOUS"):
            return dict(row, gap_type="a", detail=str(exc))
    q = canonical_quote(quote)
    src = _canonical(excerpt, source=True)[0].replace(BREAK, "")
    longest = SequenceMatcher(None, q, src, autojunk=False).find_longest_match(0, len(q), 0, len(src))
    offset = max(0, longest.b - longest.a)
    window = src[offset:offset + len(q) + 40]
    ops = [o for o in SequenceMatcher(None, q, window, autojunk=False).get_opcodes() if o[0] != "equal"]
    if ops and ops[-1][0] == "insert" and ops[-1][1] == len(q):
        ops.pop()  # window longer than the quote
    if ops and ops[0][0] == "insert" and ops[0][1] == 0:
        ops.pop(0)
    equal = len(q) - sum(i2 - i1 for _, i1, i2, _, _ in ops)
    if not ops:
        return dict(row, gap_type="a", detail="LAYOUT_RESIDUAL")
    if equal < 0.6 * len(q):
        located = any(_found(quote, x) for x in other_excerpts)
        return dict(row, gap_type="d", detail="FOUND_IN_OTHER_PASSAGE" if located else "NOT_FOUND_IN_TRANSMITTED_PASSAGES",
                    matched_chars=max(equal, 0))
    words = [o for o in ops if not _punctuation_only(q[o[1]:o[2]] + window[o[3]:o[4]])]
    return dict(row, gap_type="c" if words else "b",
                changed_chars=sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in ops),
                differences=len(ops), word_differences=len(words),
                first_difference_in_quote=ops[0][1], chunk_window_start=offset)


def _found(quote, excerpt) -> bool:
    try:
        find_layout_span(quote, excerpt)
        return True
    except CitationMaterializationError as exc:
        return str(exc).startswith("QUOTE_SPAN_AMBIGUOUS")


def _exact_span_from_whitespace_normalized_quote(quote: str, excerpt: str) -> tuple[str, int, int]:
    start, end, _ = find_layout_span(quote, excerpt)
    return excerpt[start:end], start, end


def materialize_research_citations(raw_output: dict, research_context: list[dict]) -> tuple[dict, list[dict]]:
    if not isinstance(raw_output, dict):
        raise CitationMaterializationError("RAW_OUTPUT_NOT_MAPPING")
    citations = raw_output.get("citations")
    if not isinstance(citations, list) or not citations:
        raise CitationMaterializationError("CITATIONS_REQUIRED")

    allowed = {}
    for item in research_context:
        if not isinstance(item, dict):
            raise CitationMaterializationError("RESEARCH_CONTEXT_ITEM_NOT_MAPPING")
        sid = item.get("source_id")
        cid = item.get("chunk_id")
        excerpt = item.get("excerpt")
        if not isinstance(sid, str) or not isinstance(cid, str) or not isinstance(excerpt, str) or not excerpt:
            raise CitationMaterializationError("RESEARCH_CONTEXT_ITEM_INVALID")
        key = (sid, cid)
        if key in allowed and allowed[key] != excerpt:
            raise CitationMaterializationError("DUPLICATE_PAIR_WITH_DIFFERENT_EXCERPT")
        allowed[key] = excerpt

    result = copy.deepcopy(raw_output)
    audit = []
    seen = set()

    for index, citation in enumerate(result["citations"]):
        if not isinstance(citation, dict):
            raise CitationMaterializationError(f"CITATION_{index}_NOT_MAPPING")

        sid = citation.get("source_id")
        cid = citation.get("chunk_id")
        key = (sid, cid)
        if key not in allowed:
            raise CitationMaterializationError(f"CITATION_PAIR_NOT_IN_RESEARCH_CONTEXT:{sid}:{cid}")

        original_quote = citation.get("quote")
        start, end, kinds = find_layout_span(original_quote, allowed[key])
        exact_quote = allowed[key][start:end]

        citation_key = (sid, cid, exact_quote)
        if citation_key in seen:
            raise CitationMaterializationError("DUPLICATE_CITATION_AFTER_MATERIALIZATION")
        seen.add(citation_key)

        citation["quote"] = exact_quote
        audit.append({
            "index": index,
            "source_id": sid,
            "chunk_id": cid,
            "original_quote": original_quote,
            "materialized_quote": exact_quote,
            "quote_changed": original_quote != exact_quote,
            "change_is_whitespace_only": set(kinds) <= {"WHITESPACE"},
            "ligature_fi_equivalence_used": "LIGATURE" in kinds,
            "layout_equivalences_used": kinds,
            "normalization_policy": NORMALIZATION_POLICY,
            "chunk_start_character": start,
            "chunk_end_character": end,
            "materialized_quote_chars": len(exact_quote),
        })

    return result, audit
