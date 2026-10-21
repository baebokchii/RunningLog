"""여러 스크립트가 함께 쓰는 경로, 기록ID, 구글 시트 연결 함수."""

import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def device_label(source: str) -> str:
    # 시트의 예전 기록에는 나이키 런클럽도 있어서 같은 이름 규칙을 유지한다
    return "애플워치" if "Watch" in source else "나이키 런클럽"


def record_id(start: datetime, device: str) -> str:
    """시작 시각과 기기로 만든 고유 ID. 시작 시각 자체는 공개 데이터에 넣지 않는다."""
    return hashlib.sha1(f"{start:%Y-%m-%d %H:%M}|{device}".encode()).hexdigest()[:12]


def sheet_settings() -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    url, token = os.getenv("RUNNING_SHEET_URL"), os.getenv("RUNNING_SHEET_TOKEN")
    if not url or not token:
        sys.exit(".env에 RUNNING_SHEET_URL과 RUNNING_SHEET_TOKEN을 설정하세요.")
    return url, token


def call_web_app(response: requests.Response) -> dict:
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError:
        sys.exit("웹 앱 응답이 JSON이 아니에요. 배포할 때 액세스 권한을 '모든 사용자'로 했는지 확인하세요.")
    if "error" in body:
        sys.exit(f"웹 앱 오류: {body['error']} → Apps Script의 스크립트 속성 TOKEN과 .env 값이 같은지 확인하세요.")
    return body
