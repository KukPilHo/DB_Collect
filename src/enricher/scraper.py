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
    "korea.kr", "go.kr", "fnnews.com", "yna.co.kr", "ikld.kr", "keris.or.kr",
    # 디렉토리/플랫폼 이메일 도메인
    "sankun.com", "marketbz.com", "itdonga.com", "carestore.co.kr",
    "rndcircle.io", "goodsoftware.co.kr", "teamblind.com", "daangn.com",
    # 뉴스/미디어/커뮤니티 도메인
    "inven.co.kr", "dkpia.com", "lab-t.net", "ntrex.co.kr",
    "esgroup.net", "theinvest.co.kr", "investnews.co.kr", "dable.io",
    "companymarket.co.kr", "happyhaksul.com", "biztop.co.kr",
    "composecoffee.co.kr", "sportsseoul.com", "koit.co.kr",
    "hanbat.ac.kr", "skuniv.ac.kr", "sejungilbo.com", "aitimes.kr",
    "smartcity.or.kr", "daangnservice.com", "urlquery.net",
    # 실행 중 추가 발견 (뉴스/무관 플랫폼)
    "boannews.com", "apple-economy.com", "irobotnews.com", "etnews.com",
    "ablenews.co.kr", "theindigo.co.kr", "fpn119.co.kr", "newstown.co.kr",
    "cosinkorea.com", "techsuda.com", "zdnet.co.kr", "ruliweb.com",
    "op.gg", "blog.yeogie.com", "radiokorea.com", "surfshark.com", "surfsharkbiz.com", "surfsharkpress.com",
    # 사용자 지정 차단 도메인
    "bagelchat.ai", "cookiedeal.io", "aving.net",
}


def _is_blocked_domain(domain: str) -> bool:
    """도메인이 블랙리스트에 포함되는지 확인 (서브도메인 포함)."""
    # 1. 아카데믹/공공 도메인 차단 (공장/기업 DB 타겟에서 불필요)
    if domain.endswith(".ac.kr") or domain.endswith(".edu"):
        return True
        
    # 2. 뉴스/미디어 의심 도메인 (광범위하게 차단)
    news_keywords = ["news", "press", "daily", "times", "journal", "today"]
    if any(k in domain for k in news_keywords):
        return True

    # 3. 명시적 블랙리스트 확인
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
    # 뉴스/미디어
    "fnnews.com", "yna.co.kr", "ikld.kr", "korea.kr", "go.kr", "keris.or.kr",
    "inven.co.kr", "sejungilbo.com", "aitimes.kr", "hellodd.com",
    "sportsseoul.com", "koit.co.kr", "msn.com", "namsieon.com",
    # 디렉토리/플랫폼 (노이즈 다량 발생)
    "sankun.com", "marketbz.com", "g2bmarket.com", "ksaco.kr",
    "sw.or.kr", "spo.go.kr", "factory.kjuso.kr", "myfactory.co.kr",
    "eep.energy.or.kr", "nursing.snu.ac.kr", "linkonbiz.com",
    "ourtoday.co.kr", "daont.co.kr", "babechat.ai", "m.frangfrang.com",
    "rome2rio.com", "goodsoftware.co.kr",
    # 제3자 디렉토리/리뷰/중고거래 사이트
    "devicemart.co.kr", "namu.wiki", "play.google.com", "prezi.com",
    "changeok.co.kr", "worker.co.kr", "celtic.co.kr", "biztop.co.kr",
    "happyhaksul.com", "companymarket.co.kr", "haesola.com",
    "composecoffee.com", "smartcitysolutionmarket.com",
    "app.rndcircle.io", "ubique.co.kr", "oncore.co.kr", "roadmine.com",
    "daangn.com", "hanbat.ac.kr", "skuniv.ac.kr",
    # 뉴스/미디어 추가 (실행 중 발견)
    "boannews.com", "apple-economy.com", "irobotnews.com", "etnews.com",
    "ablenews.co.kr", "theindigo.co.kr", "fpn119.co.kr", "newstown.co.kr",
    "cosinkorea.com", "techsuda.com", "zdnet.co.kr", "ruliweb.com",
    # 무관 플랫폼
    "op.gg", "blog.yeogie.com", "radiokorea.com", "surfshark.com",
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


