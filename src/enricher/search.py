"""
검색 엔진 인터페이스
=====================
기존 DB_pipeline.py에서 이식:
- naver_search, google_cse, duckduckgo_search
- search_emails_for_company (다중 쿼리 + 후보 URL 방문)
"""

import time
from typing import List, Set, Tuple

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from src.config import (
    CRAWL_DELAY_SEC,
    GOOGLE_CSE_API_KEY,
    GOOGLE_CSE_CX,
    NAVER_CLIENT_ID,
    NAVER_CLIENT_SECRET,
    TIMEOUT_SEC,
    log,
)
from .scraper import (
    URL_BLOCKLIST,
    EmailHit,
    extract_emails_from_text,
    scrape_emails_from_url,
)


# ── Naver Open API (webkr / local) ───────────────────────
@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=5))
def naver_search(query: str, kind: str = "webkr", display: int = 10) -> List[dict]:
    """네이버 검색 API 호출."""
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return []
    url = f"https://openapi.naver.com/v1/search/{kind}.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    r = requests.get(
        url, headers=headers,
        params={"query": query, "display": display},
        timeout=TIMEOUT_SEC,
    )
    if r.status_code != 200:
        log.debug("Naver %s 실패 %d %s", kind, r.status_code, r.text[:100])
        return []
    return r.json().get("items", [])


# ── Google Custom Search ──────────────────────────────────
def google_cse(query: str, num: int = 10) -> List[dict]:
    """Google CSE API 호출."""
    if not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX):
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_CSE_API_KEY,
                "cx": GOOGLE_CSE_CX,
                "q": query,
                "num": min(num, 10),
            },
            timeout=TIMEOUT_SEC,
        )
        if r.status_code != 200:
            return []
        return r.json().get("items", [])
    except requests.RequestException:
        return []


# ── DuckDuckGo Search (무료 대안) ─────────────────────────
def duckduckgo_search(query: str, num: int = 5) -> List[dict]:
    """DuckDuckGo 검색 (비공식 라이브러리). 깨지면 빈 리스트 반환."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=num, region="kr-kr")
            if not results:
                return []
            return [
                {
                    "link": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
    except Exception as e:
        log.debug("DuckDuckGo 검색 실패: %s", e)
        return []


# ── 다중 소스 이메일 검색 ─────────────────────────────────
def search_emails_for_company(
    name: str,
    address_hint: str = "",
) -> List[EmailHit]:
    """
    다중 검색 소스로 후보 URL/스니펫 수집 → 페이지 본문에서 이메일 추출.
    """
    hits: List[EmailHit] = []
    seen_emails: Set[str] = set()
    seen_urls: Set[str] = set()

    # 검색 쿼리 생성
    queries = [
        f"{name} 이메일",
        f"{name} 문의",
        f"{name} 공식 홈페이지",
        f"{name} contact email",
    ]
    if address_hint:
        city = address_hint.split()[0] if address_hint.split() else ""
        if city:
            queries.append(f"{name} {city}")

    candidates: List[Tuple[str, str, str]] = []  # (url, snippet, method)

    for q in queries:
        # 네이버 웹문서
        tqdm.write(f"    - 🔍 [Naver 웹문서] '{q}'")
        for it in naver_search(q, "webkr", 10):
            url = it.get("link") or ""
            snip = (it.get("title", "") + " " + it.get("description", ""))
            if url and url not in seen_urls and not any(b in url for b in URL_BLOCKLIST):
                seen_urls.add(url)
                candidates.append((url, snip, "naver_webkr"))
        time.sleep(0.3)

        # 네이버 지역정보
        tqdm.write(f"    - 🔍 [Naver 지역] '{q}'")
        for it in naver_search(q, "local", 5):
            url = it.get("link") or ""
            snip = " ".join([it.get("title", ""), it.get("description", ""), it.get("address", "")])
            if url and url not in seen_urls and not any(b in url for b in URL_BLOCKLIST):
                seen_urls.add(url)
                candidates.append((url, snip, "naver_local"))
        time.sleep(0.3)

        # Google CSE
        tqdm.write(f"    - 🔍 [Google CSE] '{q}'")
        for it in google_cse(q, 10):
            url = it.get("link") or ""
            snip = (it.get("title", "") + " " + it.get("snippet", ""))
            if url and url not in seen_urls and not any(b in url for b in URL_BLOCKLIST):
                seen_urls.add(url)
                candidates.append((url, snip, "google_cse"))
        time.sleep(0.3)

        # DuckDuckGo
        tqdm.write(f"    - 🔍 [DuckDuckGo] '{q}'")
        for it in duckduckgo_search(q, 5):
            url = it.get("link") or ""
            snip = (it.get("title", "") + " " + it.get("snippet", ""))
            if url and url not in seen_urls and not any(b in url for b in URL_BLOCKLIST):
                seen_urls.add(url)
                candidates.append((url, snip, "duckduckgo"))
        time.sleep(0.5)

    # 1) 검색결과 스니펫에서 직접 이메일 추출 (가장 빠른 hit)
    for url, snippet, method in candidates:
        for em in extract_emails_from_text(snippet):
            if em not in seen_emails:
                seen_emails.add(em)
                hits.append(EmailHit(email=em, source_url=url, method=f"{method}_snippet"))
                tqdm.write(f"      => [스니펫 발견] {em} ({method})")

    # 2) 후보 URL 직접 방문 (상위 8개만)
    to_visit = [
        u for u, _, _ in candidates[:8]
        if not any(u.lower().endswith(ext) for ext in (".pdf", ".jpg", ".png", ".gif", ".zip"))
    ]
    if to_visit:
        tqdm.write(f"    - 홈페이지 방문: {len(to_visit)}개 URL")

    for url in to_visit:
        time.sleep(CRAWL_DELAY_SEC)
        found_in_url = False
        for hit in scrape_emails_from_url(url):
            if hit.email not in seen_emails:
                seen_emails.add(hit.email)
                hits.append(hit)
                found_in_url = True
                tqdm.write(f"      => [홈페이지 발견] {hit.email} ({url})")
        if found_in_url:
            break  # 한 URL에서 찾으면 다음 URL 생략 (속도 우선)

    return [h for h in hits if h.is_valid()]
