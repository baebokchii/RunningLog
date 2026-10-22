"""피트니스 앱 운동 화면 스크린샷(data/의 이미지)을 읽어 data/runs.csv에 러닝 한 줄로 추가한다.

아이폰 공유 시트의 '러닝 기록 보내기' 단축어가 iCloud Drive의 이 저장소 data/에 이미지를 저장한다.
맥 내장 Vision(tools/ocr.swift, 인터넷 연결 없음)으로 글자를 읽어 아래 값을 뽑는다.

  실외 달리기 / 실내 달리기            → 장소
  2026년 10월 22일 20:14 ~ 20:31       → 날짜, 시작 시각 (기록ID에 씀)
  0:17:21                              → 운동 시간 (일시정지 제외)
  2.49KM                               → 거리
  6'57"/KM                             → 평균 페이스
  170BPM                               → 평균 심박수 (없을 수 있음)

잘못 읽었을 수 있으므로 운동 시간 ÷ 거리가 화면 페이스와 맞을 때만 받아들이고, 아니면 data/failed/로 옮긴다.
iCloud에서 아직 다 받지 않아 열리지 않는 이미지는 그대로 두었다가 다음 실행 때 다시 본다.
"""

import csv
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from common import DATA_DIR, ROOT

RUNS_CSV = DATA_DIR / "runs.csv"
FAILED_DIR = DATA_DIR / "failed"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heic"}
SOURCE = "Apple Watch (스크린샷)"  # device_label()이 '애플워치'로 읽도록 Watch를 넣는다
OCR_SOURCE = ROOT / "tools" / "ocr.swift"
OCR_BIN = Path.home() / "Library" / "Caches" / "RunningLog" / "ocr"
PACE_TOLERANCE_SEC = 3  # 화면의 거리·페이스가 반올림돼 있어 생기는 차이
STABLE_SEC = 2  # 파일 크기가 이 시간 동안 그대로면 iCloud에서 다 받은 것으로 본다
MAX_WAIT_SEC = 120

# OCR 줄에서 공백을 모두 뺀 뒤 찾는다
TITLE = re.compile(r"(실내|실외)달리기")
WHEN = re.compile(r"(\d{4})년(\d{1,2})월(\d{1,2})일(\d{1,2}):(\d{2})~")
DURATION = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")  # 상단 시계(20:50)와 헷갈리지 않게 시:분:초만
DISTANCE = re.compile(r"^(\d+\.\d+)KM$", re.IGNORECASE)
PACE = re.compile(r"^(\d{1,2})['’′](\d{2})[\"”″]?/KM$", re.IGNORECASE)
HEART = re.compile(r"^(\d{2,3})BPM$", re.IGNORECASE)


class ReadError(ValueError):
    """스크린샷에서 필요한 값을 읽지 못함."""


class NotReady(OSError):
    """iCloud에서 아직 다 내려받지 않은 이미지."""


def find_images() -> list[Path]:
    return sorted(p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def wait_until_downloaded(image: Path) -> None:
    deadline = time.time() + MAX_WAIT_SEC
    last = -1
    while time.time() < deadline:
        size = len(image.read_bytes())  # 끝까지 읽으면 macOS가 iCloud에서 다 받을 때까지 기다려 준다
        if size > 0 and size == last:
            return
        last = size
        time.sleep(STABLE_SEC)
    raise NotReady("iCloud에서 아직 내려받는 중이에요")


def ocr_lines(image: Path) -> list[str]:
    if not OCR_BIN.exists() or OCR_BIN.stat().st_mtime < OCR_SOURCE.stat().st_mtime:
        OCR_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(OCR_SOURCE), "-o", str(OCR_BIN)], check=True, capture_output=True)
    result = subprocess.run([str(OCR_BIN), str(image)], capture_output=True, text=True)
    if result.returncode != 0:
        # 이미지를 열지 못한 경우(예: 0 x 0)는 대개 아직 다 받지 않은 파일이다
        raise NotReady(result.stderr.strip() or "이미지를 열지 못했어요")
    return [line.replace(" ", "") for line in result.stdout.splitlines()]


def find(pattern: re.Pattern, lines: list[str], what: str) -> re.Match:
    for line in lines:
        if m := pattern.search(line):
            return m
    raise ReadError(f"{what}을(를) 찾지 못했어요")


def run_row(lines: list[str]) -> dict:
    """OCR 줄 → runs.csv 한 줄 (다른 열은 비워 둔다)."""
    indoor = find(TITLE, lines, "'실외/실내 달리기' 제목").group(1) == "실내"
    year, month, day, hour, minute = map(int, find(WHEN, lines, "날짜와 시작 시각").groups())
    start = datetime(year, month, day, hour, minute)
    h, m, s = map(int, find(DURATION, lines, "운동 시간").groups())
    minutes = h * 60 + m + s / 60
    km = float(find(DISTANCE, lines, "거리").group(1))
    pace_min, pace_sec = map(int, find(PACE, lines, "평균 페이스").groups())
    pace = pace_min + pace_sec / 60
    if abs(minutes / km - pace) * 60 > PACE_TOLERANCE_SEC:
        raise ReadError(f"운동 시간({minutes:.2f}분) ÷ 거리({km}km)가 화면 페이스와 맞지 않아요")
    try:
        heart = float(find(HEART, lines, "평균 심박수").group(1))
    except ReadError:
        heart = None

    return {
        "type": "HKWorkoutActivityTypeRunning",
        "date": start.date().isoformat(),
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "weekday": "월화수목금토일"[start.weekday()],
        "hour": start.hour,
        "duration_min": round(minutes, 2),
        "distance_km": km,
        "pace_min_per_km": round(pace, 4),  # 화면 거리는 반올림돼 있어 나눠 구하면 1초쯤 틀어진다
        "avg_hr": heart,
        "indoor": indoor,
        "source": SOURCE,
        "has_route": False,
    }


def collect() -> tuple[list[Path], list[str]]:
    """새 스크린샷을 runs.csv에 추가한다.

    처리한 이미지 목록(지우지 않음)과, 읽지 못해 data/failed/로 옮긴 이미지의 사유 목록을 돌려준다.
    """
    with open(RUNS_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        known = {r["start"] for r in reader}

    processed, failures, added = [], [], []
    for image in find_images():
        try:
            wait_until_downloaded(image)
            row = run_row(ocr_lines(image))
        except NotReady as e:
            print(f"  … {image.name}: 다 받아지면 다시 처리해요 ({e})")
            continue
        except ReadError as e:
            FAILED_DIR.mkdir(exist_ok=True)
            image.rename(FAILED_DIR / image.name)
            failures.append(f"{image.name}: {e}")
            print(f"  ! {image.name} → data/failed/ ({e})")
            continue
        processed.append(image)
        if row["start"] in known:
            print(f"  = {image.name}: {row['start']} 러닝은 이미 있어요")
            continue
        known.add(row["start"])
        added.append(row)
        print(f"  + {image.name}: {row['start']} {'실내' if row['indoor'] else '실외'} {row['distance_km']}km "
              f"{row['duration_min']:.1f}분 심박 {row['avg_hr']}")

    if added:
        with open(RUNS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writerows(added)
    return processed, failures
