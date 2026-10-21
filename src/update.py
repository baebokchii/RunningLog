"""건강 데이터 zip이나 단축어 러닝 파일이 들어오면 추출 → 정리 → 업로드를 한 번에 실행한다.

~/Downloads에서 가장 최근의 건강 데이터 zip('내보내기*.zip' 또는 'export*.zip')을,
data/에서 아이폰 단축어가 남긴 러닝 파일(run*.txt, src/shortcut_runs.py 참고)을 찾아 처리하고,
정리된 기록이 모두 구글 시트에 있는 것이 확인되면 zip과 러닝 파일을 삭제한다. (중간에 실패하면 삭제하지 않음)

사용법
  python src/update.py                 직접 실행
  python src/update.py --dry-run       업로드와 zip 삭제 없이 새 기록만 확인
  python src/update.py --zip 파일경로   다운로드 폴더가 아닌 특정 zip을 처리
  python src/update.py --watch         자동 실행용 (launchd가 다운로드 폴더나 data/가 바뀔 때마다 호출)
                                       - 건강 데이터 zip도 러닝 파일도 없으면 조용히 종료
                                       - AirDrop 전송이 끝날 때까지 기다린 뒤 처리
                                       - 결과를 macOS 알림으로 표시
"""

import argparse
import fcntl
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import shortcut_runs

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = Path.home() / "Downloads"
RAW_DIR = ROOT / "data" / "raw"
LEGACY_ZIP = RAW_DIR / "latest_export.zip"  # 이전 버전이 처리 후 옮겨두던 파일
# launchd가 감시하는 data/ 밖에 둔다. 안에 두면 잠금 파일을 열 때마다 다시 실행된다
LOCK_FILE = Path(tempfile.gettempdir()) / "RunningLog-update.lock"

STABLE_CHECK_SEC = 5  # 파일 크기가 이 시간 동안 그대로면 전송이 끝난 것으로 봄
MAX_WAIT_SEC = 15 * 60  # 전송 완료를 기다리는 최대 시간


def nfc(name: str) -> str:
    # macOS는 한글 파일명을 자모 분리형(NFD)으로 저장할 수 있어 비교 전에 NFC로 맞춘다
    return unicodedata.normalize("NFC", name)


def export_candidates() -> list[Path]:
    """이름이 건강 데이터 내보내기처럼 보이는 zip을 최신순으로."""
    zips = [
        p for p in DOWNLOADS.iterdir()
        if p.suffix == ".zip" and nfc(p.name).startswith(("내보내기", "export"))
    ]
    return sorted(zips, key=lambda p: p.stat().st_mtime, reverse=True)


def wait_until_complete(path: Path) -> bool:
    """AirDrop으로 받는 중인 파일은 크기가 멈추고 zip으로 열릴 때까지 기다린다."""
    deadline = time.time() + MAX_WAIT_SEC
    last_size = -1
    while time.time() < deadline:
        if not path.exists():
            return False
        size = path.stat().st_size
        if size == last_size and zipfile.is_zipfile(path):
            return True
        last_size = size
        time.sleep(STABLE_CHECK_SEC)
    return False


def is_health_export(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as zf:
        return any(name.startswith("apple_health_export/") for name in zf.namelist())


def find_export(wait: bool) -> Path | None:
    for path in export_candidates():
        if wait and not wait_until_complete(path):
            continue
        if is_health_export(path):
            return path
    return None


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
    parser.add_argument("--dry-run", action="store_true", help="업로드와 zip 삭제 없이 새 기록만 확인")
    parser.add_argument("--watch", action="store_true", help="자동 실행용")
    parser.add_argument("--zip", type=Path, help="처리할 건강 데이터 zip 경로")
    args = parser.parse_args()

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("이미 다른 업데이트가 실행 중이라 종료해요.")
            return

        if args.zip:
            if not (args.zip.exists() and is_health_export(args.zip)):
                sys.exit(f"건강 데이터 zip이 아니거나 파일이 없어요: {args.zip}")
            zip_path = args.zip
        else:
            zip_path = find_export(wait=args.watch)
        has_run_files = bool(shortcut_runs.find_run_files())
        if zip_path is None and not has_run_files:
            if args.watch:
                return  # 다운로드 폴더나 data/의 다른 변화라 할 일이 없음
            sys.exit(f"{DOWNLOADS}에 건강 데이터 zip(내보내기*.zip)도, data/에 단축어 러닝 파일도 없어요.")

        names = [nfc(zip_path.name)] if zip_path else []
        names += [p.name for p in shortcut_runs.find_run_files()]
        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 처리할 파일: {', '.join(names)}", flush=True)
        run_files = []
        try:
            if zip_path:
                run("src/parse_runs.py", str(zip_path))
            if has_run_files:
                print("\n▶ 단축어 러닝 파일", flush=True)
                run_files = shortcut_runs.collect()
                if not run_files and zip_path is None:
                    return  # 아직 iCloud에서 다 내려받지 않은 파일만 있음. 다음 변화 때 다시 본다
            run("src/clean_runs.py")
            output = run("src/upload_sheet.py", *(["--dry-run"] if args.dry_run else []))
        except RuntimeError as e:
            if args.watch and zip_path:
                # 같은 파일로 계속 다시 실패하지 않도록 옆으로 치워둔다 (삭제하지 않음)
                RAW_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(zip_path, RAW_DIR / f"failed_{datetime.now():%Y%m%d_%H%M%S}.zip")
            if args.watch:
                notify(f"업데이트 실패: {e}")
            sys.exit(f"업데이트 실패: {e}")

        if args.dry_run:
            return

        # upload_sheet.py가 정리된 기록이 모두 시트에 있는 것을 확인했으므로 원본 파일은 더 필요 없다
        # (단축어 러닝은 data/shortcut_runs.csv에 남아 있다)
        if zip_path:
            zip_path.unlink()
            print(f"사용이 끝난 {nfc(zip_path.name)}을(를) 삭제했어요.", flush=True)
        for path in run_files:
            path.unlink()
        if run_files:
            print(f"사용이 끝난 단축어 러닝 파일 {len(run_files)}개를 삭제했어요.", flush=True)
        if LEGACY_ZIP.exists():
            LEGACY_ZIP.unlink()
            print(f"이전에 보관하던 {LEGACY_ZIP.relative_to(ROOT)}도 삭제했어요.", flush=True)

        if args.watch:
            summary = next(
                (line for line in output.splitlines() if line.startswith(("업로드 완료", "올릴 새 기록이 없어요"))),
                "업데이트 완료",
            )
            notify(summary)


if __name__ == "__main__":
    main()
