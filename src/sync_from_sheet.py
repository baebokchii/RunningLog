"""구글 시트에서 직접 채운 평균심박을 가져와 data/sheet_overrides.csv에 저장한다.

parse_runs.py가 이 파일로 data/runs.csv의 평균심박을 덮어쓰기 때문에,
건강 데이터를 새로 뽑아도 시트에서 채운 값이 유지된다.

심박이 없던 나이키 런클럽 기록을 채우려고 처음 한 번 실행했고, 이후 기록은 애플워치가 심박을 남기므로
자동 업데이트(update.py)에서는 실행하지 않는다. data/sheet_overrides.csv를 잃어버렸거나
시트에서 심박을 다시 고쳤을 때만 직접 실행한다.

사용법: python src/sync_from_sheet.py
"""

import sys

import pandas as pd
import requests

from common import DATA_DIR, SHEET_OVERRIDES_CSV, call_web_app, sheet_settings

RUNS_CLEAN_CSV = DATA_DIR / "runs_clean.csv"


def main() -> None:
    url, token = sheet_settings()
    body = call_web_app(requests.get(url, params={"token": token, "action": "rows"}, timeout=60))
    if "rows" not in body:
        sys.exit("시트 기록을 받지 못했어요. Apps Script 코드를 붙여넣고 '새 버전'으로 다시 배포했는지 확인하세요.")

    sheet = pd.DataFrame(body["rows"])
    if sheet.empty:
        print("시트가 비어 있어 가져올 값이 없어요.")
        return
    sheet["기록ID"] = sheet["기록ID"].astype(str)
    sheet["평균심박"] = pd.to_numeric(sheet["평균심박"], errors="coerce")
    # 이전 배포본은 날짜를 UTC 문자열('2024-09-09T15:00:00.000Z' = 한국 9/10 0시)로 보내므로 한국 날짜로 맞춘다
    iso = sheet["날짜"].astype(str).str.contains("T")
    sheet.loc[iso, "날짜"] = (
        pd.to_datetime(sheet.loc[iso, "날짜"], utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d")
    )
    overrides = sheet.loc[sheet["평균심박"].notna(), ["기록ID", "날짜", "평균심박"]]

    local = {}
    if RUNS_CLEAN_CSV.exists():
        clean = pd.read_csv(RUNS_CLEAN_CSV, dtype={"기록ID": str})
        local = dict(zip(clean["기록ID"], clean["평균심박"]))

    changed = overrides[[
        pd.isna(local.get(rid)) or local.get(rid) != hr
        for rid, hr in zip(overrides["기록ID"], overrides["평균심박"])
    ]]
    print(f"시트에 평균심박이 있는 기록 {len(overrides)}개 / 로컬 데이터와 다른 값 {len(changed)}개")
    for r in changed.itertuples(index=False):
        before = local.get(r.기록ID)
        before_text = "없음" if pd.isna(before) else f"{before:g}"
        print(f"  {r.날짜} 평균심박 {before_text} → {r.평균심박:g}")

    SHEET_OVERRIDES_CSV.parent.mkdir(parents=True, exist_ok=True)
    overrides[["기록ID", "평균심박"]].to_csv(SHEET_OVERRIDES_CSV, index=False, encoding="utf-8-sig")
    print(f"저장: data/{SHEET_OVERRIDES_CSV.name}")


if __name__ == "__main__":
    main()
