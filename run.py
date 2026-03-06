#!/usr/bin/env python3
"""나라장터 입찰공고 모니터링 프로그램.

'영상 제작' 관련 입찰공고가 등록되면 자동으로 알림을 보냅니다.

사용법:
    # 1회 실행 (cron 등록용)
    python run.py

    # 데몬 모드 (지속 실행)
    python run.py --daemon

    # 설정 파일 지정
    python run.py --config /path/to/config.yaml

    # 조회 기간 지정 (시간 단위)
    python run.py --hours 48
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from nara_monitor.api import NaraJangterAPI, filter_bids_by_keywords
from nara_monitor.notifier import create_notifiers, send_notifications
from nara_monitor.storage import BidStorage

logger = logging.getLogger("nara_monitor")


def setup_logging(verbose: bool = False) -> None:
    """로깅을 설정합니다."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(config_path: str) -> dict:
    """YAML 설정 파일을 로드합니다. 환경변수가 있으면 우선 사용합니다."""
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    else:
        logger.info(f"설정 파일 없음 ({config_path}), 환경변수에서 설정을 읽습니다.")
        config = {}

    # 환경변수가 있으면 config 값을 덮어쓰기 (GitHub Actions 용)
    if os.environ.get("NARA_API_KEY"):
        config["api_key"] = os.environ["NARA_API_KEY"]
    if os.environ.get("NARA_KEYWORDS"):
        config["keywords"] = [
            kw.strip() for kw in os.environ["NARA_KEYWORDS"].split(",") if kw.strip()
        ]
    if os.environ.get("NARA_EXCLUDE_KEYWORDS"):
        config["exclude_keywords"] = [
            kw.strip()
            for kw in os.environ["NARA_EXCLUDE_KEYWORDS"].split(",")
            if kw.strip()
        ]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.setdefault("notification", {})
        config["notification"].setdefault("telegram", {})
        config["notification"]["telegram"]["enabled"] = True
        config["notification"]["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config.setdefault("notification", {})
        config["notification"].setdefault("telegram", {})
        config["notification"]["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]

    # API 키 검증
    api_key = config.get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.error(
            "API 키가 설정되지 않았습니다. config.yaml의 api_key를 설정해주세요.\n"
            "API 키는 https://www.data.go.kr/data/15129394/openapi.do 에서 발급받을 수 있습니다."
        )
        sys.exit(1)

    return config


def check_bids(config: dict, storage: BidStorage, notifiers: list) -> int:
    """입찰공고를 조회하고 새 공고에 대해 알림을 보냅니다.

    Returns:
        새로 알림을 보낸 공고 건수
    """
    api = NaraJangterAPI(api_key=config["api_key"])

    hours = config.get("check_hours", 24)
    bid_type = config.get("bid_type", "services")
    keywords = config.get("keywords", [])
    exclude_keywords = config.get("exclude_keywords", [])

    logger.info(f"입찰공고 조회 시작 (최근 {hours}시간, 유형: {bid_type})")

    # API에서 입찰공고 조회
    if bid_type == "all":
        bids = api.fetch_all_types(hours=hours)
    else:
        bids = api.fetch_bids(bid_type=bid_type, hours=hours)

    logger.info(f"총 {len(bids)}건의 입찰공고 조회됨")

    if not bids:
        return 0

    # 키워드 필터링
    matched = filter_bids_by_keywords(bids, keywords, exclude_keywords)
    logger.info(f"키워드 매칭: {len(matched)}건")

    if not matched:
        send_notifications(notifiers, [])
        return 0

    # 이미 알림한 공고 제외
    new_bids = storage.filter_new_bids(matched)
    logger.info(f"새 공고: {new_bids and len(new_bids) or 0}건 (기존 알림 제외)")

    if not new_bids:
        send_notifications(notifiers, [])
        return 0

    # 알림 전송
    send_notifications(notifiers, new_bids)

    # DB에 기록
    storage.mark_many_notified(new_bids)

    return len(new_bids)


def run_once(config: dict) -> None:
    """1회 실행합니다."""
    db_path = config.get("db_path", "bid_history.db")
    storage = BidStorage(db_path=db_path)
    notifiers = create_notifiers(config)

    # 오래된 이력 정리
    storage.cleanup_old(days=90)

    count = check_bids(config, storage, notifiers)
    logger.info(f"실행 완료: {count}건 알림")


def run_daemon(config: dict) -> None:
    """데몬 모드로 실행합니다."""
    interval = config.get("schedule_interval_minutes", 30)
    db_path = config.get("db_path", "bid_history.db")
    storage = BidStorage(db_path=db_path)
    notifiers = create_notifiers(config)

    # 종료 시그널 처리
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logger.info("종료 신호를 받았습니다. 프로그램을 종료합니다.")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"데몬 모드 시작 (조회 간격: {interval}분)")
    logger.info(f"키워드: {config.get('keywords', [])}")

    while running:
        try:
            # 오래된 이력 정리
            storage.cleanup_old(days=90)

            count = check_bids(config, storage, notifiers)
            logger.info(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"조회 완료: {count}건 알림 / 다음 조회: {interval}분 후"
            )
        except Exception as e:
            logger.error(f"조회 중 오류 발생: {e}", exc_info=True)

        # 대기 (1초 단위로 체크하여 종료 시그널에 빠르게 반응)
        for _ in range(interval * 60):
            if not running:
                break
            time.sleep(1)

    logger.info("프로그램이 종료되었습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="나라장터 입찰공고 모니터링 - 영상 제작 관련 공고 알림",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="설정 파일 경로 (기본: config.yaml)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="데몬 모드로 실행 (지속 모니터링)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        help="조회 기간 (시간 단위, 설정 파일 값 덮어쓰기)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력",
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    # 설정 파일이 상대경로인 경우 스크립트 위치 기준으로 해석
    config_path = args.config
    if not Path(config_path).is_absolute():
        config_path = str(Path(__file__).parent / config_path)

    config = load_config(config_path)

    # CLI 인자로 설정 덮어쓰기
    if args.hours:
        config["check_hours"] = args.hours

    if args.daemon:
        run_daemon(config)
    else:
        run_once(config)


if __name__ == "__main__":
    main()