# ── 프리메일 도메인 ────────────────────────────────────────
FREE_MAIL_DOMAINS = {
    "naver.com", "gmail.com", "hanmail.net", "daum.net",
    "nate.com", "hotmail.com", "outlook.com", "outlook.kr",
    "yahoo.com", "yahoo.co.kr",
}


def _clean_email(em: str) -> str:
    """이메일 문자열 정리."""
    return em.strip().rstrip(".,;:'\"")


def is_cross_domain_noise(email: str, source_url: str) -> bool:
    """
    출처 URL 도메인과 이메일 도메인이 무관한 제3자 이메일인지 판별.
    프리메일(naver, gmail 등)은 제외하고, 기업 도메인 이메일만 체크.
    True = 노이즈(차단 대상), False = 통과.
    """
    email_lower = email.lower()
    _, _, email_domain = email_lower.partition("@")
    if not email_domain:
        return False

    # 프리메일은 cross-domain 체크 건너뜀 (회사 담당자가 프리메일 쓸 수 있음)
    if email_domain in FREE_MAIL_DOMAINS:
        return False

    # 출처 URL 도메인 추출
    source_host = urlparse(source_url).netloc.lower().replace("www.", "")
    if not source_host:
        return False

    # 블로그/포털은 cross-domain 체크 건너뜀 (블로그에 자기 이메일 올리는 경우)
    blog_hosts = {
        "blog.naver.com", "m.blog.naver.com", "tistory.com",
        "brunch.co.kr", "medium.com", "velog.io",
        "linkedin.com", "kr.linkedin.com",
    }
    for bh in blog_hosts:
        if source_host == bh or source_host.endswith("." + bh):
            return False

    # 이메일 도메인이 출처 URL 도메인에 포함되는지 (또는 반대)
    # 예: email=sales@nuribom.com, source=nuribom.com → 통과
    # 예: email=ad@lonstech.co.kr, source=sncall.co.kr → 차단
    email_base = email_domain.replace("co.kr", "").replace("com", "").replace("net", "").replace("kr", "").strip(".")
    source_base = source_host.replace("co.kr", "").replace("com", "").replace("net", "").replace("kr", "").strip(".")

    if email_domain in source_host or source_host in email_domain:
        return False  # 매칭 → 통과
    if email_base and source_base and (email_base in source_base or source_base in email_base):
        return False  # 부분 매칭 → 통과

    return True  # 무관한 도메인 → 노이즈


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
def scrape_emails_from_url(url: str, apply_cross_domain_filter: bool = True) -> List[EmailHit]:
    """URL 본문 + 하위 연락처 페이지에서 이메일 추출.
    
    apply_cross_domain_filter: True이면 출처 URL과 무관한 제3자 이메일을 필터링.
    """
    hits: List[EmailHit] = []
    try:
        html = fetch_html(url)
    except Exception as e:
        log.debug("fetch 실패 %s: %s", url, e)
        return hits

    soup = BeautifulSoup(html, "lxml")
    for em in extract_emails_from_text(html):
        if apply_cross_domain_filter and is_cross_domain_noise(em, url):
            log.debug("cross-domain 필터링: %s (출처: %s)", em, url)
            continue
        hits.append(EmailHit(email=em, source_url=url, method="homepage"))

    # 하위 연락처 페이지 탐색
    for sub in find_contact_pages(soup, url):
        time.sleep(CRAWL_DELAY_SEC)
        try:
            html2 = fetch_html(sub)
        except Exception:
            continue
        for em in extract_emails_from_text(html2):
            if apply_cross_domain_filter and is_cross_domain_noise(em, sub):
                log.debug("cross-domain 필터링: %s (출처: %s)", em, sub)
                continue
            hits.append(EmailHit(email=em, source_url=sub, method="homepage"))

    return hits
