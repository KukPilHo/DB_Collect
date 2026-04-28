"""
AI 이메일 검증 필터
===================
OpenAI API (gpt-5.4-nano)를 사용하여 수집된 이메일이 해당 회사의 실제 이메일인지 검증.
"""

from typing import Optional
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

def is_valid_company_email(company_name: str, email: str, snippet: str) -> bool:
    """
    주어진 문맥(snippet)과 이메일이 해당 회사의 유효한 B2B 연락처인지 AI로 판별.
    """
    client = _get_client()
    if not client:
        # AI 필터 기능이 꺼져있거나 키가 없으면 항상 True (기존 로직 유지)
        return True
        
    prompt = f"""
You are an expert data validator for a B2B sales database.
Your task is to determine if the given email address is likely to be a direct or valid B2B contact email for the specified company, based on the provided text snippet.

Rule 1: Reject emails belonging to platforms, news sites, or directories (e.g., musinsa.com, cosinkorea.com, marketbz.com, naver blog platform emails) unless the target company is that platform.
Rule 2: Reject developer/creator platform emails (e.g., Chrome web store support emails) if they don't belong to the target company.
Rule 3: Return exactly "TRUE" if the email is valid for the company, or "FALSE" if it's invalid, a platform/spam email, or unrelated. No other text.

Company Name: {company_name}
Extracted Email: {email}
Context Snippet: {snippet}

Result (TRUE or FALSE):"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": "You are a strict data validation assistant."},
                {"role": "user", "content": prompt}
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
