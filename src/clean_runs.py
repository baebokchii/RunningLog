"""data/shortcut_runs.csv(단축어 러닝)를 정리해 구글 시트에 올릴 data/runs_clean.csv를 만든다.

예전 기록은 모두 구글 시트에 있으므로 여기서는 단축어로 들어온 러닝만 다룬다.
월별 요약은 시트의 Apps Script가 전체 기록으로 다시 계산한다.

정리 기준
- 거리 0.5km 미만은 뺀다 (테스트로 잠깐 켠 기록 등).
- 1km당 12분을 넘는 기록은 걷기·멈춤이 섞인 것으로 보고 뺀다.

공개 대시보드에 올라가므로 시작 시각은 넣지 않는다 (기록ID에만 쓴다).
사용법: python src/clean_runs.py
"""

import sys

import pandas as pd

from common import DATA_DIR, ROOT, device_label, record_id
from shortcut_runs import OUT_CSV as IN_CSV

RUNS_CSV = DATA_DIR / "runs_clean.csv"

MIN_DISTANCE_KM = 0.5
MAX_PACE_MIN_PER_KM = 12


def pace_label(pace: float) -> str:
    """6.25 → 6'15\" 형식."""
    minutes, seconds = int(pace), round((pace - int(pace)) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}'{seconds:02d}\""


def main() -> None:
    if not IN_CSV.exists():
        sys.exit(f"{IN_CSV.relative_to(ROOT)}이 없어요. 단축어 러닝 파일을 먼저 처리하세요.")
    df = pd.read_csv(IN_CSV, parse_dates=["start"])
    df["기기"] = df["source"].map(device_label)
    total = len(df)

    # 거리나 시간이 비어 있는 기록(NaN)은 비교식이 False라 걸러지지 않으므로 따로 뺀다
    short = df["distance_km"].isna() | (df["distance_km"] < MIN_DISTANCE_KM)
    df = df[~short]
    slow = df["pace_min_per_km"].isna() | (df["pace_min_per_km"] > MAX_PACE_MIN_PER_KM)
    df = df[~slow].sort_values("start")

    runs = pd.DataFrame({
        "기록ID": [record_id(s, d) for s, d in zip(df["start"], df["기기"])],
        "날짜": df["start"].dt.strftime("%Y-%m-%d"),
        "연월": df["start"].dt.strftime("%Y-%m"),
        "연도": df["start"].dt.year,
        "요일": df["weekday"],
        "장소": df["indoor"].map({True: "실내", False: "실외"}),
        "기기": df["기기"],
        "거리_km": df["distance_km"].round(2),
        "시간_분": df["duration_min"].round(1),
        "페이스_분_km": df["pace_min_per_km"].round(2),
        "페이스_표시": df["pace_min_per_km"].map(pace_label),
        "평균심박": df["avg_hr"],
    })
    runs.to_csv(RUNS_CSV, index=False, encoding="utf-8-sig")

    print(f"단축어 러닝 {total}회")
    print(f"  - 거리 {MIN_DISTANCE_KM}km 미만 또는 없음: {int(short.sum())}회 제외")
    print(f"  - 페이스 {MAX_PACE_MIN_PER_KM}분/km 초과 또는 없음: {int(slow.sum())}회 제외")
    print(f"→ 시트에 올릴 기록 {len(runs)}회 ({runs['거리_km'].sum():,.1f} km)")
    print(f"저장: {RUNS_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
