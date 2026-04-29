"""
이메일 스크래퍼
================
기존 DB_pipeline.py에서 이식:
- EmailHit dataclass + is_valid()
- EMAIL_BLOCKLIST_DOMAINS, EMAIL_BLOCKLIST_LOCAL, URL_BLOCKLIST 상수
- extract_emails_from_text, find_contact_pages, fetch_html, scrape_emails_from_url
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import CRAWL_DELAY_SEC, TIMEOUT_SEC, USER_AGENT, log

# ── 이메일 정규식 ─────────────────────────────────────────
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# ── 블랙리스트 ────────────────────────────────────────────
EMAIL_BLOCKLIST_DOMAINS = {
    "example.com", "domain.com", "yourdomain.com", "test.com", "email.com",
    "company.com",
    "sentry.io", "wixpress.com", "godo.co.kr", "cafe24.com",
    "saramin.co.kr", "happycampus.com",
    "jobkorea.co.kr", "albamon.com", "incruit.com", "work.go.kr",
    "kreditjob.com", "catch.co.kr", "114.co.kr", "kakaopage.com",
    "kakao.com", "kakaocorp.com", "tiktok.com", "instagram.com",
    "facebook.com", "youtube.com", "twitter.com", "x.com",
    "korea.kr", "go.kr", "or.kr", "fnnews.com", "yna.co.kr", "ikld.kr", "keris.or.kr",
    # 디렉토리/플랫폼 이메일 도메인
    "sankun.com", "marketbz.com", "itdonga.com", "carestore.co.kr",
    "rndcircle.io", "goodsoftware.co.kr", "teamblind.com", "daangn.com",
}


def _is_blocked_domain(domain: str) -> bool:
    """도메인이 블랙리스트에 포함되는지 확인 (서브도메인 포함)."""
    if domain in EMAIL_BLOCKLIST_DOMAINS:
        return True
    # 서브도메인 매칭: sentry.wixpress.com → wixpress.com
    for blocked in EMAIL_BLOCKLIST_DOMAINS:
        if domain.endswith("." + blocked):
            return True
    return False


EMAIL_BLOCKLIST_LOCAL = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "example", "test", "email", "yourname", "yourid", "abc", "xxx",
    "privacy", "personal", "admin", "webmaster", "master",
}

URL_BLOCKLIST = [
    # 취업/구인 사이트
    "saramin.co.kr", "jobkorea.co.kr", "albamon.com", "incruit.com",
    "work.go.kr", "catch.co.kr", "happycampus.com", "114.co.kr",
    "bizno.net", "kreditjob.com", "nicebizinfo.com", "rocketpunch.com",
    "wanted.co.kr", "jobplanet.co.kr",
    # SNS
    "tiktok.com", "instagram.com", "facebook.com", "youtube.com", "twitter.com", "x.com",
    # 뉴스
    "fnnews.com", "yna.co.kr", "ikld.kr", "korea.kr", "go.kr", "keris.or.kr",
    # 디렉토리/플랫폼 (노이즈 다량 발생)
    "sankun.com", "marketbz.com", "g2bmarket.com", "ksaco.kr",
    "sw.or.kr", "spo.go.kr", "factory.kjuso.kr", "myfactory.co.kr",
    "eep.energy.or.kr", "nursing.snu.ac.kr", "linkonbiz.com",
    "ourtoday.co.kr", "daont.co.kr", "babechat.ai", "m.frangfrang.com",
    "rome2rio.com", "goodsoftware.co.kr",
]


# ── EmailHit 데이터클래스 ─────────────────────────────────
@dataclass
class EmailHit:
    """검색/크롤 과정에서 발견된 이메일 한 건."""
    email: str
    source_url: str
    method: str  # naver_webkr, naver_local, google_cse, duckduckgo, homepage
    found_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def is_valid(self) -> bool:
        """이메일 유효성 검증."""
        em = self.email.lower().strip().rstrip(".,;:")
        local, _, domain = em.partition("@")
        if not domain or "." not in domain:
            return False
        if _is_blocked_domain(domain):
            return False
        if local in EMAIL_BLOCKLIST_LOCAL:
            return False
        if domain.endswith((".png", ".jpg", ".gif", ".pdf", ".zip", ".webp")):
            return False
        if len(em) > 80 or len(local) < 1:
            return False
        if local.startswith((".", "-", "_", "%", "+")) or local.endswith((".", "-", "_", "%", "+")):
            return False
        return True


def _clean_email(em: str) -> str:
    """이메일 문자열 정리."""
    return em.strip().rstrip(".,;:'\"")


# ── 페이지 fetch ──────────────────────────────────────────
@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=5))
def fetch_html(url: str) -> str:
    """URL에서 HTML을 가져온다. encoding 자동 보정."""
    r = requests.get(url, timeout=TIMEOUT_SEC, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    if r.encoding is None or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


# ── 이메일 추출 ───────────────────────────────────────────
def extract_emails_from_text(text: str) -> Set[str]:
    """텍스트에서 이메일 추출 + 필터링."""
    raw = set(EMAIL_REGEX.findall(text or ""))
    out: Set[str] = set()
    for em in raw:
        em = _clean_email(em)
        local, _, domain = em.lower().partition("@")
        if not domain or "." not in domain:
            continue
        if _is_blocked_domain(domain):
            continue
        if local in EMAIL_BLOCKLIST_LOCAL:
            continue
        if domain.endswith((".png", ".jpg", ".gif", ".pdf", ".webp")):
            continue
        if "@2x" in em or "@3x" in em:  # 이미지 retina 표기
            continue
        if local.startswith((".", "-", "_", "%", "+")) or local.endswith((".", "-", "_", "%", "+")):
            continue
        out.add(em)
    return out


# ── 연락처 페이지 탐색 ────────────────────────────────────
def find_contact_pages(soup: BeautifulSoup, base_url: str) -> List[str]:
    """HTML 내에서 연락처/회사소개 관련 링크를 찾는다."""
    keywords = (
        "contact", "about", "company", "introduction",
        "연락", "문의", "회사소개", "오시는길", "개요",
    )
    out: List[str] = []
    seen: Set[str] = set()
    base_host = urlparse(base_url).netloc

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        txt = (a.get_text() or "").lower()
        
        # 개인정보처리방침 등 필터링
        if any(bad in href.lower() for bad in ("privacy", "personal", "policy", "term")):
            continue
            
        if any(k in href.lower() or k in txt for k in keywords):
            full = urljoin(base_url, href)
            if urlparse(full).netloc == base_host and full not in seen:
                seen.add(full)
                out.append(full)
        if len(out) >= 5:
            break
    return out


# ── URL에서 이메일 스크래핑 ────────────────────────────────
def scrape_emails_from_url(url: str) -> List[EmailHit]:
    """URL 본문 + 하위 연락처 페이지에서 이메일 추출."""
    hits: List[EmailHit] = []
    try:
        html = fetch_html(url)
    except Exception as e:
        log.debug("fetch 실패 %s: %s", url, e)
        return hits

    soup = BeautifulSoup(html, "lxml")
    for em in extract_emails_from_text(html):
        hits.append(EmailHit(email=em, source_url=url, method="homepage"))

    # 하위 연락처 페이지 탐색
    for sub in find_contact_pages(soup, url):
        time.sleep(CRAWL_DELAY_SEC)
        try:
            html2 = fetch_html(sub)
        except Exception:
            continue
        for em in extract_emails_from_text(html2):
            hits.append(EmailHit(email=em, source_url=sub, method="homepage"))

    return hits
