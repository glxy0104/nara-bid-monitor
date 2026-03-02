"""입찰공고 이력 저장소.

SQLite를 사용하여 이미 알림을 보낸 입찰공고를 추적하고,
중복 알림을 방지합니다.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


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
