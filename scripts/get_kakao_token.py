"""
카카오 OAuth refresh_token 발급 헬퍼 — 1회 실행용.

사용 순서:
  1. https://developers.kakao.com → 내 애플리케이션 → 앱 생성
  2. 앱 설정 → 플랫폼 키 → REST API 키 수정 → 카카오 로그인 리다이렉트 URI 등록:
     http://localhost:3000/oauth
  3. 제품 설정 → 카카오 로그인 → 사용 설정 ON
  4. 카카오 로그인 → 동의항목 → 카카오톡 메시지 전송(talk_message) → 선택 동의
  5. 이 스크립트 실행: python scripts/get_kakao_token.py

스크립트가 자동으로:
  - 로컬 서버(:3000) 시작
  - 기본 브라우저로 카카오 인가 페이지 오픈
  - 인가 코드 수신 → 토큰 교환
  - 결과 출력

발급된 KAKAO_REFRESH_TOKEN, KAKAO_REST_API_KEY, KAKAO_CLIENT_SECRET 을 복사해서
GitHub 저장소 → Settings → Secrets and variables → Actions 에 등록.

토큰 만료 정책:
  - access_token: 6시간
  - refresh_token: 60일 (만료 1개월 전 갱신 시 자동 연장)
"""
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError


REDIRECT_URI = "http://localhost:3000/oauth"
LOCAL_PORT = 3000
AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


# 인가 코드 수신용 글로벌 (서버 콜백에서 채움)
_received = {"code": None, "error": None}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        _received["code"] = qs.get("code", [None])[0]
        _received["error"] = qs.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if _received["code"]:
            msg = "<h2 style='color:green;'>인가 코드 수신 완료!</h2><p>이 창을 닫고 터미널로 돌아가세요.</p>"
        else:
            msg = f"<h2 style='color:red;'>인가 실패: {_received['error']}</h2>"
        self.wfile.write(f"<html><body style='font-family:sans-serif;text-align:center;padding:50px;'>{msg}</body></html>".encode("utf-8"))

    def log_message(self, format, *args):
        return  # 콘솔 로그 억제


def exchange_code_for_tokens(rest_api_key: str, code: str, client_secret: str | None) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret

    body = urlencode(data).encode("utf-8")
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
    rest_api_key = input("REST API 키: ").strip()
    if not rest_api_key:
        print("REST API 키가 필요합니다.")
        return 1

    print()
    print("클라이언트 시크릿이 ON 이면 코드를 입력하세요. OFF면 엔터.")
    print("(카카오 콘솔 → 플랫폼 키 → REST API 키 수정 → 클라이언트 시크릿 > 카카오 로그인)")
    client_secret = input("클라이언트 시크릿 (없으면 엔터): ").strip() or None

    # 로컬 서버 시작
    server = HTTPServer(("localhost", LOCAL_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print()
    print(f"로컬 서버 시작됨 (포트 {LOCAL_PORT})")

    # 브라우저 오픈
    params = {
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    print("브라우저를 엽니다. 카카오 로그인 + 동의를 완료해 주세요...")
    print(f"(자동 오픈이 안 되면 직접 접속: {auth_url})")
    webbrowser.open(auth_url)

    # 인가 코드 대기 (최대 5분)
    import time
    deadline = time.time() + 300
    while time.time() < deadline:
        if _received["code"] or _received["error"]:
            break
        time.sleep(0.3)

    server.shutdown()

    if not _received["code"]:
        print(f"인가 코드 수신 실패: {_received['error'] or '시간 초과'}")
        return 1

    print("인가 코드 수신 완료. 토큰 발급 중...")
    try:
        tokens = exchange_code_for_tokens(rest_api_key, _received["code"], client_secret)
    except RuntimeError as e:
        print(f"토큰 발급 실패: {e}")
        return 1

    # 로컬 토큰 파일 저장 (.gitignored, 절대 커밋되지 않음)
    import os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    token_path = os.path.join(repo_root, "kakao_tokens.json")
    saved = {
        "rest_api_key": rest_api_key,
        "refresh_token": tokens.get("refresh_token"),
        "access_token": tokens.get("access_token"),
    }
    if client_secret:
        saved["client_secret"] = client_secret
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print("발급 성공")
    print("=" * 60)
    print()
    print(f"로컬 저장: {token_path}")
    print()
    print("GitHub Secrets에 등록할 값:")
    print(f"  KAKAO_REST_API_KEY    = {rest_api_key}")
    print(f"  KAKAO_REFRESH_TOKEN   = {tokens.get('refresh_token')}")
    if client_secret:
        print(f"  KAKAO_CLIENT_SECRET   = {client_secret}")
    print()
    print(f"(참고) access 만료(초)={tokens.get('expires_in')}, refresh 만료(초)={tokens.get('refresh_token_expires_in')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
