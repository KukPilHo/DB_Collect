"""
Best-Pick 이메일 자동 선택
===========================
회사당 수집된 이메일 다건 중 가장 유효한 1~2건을 점수 기반으로 자동 선택.

점수 체계 (높을수록 우선):
- 이메일 도메인 == 출처URL 도메인     +50
- 출처가 homepage_direct               +30
- local-id가 비즈니스 역할              +20
- local-id가 개인명 패턴                +10
- 프리메일 도메인 (naver, gmail 등)     -5
- AI 필터링 걸림                        -100
"""

from typing import Dict, List
from urllib.parse import urlparse

from .scraper import FREE_MAIL_DOMAINS

# 비즈니스 역할 local-id
_BIZ_LOCALS = {
    "biz", "sales", "info", "contact", "ceo", "marketing",
    "cs", "support", "service", "inquiry", "admin",
    "business", "trade", "export", "import", "office",
    "sal",  # sal@haion.net 같은 약칭
}

# 점수 상수
SCORE_DOMAIN_MATCH = 50       # 이메일 도메인 == 출처URL 도메인
SCORE_HOMEPAGE_DIRECT = 30    # 홈페이지 직접 방문으로 수집
SCORE_BIZ_LOCAL = 20          # 비즈니스 역할 local-id
SCORE_PERSONAL_LOCAL = 10     # 개인명 패턴 local-id
SCORE_FREE_MAIL = -5          # 프리메일 패널티
SCORE_AI_FILTERED = -100      # AI 필터링 걸린 이메일


def _score_email(email: str, source_url: str, method: str) -> int:
    """이메일 한 건의 우선순위 점수를 계산."""
    score = 0
    email_lower = email.lower()
    local, _, email_domain = email_lower.partition("@")
    if not email_domain:
        return -999

    # 1) AI 필터링 걸린 이메일
    if "AI 필터링 걸림" in method:
        score += SCORE_AI_FILTERED

    # 2) 이메일 도메인 == 출처 URL 도메인
    source_host = urlparse(source_url).netloc.lower().replace("www.", "")
    if source_host and email_domain:
        # 정확 매칭 또는 부분 매칭
        email_base = email_domain.replace("co.kr", "").replace("com", "").replace("net", "").replace("kr", "").strip(".")
        source_base = source_host.replace("co.kr", "").replace("com", "").replace("net", "").replace("kr", "").strip(".")
        if (email_domain in source_host or source_host in email_domain or
                (email_base and source_base and (email_base in source_base or source_base in email_base))):
            score += SCORE_DOMAIN_MATCH

    # 3) 홈페이지 직접 방문
    clean_method = method.replace("[AI 필터링 걸림] ", "")
    if clean_method in ("homepage_direct", "homepage"):
        score += SCORE_HOMEPAGE_DIRECT

    # 4) 프리메일 패널티
    if email_domain in FREE_MAIL_DOMAINS:
        score += SCORE_FREE_MAIL

    # 5) local-id 역할 판단
    if local in _BIZ_LOCALS:
        score += SCORE_BIZ_LOCAL
    elif local.isalnum() and 2 <= len(local) <= 20:
        score += SCORE_PERSONAL_LOCAL

    return score


def select_best_picks(
    emails: List[Dict],
    max_picks: int = 2,
) -> List[Dict]:
    """
    회사별 수집 이메일 중 best-pick 최대 max_picks건을 선택.
    
    Parameters
    ----------
    emails : list of dict
        각 dict에 최소 '회사키', '이메일', '이메일_출처_URL', '이메일_방법', '상태' 키 필요.
    max_picks : int
        회사당 최대 선택 수.
    
    Returns
    -------
    list of dict
        best-pick 선택된 이메일 목록 (점수 순 정렬).
    """
    from collections import defaultdict

    # 회사키별 그룹화 (collected 상태만)
    by_company: Dict[str, List[Dict]] = defaultdict(list)
    for em in emails:
        if em.get("상태") == "collected":
            by_company[em["회사키"]].append(em)

    results: List[Dict] = []
    for 회사키, company_emails in by_company.items():
        # 점수 계산
        scored = []
        for em in company_emails:
            s = _score_email(
                em.get("이메일", ""),
                em.get("이메일_출처_URL", ""),
                em.get("이메일_방법", ""),
            )
            scored.append((s, em))

        # 점수 내림차순 정렬
        scored.sort(key=lambda x: x[0], reverse=True)

        # 상위 max_picks건 선택 (AI 필터링 걸린 것은 제외)
        picks = []
        seen_domains = set()
        for score, em in scored:
            if score <= SCORE_AI_FILTERED:
                continue  # AI 필터링 걸린 건 제외

            email_domain = em.get("이메일", "").lower().split("@")[-1]

            # 같은 도메인의 이메일은 1건만 (다양성 확보)
            if email_domain in seen_domains and email_domain not in FREE_MAIL_DOMAINS:
                continue

            em_with_score = {**em, "best_pick_점수": score, "best_pick_순위": len(picks) + 1}
            picks.append(em_with_score)
            seen_domains.add(email_domain)

            if len(picks) >= max_picks:
                break

        results.extend(picks)

    return results
"""
Description: Scoring-based best-pick auto-selection module for choosing 1-2 optimal emails per company.
"""
