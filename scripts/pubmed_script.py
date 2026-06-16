import re
import os
import csv
import time
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

BASE_URL_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
BASE_URL_FETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RATE_LIMIT_DELAY = 0.4

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def normalize_month(month_str):
    if not month_str:
        return None
    if month_str.isdigit():
        return month_str.zfill(2)
    for fmt in ("%b", "%B"):
        try:
            dt = datetime.strptime(month_str, fmt)
            return f"{dt.month:02d}"
        except ValueError:
            continue
    return month_str

def build_pdat_date(year, month, day):
    if not year:
        return None
    if not month:
        return f"{year}"
    if not day:
        return f"{year}/{normalize_month(month)}"
    m = normalize_month(month)
    d = day.zfill(2) if day and day.isdigit() else "01"
    return f"{year}/{m}/{d}"

def search_pubmed_ids_edat(query, start_date, end_date, max_results=10000):
    params = {
        "db": "pubmed",
        "term": query,
        "mindate": start_date,
        "maxdate": end_date,
        "datetype": "edat",
        "retmode": "json",
        "retmax": max_results,
        # "usehistory": "y",
    }
    try:
        time.sleep(RATE_LIMIT_DELAY)
        response = requests.get(BASE_URL_SEARCH, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        count = data.get("esearchresult", {}).get("count", 0)
        print(f"Search (edat) found {count} results, retrieving top {len(id_list)}...")
        return id_list
    except Exception as e:
        print(f"Error during PubMed edat search: {e}")
        return []

def fetch_pubmed_details(id_list):
    if not id_list:
        return []
    results = []
    chunk_size = 50
    for i in range(0, len(id_list), chunk_size):
        chunk_ids = id_list[i : i + chunk_size]
        ids_str = ",".join(chunk_ids)
        params = {
            "db": "pubmed",
            "id": ids_str,
            "retmode": "xml",
        }
        try:
            time.sleep(RATE_LIMIT_DELAY)
            response = requests.get(BASE_URL_FETCH, params=params, timeout=20)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            articles = root.findall(".//PubmedArticle")
            for article in articles:
                parsed_item = parse_article_xml(article)
                if parsed_item:
                    results.append(parsed_item)
        except Exception as e:
            print(f"Error fetching details for chunk {i}: {e}")
    return results

def parse_article_xml(article_element):
    try:
        medline_citation = article_element.find("MedlineCitation")
        if medline_citation is None:
            return None
        # PMID
        pmid = medline_citation.findtext("PMID")
        article = medline_citation.find("Article")
        if article is None:
            return None
        # 题目
        title = article.findtext("ArticleTitle")
        # 摘要
        abstract_list = article.findall(".//AbstractText")
        abstract_parts = []
        for elem in abstract_list:
            label = elem.get("Label")
            text = elem.text
            if text:
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
        abstract = " ".join(abstract_parts)
        # 期刊名
        journal = article.find(".//Journal")
        journal_title = article.findtext("Journal/Title")

        # ISSN
        issn_elem = journal.find("ISSN")
        if issn_elem is not None:
            issn_type = issn_elem.get("IssnType") or ""
            issn = issn_elem.text.strip() if issn_elem.text else ""
        else:
            issn_type = ""
            issn = ""
        # print(issn_type, issn)
        # 出版时间
        pub_date_str = "Unknown"
        pub_date_elem = article.find("Journal/JournalIssue/PubDate")
        if pub_date_elem is not None:
            y = pub_date_elem.findtext("Year")
            if y:
                m = pub_date_elem.findtext("Month")
                d = pub_date_elem.findtext("Day")
                built = build_pdat_date(y, m, d)
                if built:
                    pub_date_str = built
            else:
                medline = pub_date_elem.findtext("MedlineDate")
                if medline:
                    y_match = re.search(r"\b(19|20)\d{2}\b", medline)
                    if y_match:
                        y_val = y_match.group(0)
                        m_match = re.search(r"[A-Za-z]{3,}", medline)
                        m_val = m_match.group(0) if m_match else None
                        built = build_pdat_date(y_val, m_val, None)
                        if built:
                            pub_date_str = built
        # 作者列表
        author_list = article.findall(".//Author")
        authors = []
        for auth in author_list:
            last = auth.findtext("LastName")
            fore = auth.findtext("ForeName")
            if last and fore:
                authors.append(f"{fore} {last}")
            elif last:
                authors.append(last)
            else:
                collective = auth.findtext("CollectiveName")
                if collective:
                    authors.append(collective)
        authors_str = ", ".join(authors)
        # DOI
        doi = ""
        elocation_ids = article.findall("ELocationID")
        for eloc in elocation_ids:
            if eloc.get("EIdType") == "doi":
                doi = eloc.text
                break
        if not doi:
            pubmed_data = article_element.find("PubmedData")
            if pubmed_data is not None:
                article_ids = pubmed_data.findall(".//ArticleId")
                for aid in article_ids:
                    if aid.get("IdType") == "doi":
                        doi = aid.text
                        break
        return {
            "Pmid": pmid or "",
            "ISSN": issn,
            "ISSN_Type": issn_type,
            "Title": clean_text(title),
            "Authors": clean_text(authors_str),
            "Journal": clean_text(journal_title),
            "Date": pub_date_str,
            "Doi": f"https://doi.org/{doi}" if doi else "",
            "Abstract": clean_text(abstract),
        }
    except Exception as e:
        print(f"Error parsing article XML: {e}")
        return None


def save_results_csv(data, filename):
    if not data:
        print("No data to save.")
        return
    try:
        df_data = pd.DataFrame(data)
        df_data.to_csv(filename, index=False)
        print(f"Successfully saved {len(data)} records to {filename}")
    except Exception as e:
        print(f"Error saving CSV: {e}")
    