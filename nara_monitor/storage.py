"""입찰공고 이력 저장소.

SQLite를 사용하여 이미 알림을 보낸 입찰공고를 추적하고,
중복 알림을 방지합니다.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class FileSubscriberStore:
    """subscribers.json 파일로 구독자를 영구 저장합니다.

    GitHub Actions에서도 파일을 커밋하여 영구 보존합니다.
    """

    def __init__(self, file_path: str = "subscribers.json"):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            self._save([])

    def _load(self) -> list[dict]:
        """파일에서 구독자 목록을 불러옵니다."""
        try:
            if self.file_path.exists():
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"구독자 목록 로드 실패: {e}")
            return []

    def _save(self, subscribers: list[dict]) -> None:
        """구독자 목록을 파일에 저장합니다."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(subscribers, f, ensure_ascii=False, indent=2)
            logger.info(f"구독자 목록 저장 완료 ({len(subscribers)}명)")
        except Exception as e:
            logger.error(f"구독자 목록 저장 실패: {e}")

    def add_subscriber(self, chat_id: str, username: str = "") -> None:
        """구독자를 등록합니다."""
        subscribers = self._load()
        if any(s["chat_id"] == chat_id for s in subscribers):
            return
        subscribers.append({
            "chat_id": chat_id,
            "username": username,
            "subscribed_at": datetime.now().isoformat(),
        })
        self._save(subscribers)
        logger.info(f"구독자 등록 완료: {chat_id} (@{username})")

    def get_all_subscribers(self) -> list[str]:
        """모든 구독자의 chat_id 목록을 반환합니다."""
        subscribers = self._load()
        return [s["chat_id"] for s in subscribers]


def get_subscriber_store():
    """구독자 저장소를 반환합니다."""
    # 스크립트 위치 기준으로 subscribers.json 경로 결정
    base_dir = Path(__file__).parent.parent
    file_path = base_dir / "subscribers.json"
    return FileSubscriberStore(file_path=str(file_path))


class BidStorage:
    """입찰공고 이력을 SQLite에 저장합니다."""

    def __init__(self, db_path: str = "bid_history.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """데이터베이스 테이블을 초기화합니다."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notified_bids (
                    bid_ntce_no TEXT NOT NULL,
                    bid_ntce_ord TEXT NOT NULL,
                    bid_ntce_nm TEXT,
                    ntce_instt_nm TEXT,
                    bid_ntce_dt TEXT,
                    bid_clse_dt TEXT,
                    presmpt_prce TEXT,
                    notified_at TEXT NOT NULL,
                    PRIMARY KEY (bid_ntce_no, bid_ntce_ord)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id TEXT PRIMARY KEY,
                    username TEXT,
                    subscribed_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        """데이터베이스에 연결합니다."""
        return sqlite3.connect(str(self.db_path))

    def is_notified(self, bid_ntce_no: str, bid_ntce_ord: str) -> bool:
        """해당 입찰공고에 대해 이미 알림을 보냈는지 확인합니다."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM notified_bids WHERE bid_ntce_no = ? AND bid_ntce_ord = ?",
                (bid_ntce_no, bid_ntce_ord),
            )
            return cursor.fetchone() is not None

    def mark_notified(self, bid: dict) -> None:
        """입찰공고를 알림 완료로 기록합니다."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO notified_bids
                    (bid_ntce_no, bid_ntce_ord, bid_ntce_nm, ntce_instt_nm,
                     bid_ntce_dt, bid_clse_dt, presmpt_prce, notified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid.get("bidNtceNo", ""),
                    bid.get("bidNtceOrd", ""),
                    bid.get("bidNtceNm", ""),
                    bid.get("ntceInsttNm", ""),
                    bid.get("bidNtceDt", ""),
                    bid.get("bidClseDt", ""),
                    str(bid.get("presmptPrce", "")),
                    datetime.now().isoformat(),
                ),
            )

    def mark_many_notified(self, bids: list[dict]) -> None:
        """여러 입찰공고를 알림 완료로 기록합니다."""
        for bid in bids:
            self.mark_notified(bid)

    def filter_new_bids(self, bids: list[dict]) -> list[dict]:
        """아직 알림을 보내지 않은 새 입찰공고만 필터링합니다."""
        new_bids = []
        for bid in bids:
            bid_no = bid.get("bidNtceNo", "")
            bid_ord = bid.get("bidNtceOrd", "")
            if bid_no and not self.is_notified(bid_no, bid_ord):
                new_bids.append(bid)
        return new_bids

    def get_recent_count(self, days: int = 7) -> int:
        """최근 N일간 알림한 건수를 조회합니다."""
        cutoff = datetime.now().replace(hour=0, minute=0, second=0)
        cutoff = cutoff.replace(day=cutoff.day - min(days, cutoff.day - 1))

        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM notified_bids WHERE notified_at >= ?",
                (cutoff.isoformat(),),
            )
            return cursor.fetchone()[0]

    def add_subscriber(self, chat_id: str, username: str = "") -> None:
        """구독자를 등록합니다."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO subscribers (chat_id, username, subscribed_at) VALUES (?, ?, ?)",
                (str(chat_id), username, datetime.now().isoformat()),
            )

    def get_all_subscribers(self) -> list[str]:
        """모든 구독자의 chat_id 목록을 반환합니다."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT chat_id FROM subscribers")
            return [row[0] for row in cursor.fetchall()]

    def cleanup_old(self, days: int = 90) -> int:
        """오래된 이력을 삭제합니다."""
        from datetime import timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM notified_bids WHERE notified_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"{deleted}건의 오래된 이력을 삭제했습니다.")
            return deleted
