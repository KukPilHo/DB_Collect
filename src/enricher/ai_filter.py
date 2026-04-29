"""
AI 이메일 검증 필터
===================
OpenAI API (gpt-5.4-nano)를 사용하여 수집된 이메일이 해당 회사의 실제 이메일인지 검증.
규칙 기반 사전 필터 + AI 판별 2단계.
"""

from typing import Optional
from urllib.parse import urlparse

from openai import OpenAI
from src.config import log, OPENAI_API_KEY, USE_AI_FILTER

# 모듈 로드 시 클라이언트 한 번만 초기화
_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if not USE_AI_FILTER or not OPENAI_API_KEY:
        return None
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


# ── 규칙 기반 사전 필터 ──────────────────────────────────────

# 이 도메인에서 수집된 이메일은 무조건 노이즈 (뉴스 기자, 디렉토리 고정 이메일 등)
_NOISE_SOURCE_DOMAINS = {
    "it.donga.com", "itdonga.com", "zdnet.co.kr", "aitimes.kr",
    "etnews.com", "newstown.co.kr", "investnews.co.kr", "kihoilbo.co.kr",
    "hellodd.com", "sejungilbo.com", "cosinkorea.com", "techsuda.com",
    "inven.co.kr", "ruliweb.com",
    "rome2rio.com", "play.google.com",
    "prezi.com", "namu.wiki", "urlquery.net",
}

# naver.com / gmail.com 등 프리 메일은 AI 판별 대신 바로 통과시키되
# 출처가 노이즈 사이트가 아닌 경우에만
_FREE_MAIL_DOMAINS = {
    "naver.com", "gmail.com", "hanmail.net", "daum.net",
    "nate.com", "hotmail.com", "outlook.com", "outlook.kr",
    "yahoo.com", "yahoo.co.kr",
}


def _extract_source_domain(snippet: str) -> str:
    """snippet에서 출처 URL 도메인 추출."""
    for token in snippet.split():
        if token.startswith(("http://", "https://")):
            try:
                return urlparse(token).netloc.replace("www.", "")
            except Exception:
                pass
    # "Source URL: ..." 또는 "Homepage: ..." 패턴
    for prefix in ("Source URL:", "Homepage:"):
        if prefix in snippet:
            url_part = snippet.split(prefix, 1)[1].strip().split()[0]
            try:
                return urlparse(url_part).netloc.replace("www.", "")
            except Exception:
                pass
    return ""


def _rule_based_filter(company_name: str, email: str, snippet: str) -> Optional[bool]:
    """
    규칙 기반 사전 판별. 확실한 경우만 판별하고, 불확실하면 None 반환 (→ AI로 넘김).
    True = 유효, False = 거부, None = AI 판별 필요.
    """
    email_lower = email.lower()
    email_domain = email_lower.split("@")[1] if "@" in email_lower else ""
    source_domain = _extract_source_domain(snippet)

    # 1) 출처가 노이즈 사이트면 무조건 거부
    if source_domain:
        for noise in _NOISE_SOURCE_DOMAINS:
            if source_domain == noise or source_domain.endswith("." + noise):
                return False

    # 2) 프리메일 (naver.com, gmail.com 등) → AI로 넘김 (회사 담당자일 수도 있음)
    if email_domain in _FREE_MAIL_DOMAINS:
        return None  # AI 판별

    # 3) 이메일 도메인 = 출처 URL 도메인 → 해당 사이트 자체 이메일이므로 유효
    if email_domain and source_domain and email_domain == source_domain:
        return True

    return None  # AI 판별 필요


def is_valid_company_email(company_name: str, email: str, snippet: str) -> bool:
    """
    주어진 문맥(snippet)과 이메일이 해당 회사의 유효한 B2B 연락처인지 판별.
    1단계: 규칙 기반 사전 필터 (확실한 케이스)
    2단계: AI 판별 (불확실한 케이스)
    """
    # 1단계: 규칙 기반
    rule_result = _rule_based_filter(company_name, email, snippet)
    if rule_result is not None:
        if not rule_result:
            log.info("[Rule Filter] 거절됨: %s - %s", company_name, email)
        return rule_result

    # 2단계: AI 판별
    client = _get_client()
    if not client:
        return True

    prompt = f"""You are a B2B email validator. Determine if this email belongs to or is a valid contact for the target company.

TRUE if:
- Email domain matches or is related to the company
- Email is a business contact (info@, sales@, cs@, contact@, or personal name) found on a relevant page
- Email belongs to an employee of the target company

FALSE if:
- Email belongs to a news site, reporter, or media outlet
- Email belongs to a completely different/unrelated company
- Email is a generic platform email (e.g., support@sentry.io, ads@teamblind.com)
- Email is clearly spam or a placeholder

Company: {company_name}
Email: {email}
Context: {snippet}

Answer TRUE or FALSE only:"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": "You are a strict data validation assistant. Answer only TRUE or FALSE."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_completion_tokens=5,
        )

        answer = response.choices[0].message.content.strip().upper()
        if "FALSE" in answer:
            log.info("[AI Filter] 거절됨: %s - %s", company_name, email)
            return False
        return True

    except Exception as e:
        log.warning("[AI Filter] API 호출 실패 (허용으로 폴백): %s", e)
        return True
