#!/usr/bin/env python3
"""나라장터 입찰공고 Telegram 대화형 봇.

알림에 포함된 '상세 정보' 버튼을 누르면 해당 공고의 세부 정보를 보내줍니다.

사용법:
    python bot.py
    python bot.py --config config.yaml
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

from nara_monitor.storage import BidStorage, get_subscriber_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
NARA_API_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"


def load_config(config_path: str) -> dict:
    """설정을 로드합니다."""
    config = {}
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

    # 환경변수 우선
    if os.environ.get("NARA_API_KEY"):
        config["api_key"] = os.environ["NARA_API_KEY"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.setdefault("notification", {}).setdefault("telegram", {})
        config["notification"]["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config.setdefault("notification", {}).setdefault("telegram", {})
        config["notification"]["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]

    return config


def telegram_request(token: str, method: str, **kwargs) -> Optional[dict]:
    """Telegram Bot API를 호출합니다."""
    url = TELEGRAM_API.format(token=token, method=method)
    try:
        resp = requests.post(url, json=kwargs, timeout=60)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Telegram API 오류: {data}")
            return None
        return data.get("result")
    except Exception as e:
        logger.error(f"Telegram API 요청 실패: {e}")
        return None


def fetch_bid_detail(api_key: str, bid_no: str, bid_ord: str) -> Optional[dict]:
    """나라장터 API에서 공고 상세 정보를 조회합니다.

    점진적으로 검색 범위를 넓히며 페이지네이션으로 특정 공고를 찾습니다.
    """
    from datetime import datetime, timedelta

    now = datetime.now()

    # 점진적으로 범위를 넓혀가며 검색 (3일 → 14일 → 60일)
    search_ranges = [3, 14, 60]

    for days in search_ranges:
        start_dt = (now - timedelta(days=days)).strftime("%Y%m%d%H%M")
        end_dt = now.strftime("%Y%m%d%H%M")

        logger.info(f"공고 {bid_no} 검색 중 (최근 {days}일)...")

        page = 1
        while page <= 20:  # 최대 20페이지 (약 20,000건)
            params = {
                "ServiceKey": api_key,
                "pageNo": page,
                "numOfRows": 999,
                "bidNtceBgnDt": start_dt,
                "bidNtceEndDt": end_dt,
                "type": "json",
            }

            try:
                resp = requests.get(NARA_API_URL, params=params, timeout=30)
                data = resp.json()
                body = data.get("response", {}).get("body", {})
                total_count = int(body.get("totalCount", 0))
                items = body.get("items", [])

                if isinstance(items, dict):
                    items = [items]

                if not items:
                    break

                for item in items:
                    if item.get("bidNtceNo") == bid_no:
                        if item.get("bidNtceOrd") == bid_ord or bid_ord == "000":
                            logger.info(f"공고 {bid_no} 발견 (페이지 {page})")
                            return item

                # 모든 페이지를 확인했으면 다음 범위로
                if page * 999 >= total_count:
                    break
                page += 1

            except Exception as e:
                logger.error(f"API 조회 실패 (페이지 {page}): {e}")
                break

    logger.warning(f"공고 {bid_no} 찾을 수 없음")
    return None


def _format_price(value) -> str:
    if not value:
        return "-"
    try:
        num = int(float(str(value)))
        if num >= 100_000_000:
            return f"{num / 100_000_000:.1f}억원 ({num:,}원)"
        elif num >= 10_000:
            return f"{num / 10_000:,.0f}만원 ({num:,}원)"
        else:
            return f"{num:,}원"
    except (ValueError, TypeError):
        return str(value)


def format_detail_message(bid: dict) -> str:
    """공고 상세 정보를 메시지로 포맷합니다."""
    # 문서 링크 수집
    docs = []
    for i in range(1, 11):
        url = bid.get(f"ntceSpecDocUrl{i}", "")
        name = bid.get(f"ntceSpecFileNm{i}", "")
        if url and name:
            docs.append(f'  📎 <a href="{url}">{name}</a>')

    docs_text = "\n".join(docs) if docs else "  (첨부 문서 없음)"

    detail_url = bid.get("bidNtceDtlUrl", "") or bid.get("bidNtceUrl", "")

    text = (
        f"📋 <b>입찰공고 상세 정보</b>\n"
        f"\n"
        f"📌 <b>{bid.get('bidNtceNm', '')}</b>\n"
        f"\n"
        f"<b>▸ 기본 정보</b>\n"
        f"  • 공고번호: {bid.get('bidNtceNo', '')}-{bid.get('bidNtceOrd', '')}\n"
        f"  • 공고종류: {bid.get('ntceKindNm', '')}\n"
        f"  • 용역구분: {bid.get('srvceDivNm', '')}\n"
        f"  • 조달분류: {bid.get('pubPrcrmntClsfcNm', '')}\n"
        f"\n"
        f"<b>▸ 기관 정보</b>\n"
        f"  • 공고기관: {bid.get('ntceInsttNm', '')}\n"
        f"  • 수요기관: {bid.get('dminsttNm', '')}\n"
        f"  • 담당자: {bid.get('ntceInsttOfclNm', '')} ({bid.get('ntceInsttOfclTelNo', '')})\n"
        f"\n"
        f"<b>▸ 금액 정보</b>\n"
        f"  • 배정예산: {_format_price(bid.get('asignBdgtAmt', ''))}\n"
        f"  • 추정가격: {_format_price(bid.get('presmptPrce', ''))}\n"
        f"  • 부가세: {_format_price(bid.get('VAT', ''))}\n"
        f"\n"
        f"<b>▸ 입찰 정보</b>\n"
        f"  • 계약방법: {bid.get('cntrctCnclsMthdNm', '')}\n"
        f"  • 낙찰방법: {bid.get('sucsfbidMthdNm', '')}\n"
        f"  • 입찰방식: {bid.get('bidMethdNm', '')}\n"
        f"  • 기술평가: {bid.get('techAbltEvlRt', '-')}% / 가격평가: {bid.get('bidPrceEvlRt', '-')}%\n"
        f"  • 예가방법: {bid.get('prearngPrceDcsnMthdNm', '')}\n"
        f"\n"
        f"<b>▸ 일정</b>\n"
        f"  • 공고일시: {bid.get('bidNtceDt', '')}\n"
        f"  • 입찰시작: {bid.get('bidBeginDt', '')}\n"
        f"  • 입찰마감: {bid.get('bidClseDt', '')}\n"
        f"  • 개찰일시: {bid.get('opengDt', '')}\n"
        f"\n"
        f"<b>▸ 첨부 문서 (과업지시서/규격서)</b>\n"
        f"{docs_text}\n"
        f"\n"
        f'🔗 <a href="{detail_url}">나라장터에서 보기</a>'
    )

    return text


def handle_callback(token: str, api_key: str, callback_query: dict) -> None:
    """인라인 버튼 콜백을 처리합니다."""
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")

    if not data.startswith("detail:"):
        telegram_request(token, "answerCallbackQuery",
                         callback_query_id=callback_id)
        return

    # 콜백 응답 (로딩 표시 제거) — 실패해도 무시 (오래된 콜백일 수 있음)
    telegram_request(token, "answerCallbackQuery",
                     callback_query_id=callback_id,
                     text="상세 정보를 불러오는 중...")

    parts = data.replace("detail:", "").split(":")
    bid_no = parts[0]
    bid_ord = parts[1] if len(parts) > 1 else "000"

    logger.info(f"상세 조회 요청: {bid_no}-{bid_ord}")

    # "조회 중" 메시지를 먼저 보내서 사용자에게 즉시 피드백
    loading_msg = telegram_request(token, "sendMessage",
                                   chat_id=chat_id,
                                   text=f"🔍 공고 {bid_no} 상세 정보 조회 중...")

    bid = fetch_bid_detail(api_key, bid_no, bid_ord)
    if bid:
        text = format_detail_message(bid)
    else:
        text = f"❌ 공고 {bid_no} 상세 정보를 찾을 수 없습니다.\n나라장터에서 직접 확인해주세요."

    # 조회 완료 후 "조회 중" 메시지를 상세 정보로 교체
    if loading_msg and loading_msg.get("message_id"):
        telegram_request(token, "editMessageText",
                         chat_id=chat_id,
                         message_id=loading_msg["message_id"],
                         text=text,
                         parse_mode="HTML",
                         disable_web_page_preview=True)
    else:
        telegram_request(token, "sendMessage",
                         chat_id=chat_id,
                         text=text,
                         parse_mode="HTML",
                         disable_web_page_preview=True)


def handle_message(token: str, api_key: str, message: dict, storage: BidStorage = None) -> None:
    """텍스트 메시지를 처리합니다."""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if text in ("/start", "시작"):
        # 구독자 등록
        if storage:
            username = message.get("from", {}).get("username", "")
            storage.add_subscriber(str(chat_id), username)
            logger.info(f"새 구독자 등록: {chat_id} (@{username})")

        telegram_request(token, "sendMessage",
                         chat_id=chat_id,
                         text="🔔 나라장터 입찰공고 모니터링 봇입니다.\n\n"
                              "✔️ 알림 구독이 완료되었습니다!\n"
                              "매일 오전 9시에 영상 제작 관련 새 입찰공고를 알려드립니다.\n\n"
                              "• 공고번호로 직접 조회도 가능합니다.\n"
                              "  예: <code>/detail R26BK01362685</code>",
                         parse_mode="HTML")

    elif text.startswith("/detail"):
        parts = text.split()
        if len(parts) < 2:
            telegram_request(token, "sendMessage",
                             chat_id=chat_id,
                             text="사용법: /detail 공고번호\n예: <code>/detail R26BK01362685</code>",
                             parse_mode="HTML")
            return

        bid_no = parts[1]
        bid_ord = parts[2] if len(parts) > 2 else "000"

        telegram_request(token, "sendMessage",
                         chat_id=chat_id,
                         text=f"🔍 {bid_no} 조회 중...")

        bid = fetch_bid_detail(api_key, bid_no, bid_ord)
        if bid:
            msg = format_detail_message(bid)
        else:
            msg = f"❌ 공고 {bid_no} 상세 정보를 찾을 수 없습니다."

        telegram_request(token, "sendMessage",
                         chat_id=chat_id,
                         text=msg,
                         parse_mode="HTML",
                         disable_web_page_preview=True)


def process_pending_updates(config: dict) -> int:
    """대기 중인 업데이트를 처리하고 종료합니다 (GitHub Actions 용)."""
    tg_config = config.get("notification", {}).get("telegram", {})
    token = tg_config.get("bot_token", "")
    api_key = config.get("api_key", "")
    storage = get_subscriber_store()

    if not token:
        logger.error("Telegram bot_token이 설정되지 않았습니다.")
        return 0

    result = telegram_request(token, "getUpdates", timeout=5)
    if not result:
        logger.info("대기 중인 요청 없음")
        return 0

    processed = 0
    offset = 0
    for update in result:
        offset = update["update_id"] + 1
        if "callback_query" in update:
            handle_callback(token, api_key, update["callback_query"])
            processed += 1
        elif "message" in update:
            handle_message(token, api_key, update["message"], storage=storage)
            processed += 1

    # offset 업데이트하여 처리된 메시지 제거
    if offset:
        telegram_request(token, "getUpdates", offset=offset, timeout=0)

    logger.info(f"{processed}건 처리 완료")
    return processed


def run_bot(config: dict) -> None:
    """봇을 실행합니다 (long polling)."""
    tg_config = config.get("notification", {}).get("telegram", {})
    token = tg_config.get("bot_token", "")
    api_key = config.get("api_key", "")
    db_path = config.get("db_path", "bid_history.db")
    storage = BidStorage(db_path=db_path)

    if not token:
        logger.error("Telegram bot_token이 설정되지 않았습니다.")
        sys.exit(1)

    # 기존 업데이트 무시
    telegram_request(token, "getUpdates", offset=-1, timeout=0)

    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logger.info("봇을 종료합니다.")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Telegram 봇 시작 (Ctrl+C로 종료)")
    offset = 0

    while running:
        try:
            result = telegram_request(token, "getUpdates",
                                      offset=offset, timeout=30)
            if not result:
                time.sleep(2)
                continue

            for update in result:
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    handle_callback(token, api_key, update["callback_query"])
                elif "message" in update:
                    handle_message(token, api_key, update["message"], storage=storage)

        except Exception as e:
            logger.error(f"봇 오류: {e}")
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="나라장터 Telegram 대화형 봇")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--once", action="store_true",
                        help="대기 중인 요청만 처리하고 종료 (GitHub Actions 용)")
    args = parser.parse_args()

    config_path = args.config
    if not Path(config_path).is_absolute():
        config_path = str(Path(__file__).parent / config_path)

    config = load_config(config_path)

    if args.once:
        process_pending_updates(config)
    else:
        run_bot(config)


if __name__ == "__main__":
    main()
