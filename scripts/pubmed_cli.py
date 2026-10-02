"""
PubMed Retrieve CLI — end-to-end pipeline: search → fetch → save → summarize.

Usage:
    python pubmed_cli.py --query "diabetes AND exercise" \
                         --start-date 2020/01/01 \
                         --end-date 2024/12/31 \
                         --max-results 50 \
                         --output pubmed_results.csv

    # with the Phase 5 academic deck chain:
    python pubmed_cli.py -f query.txt -s 2021/01/01 -e 2026/10/02 \
                         -o output/pubmed_results.csv \
                         --deck --deck-topic "radiomics in HCC prognosis"

    # one-shot: retrieval + deck + review evidence base + review skeleton
    python pubmed_cli.py -f query.txt -s 2021/01/01 -e 2026/10/02 \
                         -o output/pubmed_results.csv \
                         --full --deck-topic "影像组学在肝细胞癌预后预测中的应用"
"""

import argparse
import json
import sys
import os
from datetime import datetime
from collections import Counter

# Ensure the skill scripts dir is on the path so we can import pubmed_script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubmed_script import (
    search_pubmed_ids_edat,
    fetch_pubmed_details,
    save_results_csv,
)


def summarize_results(results, query, start_date, end_date):
    """Print a human-readable summary table of search results."""
    if not results:
        print("\n" + "=" * 70)
        print("  No results found.")
        print("=" * 70)
        return

    print("\n" + "=" * 70)
    print("  PubMed Search Summary")
    print("=" * 70)
    print(f"  Query:        {query}")
    print(f"  Date range:   {start_date} - {end_date}")
    print(f"  Search date:  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Total found:  {len(results)}")
    print("-" * 70)

    # --- Journal distribution ---
    journals = Counter(r.get("Journal", "Unknown") for r in results)
    print(f"\n  [Journal Distribution (Top 10)]:")
    for j, c in journals.most_common(10):
        print(f"     {c:4d}  {j}")

    # --- Year distribution ---
    years = Counter()
    for r in results:
        date_str = r.get("Date", "")
        if date_str and date_str != "Unknown":
            y = date_str.split("/")[0]
            if y.isdigit():
                years[y] += 1
    if years:
        print(f"\n  [Year Distribution]:")
        for y in sorted(years.keys()):
            print(f"     {y}: {years[y]}")

    # --- Article list ---
    print(f"\n  [Articles]:")
    print(f"  {'#':<4} {'PMID':<10} {'Year':<6} {'Journal':<25} {'Title (truncated)'}")
    print(f"  {'-'*4} {'-'*10} {'-'*6} {'-'*25} {'-'*35}")
    for i, r in enumerate(results, 1):
        pmid = r.get("Pmid", "")
        year = (r.get("Date", "?") or "?")[:4]
        journal = (r.get("Journal", "") or "")[:24]
        title = (r.get("Title", "") or "")[:55]
        print(f"  {i:<4} {pmid:<10} {year:<6} {journal:<25} {title}")


def build_deck_outputs(args, query, end_date):
    """Phase 5: chain the deck content model + HTML deck renderer after retrieval."""
    import types
    import re

    try:
        import deck_content as dc
        import deck_build as db
    except ImportError as exc:
        print(f"\n[deck] skipped: cannot import deck modules ({exc})")
        return

    out_dir = args.deck_out_dir or (os.path.dirname(os.path.abspath(args.output)) or ".")
    os.makedirs(out_dir, exist_ok=True)

    ns = types.SimpleNamespace(
        csv=args.output,
        out_dir=out_dir,
        topic=args.deck_topic or "",
        query=query,
        query_file=None,
        start=args.start_date,
        end=end_date,
        max_results=args.max_results,
        max_articles=8,
        topics_file=args.topics_file,
        search_date=datetime.now().strftime("%Y-%m-%d"),
    )

    print("\n=== Building academic deck (Phase 5) ===")
    content = dc.build_content(ns)
    json_path, md_path = dc.write_outputs(content, out_dir)
    print(f"   content model: {json_path}")
    print(f"   outline:       {md_path}")

    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (args.deck_topic or "deck")).strip("_")[:48] or "deck"
    deck_path = os.path.join(out_dir, f"{slug}_deck.html")

    review = None
    review_path = None
    if args.review:
        review_path = build_review_outputs(args, query, end_date)
        if review_path:
            with open(review_path, "r", encoding="utf-8") as fh:
                review = json.load(fh)

    pages = db.write_deck(content, deck_path, review=review)
    print(f"   html deck:     {deck_path}  ({pages} pages")
    if review:
        print("                    + systematic-review pages)")
    else:
        print(")")
    print("   next: run deck_validate.py, then hand deck_outline.md to the PPT step.")


