"""data/runs_clean.csv에서 구글 시트에 아직 없는 러닝 기록만 골라 올리고, 전부 올라갔는지 확인한다.

구글 시트에 붙인 Apps Script 웹 앱(apps_script/Code.gs)에서
1) 이미 올라간 기록ID 목록을 받아오고
2) 그 목록에 없는 기록만 보낸 뒤 (웹 앱에서도 한 번 더 중복을 거른다)
3) 정리된 기록이 모두 시트에 있는지 다시 확인한다. 하나라도 없으면 실패로 끝난다.

필요한 설정 (.env): RUNNING_SHEET_URL, RUNNING_SHEET_TOKEN
사용법: python src/upload_sheet.py [--dry-run]
"""

import argparse
import json
import sys

import pandas as pd
import requests

from common import DATA_DIR, call_web_app, sheet_settings

RUNS_CSV = DATA_DIR / "runs_clean.csv"


def fetch_ids(url: str, token: str) -> set[str]:
    return set(call_web_app(requests.get(url, params={"token": token}, timeout=60))["ids"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="올리지 않고 새 기록만 보여줌")
    args = parser.parse_args()

    url, token = sheet_settings()
    runs = pd.read_csv(RUNS_CSV, dtype={"기록ID": str, "연월": str})
    existing = fetch_ids(url, token)
    new = runs[~runs["기록ID"].isin(existing)]

    print(f"시트에 있는 기록 {len(existing)}개 / 정리된 기록 {len(runs)}개 / 새 기록 {len(new)}개")
    if new.empty:
        print("올릴 새 기록이 없어요.")
    else:
        for r in new.itertuples(index=False):
            print(f"  + {r.날짜} {r.장소} {r.거리_km}km {r.페이스_표시}")
        if args.dry_run:
            print("(--dry-run: 업로드하지 않음)")
            return
        rows = json.loads(new.to_json(orient="records", force_ascii=False))
        result = call_web_app(requests.post(url, json={"token": token, "rows": rows}, timeout=120))
        print(f"업로드 완료: 추가 {result['added']}개, 중복으로 건너뜀 {result['skipped']}개, 시트 전체 {result['total']}개")
        existing = fetch_ids(url, token)

    missing = set(runs["기록ID"]) - existing
    if missing:
        sys.exit(f"시트 확인 실패: 정리된 기록 중 {len(missing)}개가 시트에 없어요.")
    print(f"시트 확인 완료: 정리된 기록 {len(runs)}개가 모두 시트에 있어요.")


if __name__ == "__main__":
    main()
