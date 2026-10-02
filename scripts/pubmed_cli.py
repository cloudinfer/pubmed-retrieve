"""
PubMed Retrieve CLI — end-to-end pipeline: search → fetch → save → summarize.

Usage:
    python pubmed_cli.py --query "diabetes AND exercise" \
                         --start-date 2020/01/01 \
                         --end-date 2024/12/31 \
                         --max-results 50 \
                         --output pubmed_results.csv

    # with the Phase 6 academic deck chain:
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


def build_deck_outputs(args, query, end_date, review_path=None):
    """Phase 6: chain the deck content model + HTML deck renderer.

    Runs **after** the review. The review layer is embedded into the content
    model (not just handed to the HTML renderer) because ``deck_outline.md`` is
    the only material the PPT step receives -- a review layer that lives solely
    in a render-time argument never reaches the slides.
    """
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
        review=review_path,
        search_date=datetime.now().strftime("%Y-%m-%d"),
    )

    print("\n=== Building academic deck (Phase 6) ===")
    if not review_path:
        print("   [deck] WARNING: no review layer. The deck will carry descriptive "
              "statistics only; run the review first and pass --review.")
    content = dc.build_content(ns)
    json_path, md_path = dc.write_outputs(content, out_dir)
    print(f"   content model: {json_path}  (review layer: "
          f"{', '.join(content['meta']['review_layers']) or 'none'})")
    print(f"   outline:       {md_path}  ({len(dc.page_sequence(content))} pages)")

    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (args.deck_topic or "deck")).strip("_")[:48] or "deck"
    deck_path = os.path.join(out_dir, f"{slug}_deck.html")

    review = None
    if review_path:
        with open(review_path, "r", encoding="utf-8") as fh:
            review = json.load(fh)

    pages = db.write_deck(content, deck_path, review=review)
    print(f"   html deck:     {deck_path}  ({pages} pages"
          + (", review pages included)" if review else ", descriptive layer only)"))
    print("   next: run deck_validate.py, then hand deck_outline.md to the PPT step.")


def preflight_review(args, query, end_date):
    """Load topic-specific review criteria/PICOS and refuse a topic mismatch.

    Deliberately runs **before** the first network call. The guard rejects a
    non-hepatic topic that is still using the built-in hepatocellular-carcinoma
    defaults; checking it after retrieval would mean a rejected run had already
    overwritten the caller's CSV and deck content model. Fail first, fail cheap.
    """
    out_dir = args.review_out_dir or (os.path.dirname(os.path.abspath(args.output)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    topic = args.deck_topic or ""
    args._picos = None

    try:
        import review_evidence as re_mod
    except ImportError as exc:
        print(f"[preflight] review_evidence unavailable ({exc}); review stages will be skipped")
        return

    re_mod.load_criteria(getattr(args, "criteria_file", None))
    re_mod.guard_criteria(topic, query, getattr(args, "allow_default_criteria", False), out_dir)

    picos_path = getattr(args, "picos_file", None)
    if picos_path:
        with open(picos_path, encoding="utf-8") as fh:
            args._picos = json.load(fh)

    try:
        import review_compose as rc_mod
    except ImportError as exc:
        print(f"[preflight] review_compose unavailable ({exc})")
        return

    if picos_path:
        rc_mod.PICOS_SOURCE = os.path.basename(picos_path)
        rc_mod.PICOS_IS_DEFAULT = False
    rc_mod.guard_picos(topic, args._picos,
                       getattr(args, "allow_default_picos", False), out_dir)


def build_review_outputs(args, query, end_date):
    """Phase 5: build the systematic-review evidence base from the retrieved CSV.

    Runs **before** the deck. The deck renders its review layer out of this
    artifact, so producing the deck first would mean rendering an outline with
    no review in it -- which is exactly how the PPT ended up without the review's
    content.
    """
    import types

    try:
        import review_evidence as re
    except ImportError as exc:
        print(f"\n[review] skipped: cannot import review_evidence ({exc})")
        return None

    out_dir = args.review_out_dir or (os.path.dirname(os.path.abspath(args.output)) or ".")
    os.makedirs(out_dir, exist_ok=True)

    # Loading is idempotent; *checking* stays in preflight_review() so the rule
    # has one home. Reloading here keeps this function correct even when it is
    # called on its own (the criteria are module-level state, and silently
    # falling back to the hepatocarcinoma defaults is exactly the failure this
    # whole guard exists to prevent -- it would collapse the corpus to a handful
    # of records without an error).
    re.load_criteria(getattr(args, "criteria_file", None))

    # Criteria were already validated by preflight_review() before retrieval
    # started; re-implementing the check here would be a second, silently
    # drifting copy of the rule.
    ns = types.SimpleNamespace(
        csv=args.output,
        out_dir=out_dir,
        topic=args.deck_topic or "",
        query=query,
        query_file=None,
        # deck_content reads `start`/`end`; review_evidence reads
        # `start_date`/`end_date`. Provide both so the namespace serves either.
        start=args.start_date,
        end=end_date,
        start_date=args.start_date,
        end_date=end_date,
        max_results=args.max_results,
        corpus_size=args.review_corpus_size,
        per_theme=args.review_per_theme,
        themes_file=args.review_themes_file or args.topics_file,
        search_date=datetime.now().strftime("%Y-%m-%d"),
    )

    print("\n=== Building systematic-review evidence base (Phase 5) ===")
    ev = re.build(ns)
    ev.setdefault("meta", {})["criteria_source"] = re.CRITERIA_SOURCE
    ev["meta"]["criteria_is_default"] = re.CRITERIA_IS_DEFAULT
    # Carry the PICOS wording with the evidence base so the deck's pictos page
    # renders the same population the review screened with, instead of a second
    # copy that can drift (or be wrong for the topic).
    picos = getattr(args, "_picos", None)
    if picos:
        ev["meta"]["picos"] = picos
        ev["meta"]["picos_source"] = os.path.basename(args.picos_file or "")
    ev["meta"]["picos_available"] = bool(picos)
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

    # Phase 5.2 -- compose the submission-ready skeleton. Everything
    # deterministic is written by the script; only interpretive prose is left
    # behind as WRITE-BLOCK briefs.
    try:
        import review_compose as rc
    except ImportError as exc:
        print(f"   [review] skeleton skipped: cannot import review_compose ({exc})")
        return json_path

    print("\n=== Composing review skeleton (Phase 5.2) ===")
    picos = getattr(args, "_picos", None)
    topic = args.deck_topic or ev["meta"]["topic"]
    pmids = [r["pmid"] for r in ev["corpus"]]
    refs, mapping = rc.build_references(args.output, pmids)
    draft = rc.compose(ev, refs, mapping, topic, "", picos)

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
        help="After retrieval, also build the deck content model + HTML deck "
             "(Phase 6; always runs after --review so the deck carries the review layer)"
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
        help="After retrieval, build the systematic-review evidence base + skeleton "
             "(Phase 5; runs before the deck)"
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
        "--review-themes-file", default=None,
        help="JSON {theme: regex} overriding the review synthesis themes "
             "(defaults to --topics-file if given)"
    )
    parser.add_argument(
        "--criteria-file", default=None,
        help="JSON overriding the review's PICOS eligibility criteria "
             "(pop_in/pop_strong/other_primary/idx_in/out_in + labels). "
             "REQUIRED for any non-hepatic topic -- see references/review-criteria.md"
    )
    parser.add_argument(
        "--picos-file", default=None,
        help="JSON overriding the review's PICOS wording "
             "(population/index/comparator/outcome/study_type/…/keywords). "
             "REQUIRED for any non-hepatic topic"
    )
    parser.add_argument(
        "--allow-default-criteria", action="store_true",
        help="Permit the built-in hepatocellular-carcinoma screening criteria "
             "on a non-hepatic topic (normally refused)"
    )
    parser.add_argument(
        "--allow-default-picos", action="store_true",
        help="Permit the built-in hepatocellular-carcinoma PICOS wording "
             "on a non-hepatic topic (normally refused)"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="One-shot pipeline: retrieval -> systematic-review evidence base "
             "-> submission-ready review skeleton -> deck (with the review layer)"
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

    # Preflight BEFORE the first network call. The eligibility-criteria guard
    # rejects a non-hepatic topic that is still using the hepatocarcinoma
    # defaults; running it after retrieval would mean a rejected run had
    # already overwritten the caller's CSV and deck content model with data
    # screened by the wrong rules. Fail first, fail cheap.
    if args.review or args.full:
        preflight_review(args, query, end_date)

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

    # Step 5 (optional): the systematic review FIRST, then the deck built out of
    # it. Order matters: the deck's review layer is rendered from the review's
    # evidence base, and deck_outline.md -- the material the PPT step consumes --
    # is written during the deck stage. Generating the deck first would produce
    # slides that cannot contain the review.
    review_path = None
    if args.review:
        review_path = build_review_outputs(args, query, end_date)

    if args.deck:
        build_deck_outputs(args, query, end_date, review_path)


if __name__ == "__main__":
    main()