def build_review_outputs(args, query, end_date):
    """Phase 6: build the systematic-review evidence base from the retrieved CSV."""
    import types

    try:
        import review_evidence as re
    except ImportError as exc:
        print(f"\n[review] skipped: cannot import review_evidence ({exc})")
        return None

    out_dir = args.review_out_dir or (os.path.dirname(os.path.abspath(args.output)) or ".")
    os.makedirs(out_dir, exist_ok=True)

    ns = types.SimpleNamespace(
        csv=args.output,
        out_dir=out_dir,
        topic=args.deck_topic or "",
        query=query,
        query_file=None,
        start=args.start_date,
        end=end_date,
        max_results=args.max_results,
        corpus_size=args.review_corpus_size,
        per_theme=args.review_per_theme,
        search_date=datetime.now().strftime("%Y-%m-%d"),
    )

    print("\n=== Building systematic-review evidence base (Phase 6) ===")
    ev = re.build(ns)
    json_path = os.path.join(out_dir, "review_evidence.json")
    md_path = os.path.join(out_dir, "review_corpus.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        import json as _json
        _json.dump(ev, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(re.render_corpus_md(
            ev["meta"], ev["prisma"], ev["levels"], ev["corpus"],
            ev["numbers"], ev["matrix"], ev["gaps"],
            {k: __import__("re").compile(v, __import__("re").IGNORECASE)
             for k, v in re.REVIEW_THEMES.items()}
        ) + "\n")
    print(f"   evidence json: {json_path}")
    print(f"   corpus digest: {md_path}")

    # Phase 6.2 -- compose the submission-ready skeleton. Everything
    # deterministic is written by the script; only interpretive prose is left
    # behind as WRITE-BLOCK briefs.
    try:
        import review_compose as rc
    except ImportError as exc:
        print(f"   [review] skeleton skipped: cannot import review_compose ({exc})")
        return json_path

    print("\n=== Composing review skeleton (Phase 6.2) ===")
    pmids = [r["pmid"] for r in ev["corpus"]]
    refs, mapping = rc.build_references(args.output, pmids)
    draft = rc.compose(ev, refs, mapping, args.deck_topic or ev["meta"]["topic"], "")

    draft_path = os.path.join(out_dir, "review_draft.md")
    refs_path = os.path.join(out_dir, "review_references.md")
    map_path = os.path.join(out_dir, "review_refmap.json")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(draft)
    with open(refs_path, "w", encoding="utf-8") as fh:
        fh.write("## 参考文献\n\n" + "\n".join(refs) + "\n")
    with open(map_path, "w", encoding="utf-8") as fh:
        import json as _json
        _json.dump(mapping, fh, ensure_ascii=False, indent=2)

    blocks = draft.count("<!-- WRITE-BLOCK")
    print(f"   draft:         {draft_path}")
    print(f"   references:    {refs_path}  ({len(refs)} entries)")
    print(f"   refmap:        {map_path}")
    print(f"   WRITE-BLOCKs:  {blocks}  -> fill all of them, then run:")
    print(f"     python review_check.py <review.md> --evidence {json_path} \\")
    print(f"            --refmap {map_path} --strict")
    return json_path


def main():
    # Ensure UTF-8 output on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="PubMed Retrieve — search PubMed and produce a summary table."
    )
    query_group = parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument(
        "--query", "-q", help="PubMed query string (supports full PubMed syntax)"
    )
    query_group.add_argument(
        "--query-file", "-f", help="Read PubMed query from file (avoids shell quoting issues)"
    )
    parser.add_argument(
        "--start-date", "-s", default="2000/01/01",
        help="Start date (YYYY/MM/DD), default: 2000/01/01"
    )
    parser.add_argument(
        "--end-date", "-e", default=None,
        help="End date (YYYY/MM/DD), default: today"
    )
    parser.add_argument(
        "--max-results", "-m", type=int, default=2000,
        help="Max results to fetch, default: 2000"
    )
    parser.add_argument(
        "--output", "-o", default="pubmed_results.csv",
        help="Output CSV filename, default: pubmed_results.csv"
    )
    parser.add_argument(
        "--deck", action="store_true",
        help="After retrieval, also build the Phase 5 deck content model + HTML deck"
    )
    parser.add_argument(
        "--deck-topic", default="",
        help="Deck title / topic summary (used with --deck)"
    )
    parser.add_argument(
        "--deck-out-dir", default=None,
        help="Directory for deck outputs (default: same directory as --output)"
    )
    parser.add_argument(
        "--topics-file", default=None,
        help="JSON {name: regex} overriding the default topic buckets (used with --deck)"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="After the deck, also build the Phase 6 systematic-review evidence base"
    )
    parser.add_argument(
        "--review-out-dir", default=None,
        help="Directory for review outputs (default: same directory as --output)"
    )
    parser.add_argument(
        "--review-corpus-size", type=int, default=90,
        help="Representative corpus size for the review digest (default: 90)"
    )
    parser.add_argument(
        "--review-per-theme", type=int, default=8,
        help="Minimum exemplars per synthesis theme (default: 8)"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="One-shot pipeline: retrieval -> HTML deck -> systematic-review "
             "evidence base -> submission-ready review skeleton"
    )

    args = parser.parse_args()

    if args.full:
        args.deck = True
        args.review = True
        if not args.deck_topic:
            parser.error("--full requires --deck-topic (the review/deck title)")

    # Resolve query from --query or --query-file
    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as f:
            query = f.read().strip()
    else:
        query = args.query

    end_date = args.end_date or datetime.now().strftime("%Y/%m/%d")

    print(f"\n=== Searching PubMed ===")
    print(f"   Query:      {query}")
    print(f"   Date range: {args.start_date} - {end_date}")
    print(f"   Max results: {args.max_results}")

    # Step 1: Search
    id_list = search_pubmed_ids_edat(query, args.start_date, end_date, args.max_results)
    if not id_list:
        print("No PMIDs returned from search.")
        return

    # Step 2: Fetch details
    print(f"\n=== Fetching details for {len(id_list)} articles... ===")
    results = fetch_pubmed_details(id_list)
    print(f"   Retrieved {len(results)} articles with full details.")

    # Step 3: Save CSV
    output_dir = os.path.dirname(os.path.abspath(args.output))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    save_results_csv(results, args.output)

    # Step 4: Print summary
    summarize_results(results, query, args.start_date, end_date)

    # Step 5 (optional): build the academic deck
    if args.deck:
        build_deck_outputs(args, query, end_date)


if __name__ == "__main__":
    main()
