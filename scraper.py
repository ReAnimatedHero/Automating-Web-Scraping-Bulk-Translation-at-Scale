#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Novel Web Scraper + Bulk Translator

Scrapes chapter pages from an index URL, extracts the main text,
optionally translates each chapter, and saves the results as .txt files.

Original logic adapted from a Jupyter Notebook version.
"""

import os
import time
import argparse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator


def fetch_url(url, headers=None, retries=3, timeout=15, delay=3):
    """
    Fetch a URL with retries.
    Returns response.text on success, or None on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            print(f"[{attempt}/{retries}] GET {url}")
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            else:
                print(f"HTTP {resp.status_code} for {url}")
                return None
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            if attempt == retries:
                return None
            time.sleep(delay)


def get_chapter_links(index_url, headers=None, retries=3, timeout=15, delay=3):
    """
    Parse the index page and return a list of dicts:
    [{"title": "...", "url": "..."}, ...]
    """
    html = fetch_url(index_url, headers=headers, retries=retries, timeout=timeout, delay=delay)
    if not html:
        raise RuntimeError("Failed to fetch index page")

    soup = BeautifulSoup(html, "lxml")

    # This selector is specific to the example site.
    # You may need to customize this for other websites.
    container = soup.find(id="tbchapterlist")
    if not container:
        raise RuntimeError("Could not find #tbchapterlist – check the page structure")

    chapter_links = []
    for a in container.find_all("a"):
        href = a.get("href")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        full_url = urljoin(index_url, href)
        chapter_links.append({"title": title, "url": full_url})

    print(f"Found {len(chapter_links)} chapters.")
    return chapter_links


def extract_chapter_text(chapter_html):
    """
    Given the HTML of a chapter page, extract the main text.

    NOTE: This is tailored to the example site which uses a <div>
    with inline styles for font-size and line-height.
    """
    soup = BeautifulSoup(chapter_html, "lxml")

    content_div = soup.find(
        "div",
        style=lambda v: v and "font-size: 20px" in v and "line-height: 30px" in v
    )

    if not content_div:
        raise RuntimeError("Could not find chapter text container. Structure may have changed.")

    paragraphs = []

    # Many lines are separated by <p/> and <br/>
    for elem in content_div.find_all(["p", "br"]):
        text = elem.get_text(strip=True)
        if text:
            paragraphs.append(text)

    # Fallback: if we didn't get anything from <p>/<br>, just split the raw text
    if not paragraphs:
        raw = content_div.get_text("\n", strip=True)
        paragraphs = [line for line in raw.split("\n") if line.strip()]

    # Optional cleaning: drop site-name reminder lines if present
    cleaned = []
    for line in paragraphs:
        if "請記住本站域名" in line:
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def translate_text(text, translator=None, enabled=True, line_delay=0.5):
    """
    Translate multi-line text using deep_translator.GoogleTranslator.
    Splits on newlines to reduce the chance of hitting length limits.
    """
    if not enabled or translator is None:
        return text

    lines = [line for line in text.split("\n") if line.strip()]
    translated_lines = []

    for idx, line in enumerate(lines, start=1):
        try:
            en = translator.translate(line)
        except Exception as e:
            print(f"Translation error on line {idx}: {e}")
            en = line  # fallback: keep original line
        translated_lines.append(en)
        time.sleep(line_delay)  # be gentle with the translation service

    return "\n".join(translated_lines)


def sanitize_filename(name):
    """
    Replace characters that are invalid on common file systems.
    """
    invalid = r'\\/:*?"<>|'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name.strip() or "chapter"


def process_chapters(
    index_url,
    output_dir="novel_output",
    start_from=0,
    max_chapters=None,
    translate=True,
    src_lang="zh-TW",
    dest_lang="en",
    request_delay=3,
    retries=3,
    timeout=15,
    user_agent="NovelScraper/1.0 (+your_email@example.com)",
):
    """
    Orchestrates the whole scraping + translation pipeline.
    """

    os.makedirs(output_dir, exist_ok=True)

    headers = {
        "User-Agent": user_agent
    }

    # Initialize translator only if needed
    translator = None
    if translate:
        translator = GoogleTranslator(source=src_lang, target=dest_lang)

    # Step 1: get all chapter links
    chapter_links = get_chapter_links(
        index_url=index_url,
        headers=headers,
        retries=retries,
        timeout=timeout,
        delay=request_delay,
    )

    total = len(chapter_links)
    print(f"Total chapters discovered: {total}")
    if start_from >= total:
        print(f"start_from={start_from} is >= total chapters={total}. Nothing to do.")
        return

    # Step 2: iterate over chapters
    for idx, chap in enumerate(chapter_links[start_from:], start=start_from):
        if max_chapters is not None and idx >= start_from + max_chapters:
            break

        title = chap["title"]
        url = chap["url"]

        print(f"\n==== Chapter {idx + 1}/{total}: {title} ====")
        print(f"URL: {url}")

        html = fetch_url(url, headers=headers, retries=retries, timeout=timeout, delay=request_delay)
        if not html:
            print("Failed to fetch chapter HTML, skipping.")
            continue

        try:
            zh_text = extract_chapter_text(html)
        except RuntimeError as e:
            print(f"Error parsing chapter: {e}")
            continue

        base_name = f"{idx + 1:04d}_{sanitize_filename(title)}"

        # Only save translated version by default
        if translate:
            en_text = translate_text(
                zh_text,
                translator=translator,
                enabled=True,
                line_delay=0.5,
            )
            out_path = os.path.join(output_dir, base_name + "_en.txt")
        else:
            en_text = zh_text
            out_path = os.path.join(output_dir, base_name + ".txt")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(en_text)

        print(f"Saved file: {out_path}")
        time.sleep(request_delay)  # Respectful delay between chapter requests


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape novel chapters from an index page and optionally translate them."
    )

    parser.add_argument(
        "index_url",
        help="Index page URL that lists all chapters.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="novel_output",
        help="Directory where output .txt files will be stored (default: novel_output).",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        default=0,
        help="0-based index in the chapter list to start from (default: 0).",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=None,
        help="Maximum number of chapters to process from start_from (default: all).",
    )
    parser.add_argument(
        "--no-translate",
        action="store_false",
        dest="translate",
        help="Disable translation and save only original text.",
    )
    parser.add_argument(
        "--src-lang",
        default="zh-TW",
        help="Source language code for translation (default: zh-TW).",
    )
    parser.add_argument(
        "--dest-lang",
        default="en",
        help="Target language code for translation (default: en).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=3.0,
        help="Seconds to sleep between HTTP requests (default: 3).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retries for HTTP requests (default: 3).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Timeout in seconds for HTTP requests (default: 15).",
    )
    parser.add_argument(
        "--user-agent",
        default="NovelScraper/1.0 (+your_email@example.com)",
        help="Custom User-Agent header (default: NovelScraper/1.0 ...).",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    process_chapters(
        index_url=args.index_url,
        output_dir=args.output_dir,
        start_from=args.start_from,
        max_chapters=args.max_chapters,
        translate=args.translate,
        src_lang=args.src_lang,
        dest_lang=args.dest_lang,
        request_delay=args.request_delay,
        retries=args.retries,
        timeout=args.timeout,
        user_agent=args.user_agent,
    )


if __name__ == "__main__":
    main()
