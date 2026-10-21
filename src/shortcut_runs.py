"""아이폰 단축어가 남긴 러닝 파일(data/run*.txt)을 러닝 기록으로 바꿔 data/shortcut_runs.csv에 쌓는다.

단축어 두 개가 iCloud Drive의 이 저장소 data/ 폴더에 파일을 남긴다.
- '러닝 시작' (달리기 시작될 때): start.txt  → START / 시작 시각
- '러닝 종료' (달리기 종료될 때): run.txt    → END / 종료 시각, LOCATION / 실내·실외,
                                             최근 하루치 애플워치 거리·심박 샘플 (시각과 값)

시작~종료 사이의 샘플만 골라 거리는 더하고 심박은 평균을 낸다. 시간은 종료-시작이라
일시정지한 시간도 들어간다. 처리한 러닝은 shortcut_runs.csv에 계속 쌓이고(시작 시각으로 중복을 거름),
run*.txt는 시트에 올라간 것이 확인되면 update.py가 지운다.

사용법: python src/shortcut_runs.py   (update.py가 자동으로 부른다)
"""

import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

from common import DATA_DIR, ROOT

START_FILE = DATA_DIR / "start.txt"
OUT_CSV = DATA_DIR / "shortcut_runs.csv"
SOURCE = "Apple Watch (단축어)"  # device_label()이 '애플워치'로 읽도록 Watch를 넣는다
MAX_RUN = timedelta(hours=4)  # start.txt가 이보다 오래됐으면 다른 러닝의 시작으로 본다
SAMPLE_GAP = timedelta(minutes=2)  # 시작 시각이 없을 때, 심박 샘플이 이만큼 끊기면 운동 밖으로 본다
FIELDS = [
    "type", "date", "start", "weekday", "hour", "duration_min", "distance_km", "pace_min_per_km",
    "avg_hr", "energy_kcal", "indoor", "temp_c", "humidity_pct", "elevation_gain_m", "source", "has_route",
]
KOREAN_DATE = re.compile(
    r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})\D+?(오전|오후|AM|PM)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"
)


def find_run_files() -> list[Path]:
    return sorted(DATA_DIR.glob("run*.txt"), key=lambda p: p.stat().st_mtime)


def parse_date(text: str) -> datetime:
    """ISO 8601을 기본으로 읽고, 단축어 기본 날짜 형식(2026. 10. 21. 오후 3:55)도 받아준다."""
    text = text.strip()
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        m = KOREAN_DATE.search(text)
        if not m:
            raise ValueError(f"날짜를 읽을 수 없어요: {text!r}")
        year, month, day, ampm, hour, minute, second = m.groups()
        hour = int(hour) % 12 + (12 if ampm in ("오후", "PM") else 0) if ampm else int(hour)
        value = datetime(int(year), int(month), int(day), hour, int(minute), int(second or 0))
    return value.astimezone()  # 시간대가 없으면 이 맥의 시간대로 본다


def read_sections(path: Path) -> dict[str, list[str]]:
    """'END', 'DIST_KM' 같은 제목 줄 아래의 값들을 묶는다."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if re.fullmatch(r"[A-Z_]+", line):
            current = sections.setdefault(line, [])
        elif line and current is not None:
            current.append(line)
    return sections


def samples(sections: dict[str, list[str]], time_key: str, value_key: str) -> list[tuple[datetime, float]]:
    times, values = sections.get(time_key, []), sections.get(value_key, [])
    if len(times) != len(values):
        raise ValueError(f"{time_key}({len(times)}개)와 {value_key}({len(values)}개)의 개수가 달라요")
    return [(parse_date(t), float(v.replace(",", ""))) for t, v in zip(times, values)]


def run_start(end: datetime, heart: list[tuple[datetime, float]]) -> datetime:
    """start.txt의 시작 시각을 쓰고, 없거나 이번 러닝 것이 아니면 심박 샘플이 촘촘한 구간으로 추정한다."""
    if START_FILE.exists():
        lines = [l.strip() for l in START_FILE.read_text(encoding="utf-8").splitlines()]
        lines = [l for l in lines if l and l != "START"]
        try:
            start = parse_date(lines[-1])
            if end - MAX_RUN < start < end:
                return start
        except (ValueError, IndexError):
            pass
    before_end = [t for t, _ in heart if t <= end]
    if not before_end:
        raise ValueError("시작 시각(start.txt)도, 심박 샘플도 없어 러닝 구간을 알 수 없어요")
    start = before_end[-1]
    for t in reversed(before_end[:-1]):
        if start - t > SAMPLE_GAP:
            break
        start = t
    return start


def run_row(path: Path) -> dict:
    sections = read_sections(path)
    if not sections.get("END"):
        raise ValueError("END(종료 시각)가 없어요")
    end = parse_date(sections["END"][0])
    distance = samples(sections, "DIST_TIME", "DIST_KM")
    heart = samples(sections, "HR_TIME", "HR_BPM")
    start = run_start(end, heart)

    km = sum(v for t, v in distance if start <= t <= end)
    bpm = [v for t, v in heart if start <= t <= end]
    minutes = (end - start).total_seconds() / 60
    location = (sections.get("LOCATION") or [""])[0]
    return {
        "type": "HKWorkoutActivityTypeRunning",
        "date": start.date().isoformat(),
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "weekday": "월화수목금토일"[start.weekday()],
        "hour": start.hour,
        "duration_min": round(minutes, 2),
        "distance_km": round(km, 3) if km else None,
        "pace_min_per_km": round(minutes / km, 2) if km else None,
        "avg_hr": round(sum(bpm) / len(bpm), 1) if bpm else None,
        "energy_kcal": None,
        "indoor": location == "실내",
        "temp_c": None,
        "humidity_pct": None,
        "elevation_gain_m": None,
        "source": SOURCE,
        "has_route": False,
    }


def collect() -> list[Path]:
    """새 러닝 파일을 shortcut_runs.csv에 더하고, 처리한 파일 목록을 돌려준다 (파일은 지우지 않음)."""
    existing = []
    if OUT_CSV.exists():
        with open(OUT_CSV, newline="", encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    known = {r["start"] for r in existing}

    processed, added = [], []
    for path in find_run_files():
        try:
            row = run_row(path)
        except (ValueError, OSError) as e:
            # iCloud에서 아직 다 내려받지 않은 파일일 수 있어 지우지 않고 다음 실행 때 다시 본다
            print(f"  ! {path.name} 건너뜀: {e}")
            continue
        processed.append(path)
        if row["start"] in known:
            print(f"  = {path.name}: {row['start']} 러닝은 이미 있어요")
            continue
        known.add(row["start"])
        added.append(row)
        place = "실내" if row["indoor"] else "실외"
        print(f"  + {path.name}: {row['date']} {place} {row['distance_km']}km, "
              f"{row['duration_min']:.1f}분, 평균심박 {row['avg_hr']}")

    if added:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(sorted(existing + added, key=lambda r: r["start"]))
        print(f"저장: {OUT_CSV.relative_to(ROOT)} (새 러닝 {len(added)}회)")
    return processed


if __name__ == "__main__":
    collect()
