"""애플 건강 데이터 내보내기(zip)에서 러닝 기록만 뽑아 data/runs.csv로 저장한다.

- 1GB가 넘는 XML을 압축을 풀지 않고 스트리밍으로 읽는다.
- 심박·수면 같은 다른 건강 기록과 GPS 경로는 저장하지 않는다.
- 예전에 구글 시트에서 받아둔 평균심박(data/sheet_overrides.csv)이 있으면 그 값으로 덮어쓴다.

사용법: python src/parse_runs.py [zip 경로]   (기본값: ~/Downloads/내보내기.zip)
"""

import csv
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from common import DATA_DIR, ROOT, device_label, load_hr_overrides, record_id

DEFAULT_ZIP = Path.home() / "Downloads" / "내보내기.zip"
OUT_CSV = DATA_DIR / "runs.csv"
RUNNING = "HKWorkoutActivityTypeRunning"
KM_PER_UNIT = {"km": 1, "m": 0.001, "mi": 1.609344}


def real_name(info: zipfile.ZipInfo) -> str:
    """UTF-8 플래그 없이 압축된 한글 파일명을 복원한다."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except UnicodeError:
        return info.filename


def find_export_xml(zf: zipfile.ZipFile) -> zipfile.ZipInfo:
    """export_cda.xml을 제외한 가장 큰 XML이 본 데이터다."""
    candidates = [
        i for i in zf.infolist()
        if real_name(i).endswith(".xml") and "export_cda" not in real_name(i)
    ]
    return max(candidates, key=lambda i: i.file_size)


def to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse_quantity(text: str | None) -> tuple[float | None, str]:
    """'79 degF', '6500 %', '12.3 m' 같은 메타데이터 값을 숫자와 단위로 나눈다."""
    if not text:
        return None, ""
    m = re.match(r"\s*([-\d.]+)\s*(.*)", text)
    return (float(m.group(1)), m.group(2).strip()) if m else (None, "")


def to_km(value: float | None, unit: str) -> float | None:
    if value is None or unit not in KM_PER_UNIT:
        return None
    return value * KM_PER_UNIT[unit]


def to_minutes(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return {"min": 1, "s": 1 / 60, "hr": 60}.get(unit, 1) * value


def workout_row(el) -> dict:
    """<Workout> 요소 하나를 평평한 딕셔너리로 바꾼다."""
    a = el.attrib
    stats, meta = {}, {}
    has_route = False
    for child in el:
        if child.tag == "WorkoutStatistics":
            key = child.get("type", "").replace("HKQuantityTypeIdentifier", "")
            stats[key] = child.attrib
        elif child.tag == "MetadataEntry":
            meta[child.get("key")] = child.get("value")
        elif child.tag == "WorkoutRoute":
            has_route = True

    start = datetime.strptime(a["startDate"], "%Y-%m-%d %H:%M:%S %z")
    duration = to_minutes(to_float(a.get("duration")), a.get("durationUnit", "min"))

    # 거리: 예전 iOS는 Workout 속성, 최근 iOS는 WorkoutStatistics에 들어 있다
    dist = stats.get("DistanceWalkingRunning")
    if dist:
        distance = to_km(to_float(dist.get("sum")), dist.get("unit", "km"))
    else:
        distance = to_km(to_float(a.get("totalDistance")), a.get("totalDistanceUnit", "km"))

    hr = stats.get("HeartRate", {})
    energy = stats.get("ActiveEnergyBurned", {})

    temp, temp_unit = parse_quantity(meta.get("HKWeatherTemperature"))
    if temp is not None and temp_unit == "degF":
        temp = (temp - 32) * 5 / 9
    humidity, _ = parse_quantity(meta.get("HKWeatherHumidity"))
    if humidity is not None and humidity > 100:  # 일부 기기는 65%를 6500으로 기록
        humidity /= 100
    elevation, elev_unit = parse_quantity(meta.get("HKElevationAscended"))
    if elevation is not None and elev_unit == "cm":
        elevation /= 100

    pace = duration / distance if duration and distance else None
    return {
        "type": a.get("workoutActivityType", ""),
        "date": start.date().isoformat(),
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "weekday": "월화수목금토일"[start.weekday()],
        "hour": start.hour,
        "duration_min": round(duration, 2) if duration else None,
        "distance_km": round(distance, 3) if distance else None,
        "pace_min_per_km": round(pace, 2) if pace else None,
        "avg_hr": round(to_float(hr.get("average")), 1) if hr.get("average") else None,
        "energy_kcal": round(to_float(energy.get("sum")), 1) if energy.get("sum") else None,
        "indoor": meta.get("HKIndoorWorkout") == "1",
        "temp_c": round(temp, 1) if temp is not None else None,
        "humidity_pct": round(humidity, 1) if humidity is not None else None,
        "elevation_gain_m": round(elevation, 1) if elevation is not None else None,
        "source": a.get("sourceName", ""),
        "has_route": has_route,
    }


def apply_sheet_overrides(runs: list[dict]) -> int:
    """구글 시트에서 채운 평균심박으로 덮어쓰고, 값이 바뀐 기록 수를 돌려준다."""
    overrides = load_hr_overrides()
    changed = 0
    for r in runs:
        rid = record_id(datetime.strptime(r["start"], "%Y-%m-%d %H:%M"), device_label(r["source"]))
        if rid in overrides and r["avg_hr"] != overrides[rid]:
            r["avg_hr"] = overrides[rid]
            changed += 1
    return changed


def main() -> None:
    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ZIP
    if not zip_path.exists():
        sys.exit(f"파일을 찾을 수 없음: {zip_path}")

    type_counts = Counter()
    runs = []
    with zipfile.ZipFile(zip_path) as zf:
        info = find_export_xml(zf)
        print(f"읽는 중: {real_name(info)} ({info.file_size / 1e9:.2f} GB) — 몇 분 걸릴 수 있어요")
        with zf.open(info) as f:
            context = iterparse(f, events=("start", "end"))
            _, root = next(context)
            depth = 1
            for event, el in context:
                if event == "start":
                    depth += 1
                    continue
                depth -= 1
                if depth != 1:
                    continue
                # 최상위 요소가 끝날 때만 처리하고 메모리를 비운다
                if el.tag == "Workout":
                    workout_type = el.get("workoutActivityType", "")
                    type_counts[workout_type] += 1
                    if workout_type == RUNNING:
                        runs.append(workout_row(el))
                root.clear()

    runs.sort(key=lambda r: r["start"])
    from_sheet = apply_sheet_overrides(runs)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(runs[0].keys()) if runs else ["type"])
        writer.writeheader()
        writer.writerows(runs)

    print("\n=== 운동 종류별 기록 수 ===")
    for t, c in type_counts.most_common(10):
        print(f"  {t.replace('HKWorkoutActivityType', '')}: {c}")

    if not runs:
        print("\n러닝 기록이 없음")
        return

    def filled(col: str) -> int:
        return sum(1 for r in runs if r[col] not in (None, ""))

    total_km = sum(r["distance_km"] or 0 for r in runs)
    print(f"\n=== 러닝 요약 ({OUT_CSV.relative_to(ROOT)}) ===")
    print(f"총 {len(runs)}회, {total_km:,.1f} km, 기간 {runs[0]['date']} ~ {runs[-1]['date']}")
    print(f"값이 있는 기록 수: 거리 {filled('distance_km')}, 심박 {filled('avg_hr')}, "
          f"기온 {filled('temp_c')}, 습도 {filled('humidity_pct')}, 경로 {sum(r['has_route'] for r in runs)}")
    print(f"구글 시트에서 가져온 평균심박으로 덮어쓴 기록: {from_sheet}회")
    print(f"실내 러닝: {sum(r['indoor'] for r in runs)}회")
    print(f"기록 기기/앱: {dict(Counter(r['source'] for r in runs))}")

    print("\n=== 연도별 ===")
    by_year = {}
    for r in runs:
        y = by_year.setdefault(r["date"][:4], [0, 0.0])
        y[0] += 1
        y[1] += r["distance_km"] or 0
    for year, (count, km) in sorted(by_year.items()):
        print(f"  {year}: {count}회, {km:,.1f} km")


if __name__ == "__main__":
    main()
