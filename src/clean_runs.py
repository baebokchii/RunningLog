"""data/runs.csv를 정리해 Tableau와 구글 시트에서 쓸 CSV 두 개를 만든다.

정리 기준
- 같은 러닝이 애플워치와 나이키 런클럽에 중복 기록되면 애플워치 기록만 남긴다 (심박이 있어서).
- 거리 0.5km 미만은 뺀다 (기록 오류).
- 1km당 12분을 넘는 기록은 걷기·멈춤이 섞인 것으로 보고 뺀다.

결과
- data/runs_clean.csv : 러닝 1회 = 1행 (기록ID로 구글 시트 중복을 거른다)
- data/monthly.csv    : 월 1개 = 1행 (러닝이 없던 달도 0으로 포함)

공개 대시보드에 올라가므로 시작 시각과 GPS 정보는 넣지 않는다.
사용법: python src/clean_runs.py
"""

import pandas as pd

from common import DATA_DIR, ROOT, device_label, record_id

IN_CSV = DATA_DIR / "runs.csv"
RUNS_CSV = DATA_DIR / "runs_clean.csv"
MONTHLY_CSV = DATA_DIR / "monthly.csv"

MIN_DISTANCE_KM = 0.5
MAX_PACE_MIN_PER_KM = 12


def pace_label(pace: float) -> str:
    """6.25 → 6'15\" 형식."""
    minutes, seconds = int(pace), round((pace - int(pace)) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}'{seconds:02d}\""


def drop_duplicates_across_apps(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """시간이 겹치는 애플워치·나이키 런클럽 기록 쌍에서 나이키 쪽을 뺀다."""
    end = df["start"] + pd.to_timedelta(df["duration_min"], unit="m")
    watch = df[df["기기"] == "애플워치"]
    nrc = df[df["기기"] == "나이키 런클럽"]
    dup_index = {
        n for n in nrc.index for w in watch.index
        if df.at[w, "start"] < end[n] and df.at[n, "start"] < end[w]
    }
    return df.drop(index=list(dup_index)), len(dup_index)


def main() -> None:
    df = pd.read_csv(IN_CSV, parse_dates=["start"])
    df["기기"] = df["source"].map(device_label)
    total = len(df)

    df, dup_count = drop_duplicates_across_apps(df)
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

    # 러닝이 없던 달도 0으로 채워야 쉬었던 기간이 차트에 보인다
    months = pd.period_range(df["start"].min().to_period("M"), df["start"].max().to_period("M"), freq="M")
    grouped = runs.groupby("연월")
    monthly = pd.DataFrame(index=months.strftime("%Y-%m"))
    monthly["러닝_횟수"] = grouped.size()
    monthly["거리_km"] = grouped["거리_km"].sum().round(2)
    monthly["실내_횟수"] = runs[runs["장소"] == "실내"].groupby("연월").size()
    monthly["실외_횟수"] = runs[runs["장소"] == "실외"].groupby("연월").size()
    monthly = monthly.fillna(0)
    monthly[["러닝_횟수", "실내_횟수", "실외_횟수"]] = monthly[["러닝_횟수", "실내_횟수", "실외_횟수"]].astype(int)
    monthly["누적_거리_km"] = monthly["거리_km"].cumsum().round(1)
    monthly = monthly.rename_axis("연월").reset_index()
    monthly.to_csv(MONTHLY_CSV, index=False, encoding="utf-8-sig")

    print(f"원본 {total}회")
    print(f"  - 두 앱 중복: {dup_count}회 제외")
    print(f"  - 거리 {MIN_DISTANCE_KM}km 미만 또는 없음: {int(short.sum())}회 제외")
    print(f"  - 페이스 {MAX_PACE_MIN_PER_KM}분/km 초과 또는 없음: {int(slow.sum())}회 제외")
    print(f"→ 최종 {len(runs)}회, {runs['거리_km'].sum():,.1f} km ({runs['날짜'].min()} ~ {runs['날짜'].max()})")
    print(f"평균심박이 있는 기록: {runs['평균심박'].notna().sum()}회")
    print(f"저장: {RUNS_CSV.relative_to(ROOT)}, {MONTHLY_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
