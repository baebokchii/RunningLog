"""단축어 러닝 파일이 들어오면 계산 → 정리 → 업로드를 한 번에 실행한다.

data/에서 아이폰 단축어가 남긴 러닝 파일(run*.txt, src/shortcut_runs.py 참고)을 찾아 처리하고,
정리된 기록이 모두 구글 시트에 있는 것이 확인되면 러닝 파일을 삭제한다. (중간에 실패하면 삭제하지 않음)
러닝은 data/shortcut_runs.csv에 남아 있으므로 파일을 지워도 기록은 사라지지 않는다.

사용법
  python src/update.py                 직접 실행
  python src/update.py --dry-run       업로드와 파일 삭제 없이 새 기록만 확인
  python src/update.py --watch         자동 실행용 (launchd가 data/가 바뀔 때마다 호출)
                                       - 러닝 파일이 없으면 조용히 종료
                                       - 결과를 macOS 알림으로 표시
"""

import argparse
import fcntl
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import shortcut_runs

ROOT = Path(__file__).resolve().parents[1]
# launchd가 감시하는 data/ 밖에 둔다. 안에 두면 잠금 파일을 열 때마다 다시 실행된다
LOCK_FILE = Path(tempfile.gettempdir()) / "RunningLog-update.lock"


def run(*args: str) -> str:
    """하위 스크립트를 실행하고 출력을 로그에 남긴 뒤 돌려준다."""
    print(f"\n▶ {' '.join(args)}", flush=True)
    result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    print(result.stdout, end="", flush=True)
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr, flush=True)
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"{args[0]} 실패")
    return result.stdout


def notify(message: str) -> None:
    script = f'display notification {json.dumps(message, ensure_ascii=False)} with title "러닝 대시보드"'
    subprocess.run(["osascript", "-e", script], check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="업로드와 파일 삭제 없이 새 기록만 확인")
    parser.add_argument("--watch", action="store_true", help="자동 실행용")
    args = parser.parse_args()

    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("이미 다른 업데이트가 실행 중이라 종료해요.")
            return

        pending = shortcut_runs.find_run_files()
        if not pending:
            if not args.watch:  # watch 모드에서는 data/의 다른 변화라 할 일이 없음
                print("data/에 단축어 러닝 파일(run*.txt)이 없어요.")
            return

        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 처리할 파일: {', '.join(p.name for p in pending)}", flush=True)
        print("\n▶ 단축어 러닝 파일", flush=True)
        run_files = shortcut_runs.collect()
        if not run_files:
            return  # 아직 iCloud에서 다 내려받지 않은 파일만 있음. 다음 변화 때 다시 본다
        try:
            run("src/clean_runs.py")
            output = run("src/upload_sheet.py", *(["--dry-run"] if args.dry_run else []))
        except RuntimeError as e:
            if args.watch:
                notify(f"업데이트 실패: {e}")
            sys.exit(f"업데이트 실패: {e}")

        if args.dry_run:
            return

        # upload_sheet.py가 정리된 기록이 모두 시트에 있는 것을 확인했으므로 러닝 파일은 더 필요 없다
        for path in run_files:
            path.unlink()
        print(f"사용이 끝난 단축어 러닝 파일 {len(run_files)}개를 삭제했어요.", flush=True)

        if args.watch:
            summary = next(
                (line for line in output.splitlines() if line.startswith(("업로드 완료", "올릴 새 기록이 없어요"))),
                "업데이트 완료",
            )
            notify(summary)


if __name__ == "__main__":
    main()
