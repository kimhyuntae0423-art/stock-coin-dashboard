"""
카카오 OAuth refresh_token 발급 헬퍼 — 1회 실행용.

사용 순서:
  1. https://developers.kakao.com → 내 애플리케이션 → 앱 생성
  2. 앱 설정 → 플랫폼 → Web 플랫폼 등록 (사이트 도메인: http://localhost)
  3. 카카오 로그인 활성화 → Redirect URI: http://localhost:8080/callback
  4. 카카오 로그인 → 동의항목 → "카카오톡 메시지 전송(talk_message)" 사용 ON
  5. 이 스크립트 실행 → 안내대로 브라우저에서 코드 받아오기

마지막에 print 되는 KAKAO_REFRESH_TOKEN 값을 복사해서
GitHub Secrets 에 등록 (Actions → secrets → New repository secret).

토큰 만료 정책:
  - access_token: 6시간
  - refresh_token: 60일 (만료 1개월 전 갱신 시 자동 연장)
"""
import json
import sys
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError


REDIRECT_URI = "http://localhost:8080/callback"
AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def get_auth_code_url(rest_api_key: str) -> str:
    params = {
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(rest_api_key: str, code: str) -> dict:
    body = urlencode({
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }).encode("utf-8")
    req = Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}")


def main():
    print("=" * 60)
    print("카카오 OAuth refresh_token 발급 도우미")
    print("=" * 60)
    print()
    print("준비:")
    print("  1) https://developers.kakao.com 에서 앱 생성")
    print("  2) 앱 설정 → 플랫폼 → Web → 사이트 도메인 http://localhost 추가")
    print("  3) 제품 설정 → 카카오 로그인 → ON")
    print("  4) 카카오 로그인 → Redirect URI 등록: " + REDIRECT_URI)
    print("  5) 카카오 로그인 → 동의항목 → '카카오톡 메시지 전송(talk_message)' ON")
    print()
    rest_api_key = input("앱의 REST API 키를 입력하세요: ").strip()
    if not rest_api_key:
        print("❌ REST API 키가 필요합니다.")
        return 1

    auth_url = get_auth_code_url(rest_api_key)
    print()
    print("브라우저에서 아래 URL을 여세요. 카카오 로그인 + 동의 후")
    print("'주소를 표시할 수 없습니다' 페이지로 이동합니다.")
    print("그때 주소창의 URL 전체를 복사해서 여기에 붙여넣으세요.")
    print()
    print(auth_url)
    print()

    redirected_url = input("리다이렉트된 전체 URL: ").strip()
    parsed = urlparse(redirected_url)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        print("❌ URL에서 code 파라미터를 찾을 수 없습니다.")
        print("   URL 형태: http://localhost:8080/callback?code=xxxxx")
        return 1

    print()
    print("토큰 발급 중...")
    try:
        tokens = exchange_code_for_tokens(rest_api_key, code)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1

    print()
    print("✓ 발급 성공")
    print()
    print("=" * 60)
    print("GitHub Secrets에 등록할 값")
    print("=" * 60)
    print()
    print(f"KAKAO_REST_API_KEY    = {rest_api_key}")
    print(f"KAKAO_REFRESH_TOKEN   = {tokens.get('refresh_token')}")
    print()
    print(f"(참고용) access_token = {tokens.get('access_token')}")
    print(f"          만료(초)   = access {tokens.get('expires_in')}, refresh {tokens.get('refresh_token_expires_in')}")
    print()
    print("GitHub 저장소 → Settings → Secrets and variables → Actions")
    print("New repository secret 으로 위 2개 등록.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
