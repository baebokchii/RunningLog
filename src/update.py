"""피트니스 앱 스크린샷이 들어오면 글자 읽기 → 정리 → 업로드를 한 번에 실행하고 결과를 macOS 알림으로 띄운다.

launchd가 data/가 바뀔 때마다 실행한다. 스크린샷이 없으면 바로 끝난다.
정리된 기록이 모두 구글 시트에 있는 것이 확인되면 스크린샷을 지운다 (러닝은 data/runs.csv에 남아 있다).

사용법: python src/update.py
"""

import fcntl
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import clean_runs
import screenshot_runs
import upload_sheet

# launchd가 감시하는 data/ 밖에 둔다. 안에 두면 잠금 파일을 열 때마다 다시 실행된다
LOCK_FILE = Path(tempfile.gettempdir()) / "RunningLog-update.lock"


def notify(message: str) -> None:
    script = f'display notification {json.dumps(message, ensure_ascii=False)} with title "러닝 대시보드"'
    subprocess.run(["osascript", "-e", script], check=False)


def main() -> None:
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # 다른 실행이 이미 처리 중

        pending = screenshot_runs.find_images()
        if not pending:
            return  # data/의 다른 변화
        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 처리할 스크린샷: {', '.join(p.name for p in pending)}", flush=True)

        images, failures = screenshot_runs.collect()
        if failures:
            notify(f"스크린샷을 읽지 못했어요 (data/failed/에 둠): {failures[0]}")
        if not images:
            return
        try:
            clean_runs.main()
            summary = upload_sheet.main()
        except (Exception, SystemExit) as e:
            print(f"업데이트 실패: {e}", flush=True)
            notify(f"업데이트 실패: {e}")
            raise SystemExit(1)

        for image in images:
            image.unlink()
        print(f"사용이 끝난 스크린샷 {len(images)}개를 삭제했어요.", flush=True)
        notify(summary)


if __name__ == "__main__":
    main()
