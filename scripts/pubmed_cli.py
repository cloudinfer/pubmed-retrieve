"""
PubMed Retrieve CLI — end-to-end pipeline: search → fetch → save → summarize.

Usage:
    python pubmed_cli.py --query "diabetes AND exercise" \
                         --start-date 2020/01/01 \
                         --end-date 2024/12/31 \
                         --max-results 50 \
                         --output pubmed_results.csv
"""

import argparse
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

    args = parser.parse_args()

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
    save_results_csv(results, args.output)

    # Step 4: Print summary
    summarize_results(results, query, args.start_date, end_date)


if __name__ == "__main__":
    main()
