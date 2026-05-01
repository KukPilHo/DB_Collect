"""
검색 엔진 인터페이스
=====================
기존 DB_pipeline.py에서 이식:
- naver_search, google_cse, duckduckgo_search
- search_emails_for_company (다중 쿼리 + 후보 URL 방문)
"""

import time
from typing import List, Set, Tuple
from urllib.parse import urlparse

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
from .ai_filter import is_valid_company_email


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
INVALID_HOMEPAGES = {"http://", "http:// ", "https://", "http://www.", "", "nan"}

# 회사당 최대 수집 이메일 수 (너무 많으면 노이즈만 늘어남)
MAX_EMAILS_PER_COMPANY = 15


def search_emails_for_company(
    name: str,
    address_hint: str = "",
    homepage_url: str = "",
) -> List[EmailHit]:
    """
    다중 검색 소스로 후보 URL/스니펫 수집 → 페이지 본문에서 이메일 추출.
    """
    hits: List[EmailHit] = []
    seen_emails: Set[str] = set()
    seen_urls: Set[str] = set()

    # ── Phase 0: 홈페이지 직접 방문 (검색 전에 실행) ──────────
    hp = str(homepage_url).strip() if homepage_url else ""
    if hp and hp not in INVALID_HOMEPAGES and hp.startswith("http"):
        tqdm.write(f"    - 🏠 [홈페이지 직접 방문] {hp}")
        seen_urls.add(hp)
        for hit in scrape_emails_from_url(hp):
            if hit.email not in seen_emails:
                seen_emails.add(hit.email)
                is_valid = is_valid_company_email(name, hit.email, f"Homepage: {hp}")
                mark = "" if is_valid else "[AI 필터링 걸림] "
                hit.method = f"{mark}homepage_direct"
                hits.append(hit)
                tqdm.write(f"      => [홈페이지 발견] {hit.email} (homepage_direct) {mark}")
        time.sleep(CRAWL_DELAY_SEC)

    # 검색 쿼리 생성 (3개로 최적화: 기존 5~6개에서 중복/비효율 제거)
    queries = [
        f"{name} 이메일",
        f"{name} 공식 홈페이지",
        f'"{name}" "@"',
    ]

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

    # ── site: 연산자 검색 (DuckDuckGo) ──────────────────────
    if homepage_url and homepage_url not in INVALID_HOMEPAGES:
        domain = urlparse(homepage_url).netloc.lstrip("www.")
        if domain:
            site_queries = [f"site:{domain} 이메일", f"site:{domain} contact"]
            for sq in site_queries:
                tqdm.write(f"    - 🔍 [DuckDuckGo site:] '{sq}'")
                for it in duckduckgo_search(sq, 5):
                    url = it.get("link") or ""
                    snip = (it.get("title", "") + " " + it.get("snippet", ""))
                    if url and url not in seen_urls and not any(b in url for b in URL_BLOCKLIST):
                        seen_urls.add(url)
                        candidates.append((url, snip, "duckduckgo_site"))
                time.sleep(0.5)

    # 1) 검색결과 스니펫에서 직접 이메일 추출 (가장 빠른 hit)
    for url, snippet, method in candidates:
        for em in extract_emails_from_text(snippet):
            if em not in seen_emails:
                seen_emails.add(em)
                is_valid = is_valid_company_email(name, em, snippet)
                mark = "" if is_valid else "[AI 필터링 걸림] "
                hits.append(EmailHit(email=em, source_url=url, method=f"{mark}{method}_snippet"))
                tqdm.write(f"      => [스니펫 발견] {em} ({method}) {mark}")

    # 2) 후보 URL 직접 방문 (상위 6개 — 12개는 과다, 노이즈만 증가)
    to_visit = [
        u for u, _, _ in candidates[:6]
        if not any(u.lower().endswith(ext) for ext in (".pdf", ".jpg", ".png", ".gif", ".zip"))
    ]
    if to_visit:
        tqdm.write(f"    - 홈페이지 방문: {len(to_visit)}개 URL")

    for url in to_visit:
        time.sleep(CRAWL_DELAY_SEC)
        for hit in scrape_emails_from_url(url):
            if hit.email not in seen_emails:
                seen_emails.add(hit.email)
                is_valid = is_valid_company_email(name, hit.email, f"Source URL: {url}")
                mark = "" if is_valid else "[AI 필터링 걸림] "
                hit.method = f"{mark}{hit.method}"
                hits.append(hit)
                tqdm.write(f"      => [홈페이지 발견] {hit.email} ({url}) {mark}")
            
            # 한 페이지에서 무더기로 나오는 경우 바로 중단
            if len(seen_emails) >= MAX_EMAILS_PER_COMPANY:
                break
                
        if len(seen_emails) >= MAX_EMAILS_PER_COMPANY:
            tqdm.write(f"      => 이메일 {len(seen_emails)}개 수집 완료 (상한), URL 방문 중단")
            break

    return [h for h in hits if h.is_valid()]
