"""
카카오톡 '나에게 보내기' 알림.

전제:
  - Kakao Developers에서 앱 등록 + REST API 키 발급 완료
  - "카카오 로그인 > 동의항목 > 카카오톡 메시지 전송(talk_message)" 활성화
  - 사용자 OAuth 동의 후 refresh_token 획득 (한 번)

환경변수:
  KAKAO_ACCESS_TOKEN  : (권장) 유효한 access_token — 있으면 refresh 없이 바로 전송
  KAKAO_REST_API_KEY  : 앱의 REST API 키 (refresh 필요 시)
  KAKAO_REFRESH_TOKEN : OAuth refresh token (access_token 만료 시 폴백)
  KAKAO_CLIENT_SECRET : (선택) 클라이언트 시크릿이 ON인 경우 필수

토큰 우선순위: KAKAO_ACCESS_TOKEN → (401 시) refresh_token으로 갱신
이 레포는 토큰을 갱신·저장하지 않음. morning-briefing 레포가 토큰 관리 전담.

GitHub Actions에선 Secrets에 등록해서 사용.
로컬 테스트는 set $env:KAKAO_ACCESS_TOKEN = "..." 등.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

DEFAULT_DASH_URL = "https://stock-coin-dashboard-jdlrktuq3b7dzn5canhyeo.streamlit.app/"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def refresh_access_token(rest_api_key: str, refresh_token: str,
                         client_secret: str | None = None) -> dict:
    """refresh_token 으로 새 access_token 받기. refresh_token이 갱신될 수도 있음."""
    data = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret
    return _post(TOKEN_URL, data)   # access_token, optionally refresh_token


def _save_new_tokens(tok: dict) -> None:
    """갱신된 토큰을 new_tokens.json 에 저장. GitHub Actions 시크릿 업데이트 스텝이 읽음."""
    data = {"access_token": tok["access_token"]}
    if "refresh_token" in tok:
        data["refresh_token"] = tok["refresh_token"]
    path = os.path.join(_REPO_ROOT, "new_tokens.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print("토큰 갱신 완료 → new_tokens.json 저장")


def _load_local_tokens() -> dict | None:
    """저장소 루트의 kakao_tokens.json 이 있으면 로드 (로컬 테스트용)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "kakao_tokens.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _send_with_token(access_token: str, text: str, url: str, button_title: str) -> dict:
    template = {
        "object_type": "text",
        "text": text[:200],
        "link": {"web_url": url, "mobile_web_url": url},
        "button_title": button_title,
    }
    return _post(
        SEND_URL,
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access_token}"},
    )


def send_to_self(text: str, link_url: str | None = None,
                 button_title: str = "대시보드 열기") -> dict:
    """카카오톡 메모챗('나에게 보내기')으로 텍스트 메시지 발송.

    토큰 전략: KAKAO_ACCESS_TOKEN 우선 사용 → 401이면 refresh_token으로 재시도.
    이 레포는 갱신한 토큰을 저장하지 않음 (morning-briefing 레포가 전담).
    """
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    access_token = os.environ.get("KAKAO_ACCESS_TOKEN")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET") or None

    # 환경변수 없으면 로컬 파일에서 로드 (로컬 테스트용)
    if not api_key or not refresh_token:
        local = _load_local_tokens()
        if local:
            api_key = api_key or local.get("rest_api_key")
            access_token = access_token or local.get("access_token")
            refresh_token = refresh_token or local.get("refresh_token")
            client_secret = client_secret or local.get("client_secret")

    url = link_url or DEFAULT_DASH_URL

    # 1) ACCESS_TOKEN 있으면 먼저 시도 (refresh 없음 → 토큰 충돌 방지)
    if access_token:
        try:
            return _send_with_token(access_token, text, url, button_title)
        except RuntimeError as e:
            if "401" not in str(e):
                raise
            # 401 → 토큰 만료, refresh로 재시도

    # 2) refresh_token으로 새 access_token 발급 (폴백)
    if not api_key or not refresh_token:
        raise RuntimeError(
            "KAKAO_ACCESS_TOKEN 또는 KAKAO_REST_API_KEY/KAKAO_REFRESH_TOKEN 환경변수 필요"
        )
    tok = refresh_access_token(api_key, refresh_token, client_secret)
    _save_new_tokens(tok)
    return _send_with_token(tok["access_token"], text, url, button_title)


if __name__ == "__main__":
    # 간단 테스트
    print(send_to_self("📊 카카오 알림 테스트 — 셋업 정상"))
