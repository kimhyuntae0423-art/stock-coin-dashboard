"""
카카오톡 '나에게 보내기' 알림.

전제:
  - Kakao Developers에서 앱 등록 + REST API 키 발급 완료
  - "카카오 로그인 > 동의항목 > 카카오톡 메시지 전송(talk_message)" 활성화
  - 사용자 OAuth 동의 후 refresh_token 획득 (한 번)

환경변수:
  KAKAO_REST_API_KEY  : 앱의 REST API 키
  KAKAO_REFRESH_TOKEN : OAuth refresh token

GitHub Actions에선 Secrets에 등록해서 사용.
로컬 테스트는 set $env:KAKAO_REST_API_KEY = "..." 등.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

DEFAULT_DASH_URL = "https://stock-coin-dashboard-jdlrktuq3b7dzn5canhyeo.streamlit.app/"


def _post(url: str, data: dict, headers: dict | None = None):
    body = urlencode(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}")


def refresh_access_token(rest_api_key: str, refresh_token: str) -> dict:
    """refresh_token 으로 새 access_token 받기. refresh_token이 갱신될 수도 있음."""
    result = _post(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    })
    return result   # access_token, optionally refresh_token


def send_to_self(text: str, link_url: str | None = None,
                 button_title: str = "대시보드 열기") -> dict:
    """카카오톡 메모챗('나에게 보내기')으로 텍스트 메시지 발송."""
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not api_key or not refresh_token:
        raise RuntimeError(
            "KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 환경변수 필요"
        )

    tok = refresh_access_token(api_key, refresh_token)
    access_token = tok["access_token"]

    url = link_url or DEFAULT_DASH_URL
    template = {
        "object_type": "text",
        "text": text[:200],  # 카카오 메시지 한도 200자
        "link": {"web_url": url, "mobile_web_url": url},
        "button_title": button_title,
    }
    return _post(
        SEND_URL,
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access_token}"},
    )


if __name__ == "__main__":
    # 간단 테스트
    print(send_to_self("📊 카카오 알림 테스트 — 셋업 정상"))
