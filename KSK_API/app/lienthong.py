import base64
import time
import uuid

import requests
from fastapi import HTTPException

from .config import Settings


_access_token: str | None = None


def _validate_config(settings: Settings) -> None:
    missing = [
        key for key, value in {
            "LIEN_THONG_BASE_URL": settings.lien_thong_base_url,
            "LIEN_THONG_USERNAME": settings.lien_thong_username,
            "LIEN_THONG_PASSWORD": settings.lien_thong_password,
            "LIEN_THONG_SENDER_ID": settings.lien_thong_sender_id,
        }.items() if not value
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu cau hinh: {', '.join(missing)}")


def _api_url(settings: Settings, path: str) -> str:
    return f"{settings.lien_thong_base_url.rstrip('/')}{path}"


def _remote_response(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return {"status_code": response.status_code, "body": body}


def login(settings: Settings, force: bool = False) -> tuple[str, dict]:
    global _access_token
    _validate_config(settings)
    if _access_token and not force:
        return _access_token, {"status_code": 200, "cached": True}
    try:
        response = requests.post(
            _api_url(settings, "/api/v1/resource/authentication/login"),
            json={"username": settings.lien_thong_username, "password": settings.lien_thong_password},
            timeout=settings.lien_thong_timeout_seconds,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail=f"Khong the ket noi API lien thong: {error}")

    result = _remote_response(response)
    body = result["body"]
    code = body.get("code") if isinstance(body, dict) else None
    data = body.get("data") if isinstance(body, dict) else None
    token = body.get("access_token") if isinstance(body, dict) else None
    if not token and isinstance(data, dict):
        token = data.get("access_token")
    if not response.ok or (code is not None and str(code) != "200") or not token:
        raise HTTPException(status_code=502, detail={"message": "Login lien thong that bai.", "response": result})
    _access_token = token
    return token, result


def build_envelope(raw_data: str, data_type: str, settings: Settings, supplied_signature: str) -> dict:
    current = time.localtime()
    send_datetime = int(time.time() * 1000)
    message_id = f"{settings.lien_thong_sender_id}{time.strftime('%y%m%d', current)}{uuid.uuid4().hex}"
    header = {
        "version": settings.lien_thong_version,
        "sender_id": settings.lien_thong_sender_id,
        "receiver_id": settings.lien_thong_receiver_id,
        "txn_type": "sync_checkup",
        "msg_type": "101",
        "data_type": data_type,
        "send_datetime": send_datetime,
        "msg_id": message_id,
    }
    encoded_data = base64.b64encode(raw_data.encode("utf-8")).decode("ascii")
    return {"header": header, "data": {"content": encoded_data}, "signature": supplied_signature.strip()}


def push(envelope: dict, settings: Settings) -> dict:
    token, login_result = login(settings)

    def send(access_token: str) -> requests.Response:
        return requests.post(
            _api_url(settings, "/api/v1/medical-record/ksk-lien-thong/kham-suc-khoe"),
            json=envelope,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=settings.lien_thong_timeout_seconds,
        )

    try:
        response = send(token)
        if response.status_code == 401:
            token, login_result = login(settings, force=True)
            response = send(token)
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail=f"Khong the day du lieu lien thong: {error}")
    return {"login": {"status_code": login_result["status_code"]}, "push": _remote_response(response)}
