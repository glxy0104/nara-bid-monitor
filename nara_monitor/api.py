"""나라장터 입찰공고정보서비스 API 클라이언트.

공공데이터포털(data.go.kr)의 조달청 나라장터 입찰공고정보서비스 API를 호출하여
입찰공고 목록을 조회합니다.

API 문서: https://www.data.go.kr/data/15129394/openapi.do
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# 업무별 API 엔드포인트 매핑
BID_TYPE_ENDPOINTS = {
    "services": "getDataSetOpnStdBidPblancInfo",      # 용역
    "goods": "getDataSetOpnStdBidPblancInfo",          # 물품
    "construction": "getDataSetOpnStdBidPblancInfo",   # 공사
    "foreign": "getDataSetOpnStdBidPblancInfo",        # 외자
}

BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
MAX_ROWS_PER_PAGE = 999

# 첨부파일 조회용 구 API (업무별 엔드포인트)
BID_DETAIL_BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
BID_DETAIL_ENDPOINTS = {
    "services": "getBidPblancListInfoServc",      # 용역
    "goods": "getBidPblancListInfoThng",           # 물품
    "construction": "getBidPblancListInfoCnstwk",  # 공사
    "foreign": "getBidPblancListInfoFrgcpt",       # 외자
}


class NaraJangterAPI:
    """나라장터 입찰공고 API 클라이언트."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def fetch_bids(
        self,
        bid_type: str = "services",
        hours: int = 24,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """지정 기간 내 입찰공고 목록을 조회합니다.

        Args:
            bid_type: 업무 구분 (services, goods, construction, foreign)
            hours: 현재 시점 기준 조회할 시간 범위 (start_dt/end_dt 미지정 시 사용)
            start_dt: 조회 시작 일시
            end_dt: 조회 종료 일시

        Returns:
            입찰공고 목록 (dict 리스트)
        """
        endpoint = BID_TYPE_ENDPOINTS.get(bid_type)
        if not endpoint:
            logger.error(f"지원하지 않는 업무 구분: {bid_type}")
            return []

        if end_dt is None:
            end_dt = datetime.now()
        if start_dt is None:
            start_dt = end_dt - timedelta(hours=hours)

        all_items = []
        page = 1

        while True:
            items, total_count = self._fetch_page(
                endpoint=endpoint,
                start_dt=start_dt,
                end_dt=end_dt,
                page=page,
            )

            if items is None:
                break

            all_items.extend(items)
            logger.info(
                f"페이지 {page} 조회 완료: {len(items)}건 (누적 {len(all_items)}/{total_count}건)"
            )

            if len(all_items) >= total_count:
                break
            page += 1

        return all_items

    def fetch_all_types(self, hours: int = 24) -> list[dict[str, Any]]:
        """모든 업무 구분의 입찰공고를 조회합니다."""
        all_items = []
        for bid_type in BID_TYPE_ENDPOINTS:
            logger.info(f"[{bid_type}] 입찰공고 조회 중...")
            items = self.fetch_bids(bid_type=bid_type, hours=hours)
            all_items.extend(items)
        return all_items

    def fetch_attachments(
        self,
        bid_ntce_no: str,
        bid_type: str = "services",
        hours: int = 24,
    ) -> list[dict[str, str]]:
        """구 API(BidPublicInfoService)에서 첨부 문서 정보를 조회합니다.

        Returns:
            [{"name": 파일명, "url": 다운로드URL}, ...] 형식의 리스트
        """
        endpoint = BID_DETAIL_ENDPOINTS.get(bid_type, "getBidPblancListInfoServc")
        url = f"{BID_DETAIL_BASE_URL}/{endpoint}"

        now = datetime.now()
        start_dt = (now - timedelta(hours=hours)).strftime("%Y%m%d%H%M")
        end_dt = now.strftime("%Y%m%d%H%M")

        params = {
            "ServiceKey": self.api_key,
            "pageNo": 1,
            "numOfRows": 10,
            "inqryDiv": 2,
            "bidNtceNo": bid_ntce_no,
            "inqryBgnDt": start_dt,
            "inqryEndDt": end_dt,
            "type": "json",
        }

        try:
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"첨부파일 조회 실패 ({bid_ntce_no}): HTTP {resp.status_code}")
                return []
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"첨부파일 조회 실패 ({bid_ntce_no}): {e}")
            return []

        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]
        if not items:
            return []

        # 첫 번째 아이템의 첨부 정보 추출
        item = items[0]
        attachments = []
        for i in range(1, 11):
            name = item.get(f"ntceSpecFileNm{i}", "")
            file_url = item.get(f"ntceSpecDocUrl{i}", "")
            if name and file_url:
                attachments.append({"name": name, "url": file_url})
        return attachments

    def enrich_with_attachments(
        self,
        bids: list[dict],
        bid_type: str = "services",
        hours: int = 24,
    ) -> None:
        """입찰공고 리스트에 첨부파일 정보를 덧붙입니다 (in-place)."""
        for bid in bids:
            bid_no = bid.get("bidNtceNo", "")
            if bid_no:
                bid["attachments"] = self.fetch_attachments(bid_no, bid_type=bid_type, hours=hours)

    def _fetch_page(
        self,
        endpoint: str,
        start_dt: datetime,
        end_dt: datetime,
        page: int = 1,
    ) -> Tuple[Optional[list[dict]], int]:
        """API에서 한 페이지의 입찰공고를 조회합니다."""
        params = {
            "ServiceKey": self.api_key,
            "pageNo": page,
            "numOfRows": MAX_ROWS_PER_PAGE,
            "bidNtceBgnDt": start_dt.strftime("%Y%m%d%H%M"),
            "bidNtceEndDt": end_dt.strftime("%Y%m%d%H%M"),
            "type": "json",
        }

        url = f"{BASE_URL}/{endpoint}"

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"API 요청 실패: {e}")
            return None, 0

        try:
            data = resp.json()
        except ValueError:
            logger.error(f"JSON 파싱 실패: {resp.text[:200]}")
            return None, 0

        # 응답 구조 파싱
        response = data.get("response", {})
        header = response.get("header", {})
        result_code = header.get("resultCode", "")

        if result_code != "00":
            result_msg = header.get("resultMsg", "알 수 없는 오류")
            logger.error(f"API 오류 (코드: {result_code}): {result_msg}")
            return None, 0

        body = response.get("body", {})
        total_count = int(body.get("totalCount", 0))

        if total_count == 0:
            return [], 0

        items = body.get("items", [])

        # items가 리스트가 아닌 경우 처리
        if isinstance(items, dict):
            items = [items]

        return items, total_count


def filter_bids_by_keywords(
    bids: list[dict],
    keywords: list[str],
    exclude_keywords: Optional[list[str]] = None,
    keyword_groups: Optional[list[list[str]]] = None,
) -> list[dict]:
    """입찰공고 목록에서 키워드로 필터링합니다.

    Args:
        bids: 입찰공고 목록
        keywords: 포함 키워드 (모든 키워드가 포함되어야 매칭 - AND 조건, keyword_groups 미사용 시)
        exclude_keywords: 제외 키워드 (하나라도 포함되면 제외)
        keyword_groups: 키워드 그룹 목록 (OR 조건). 각 그룹 내부는 AND 조건.
                        예: [["영상", "제작"], ["홍보영상"]] → "영상"AND"제작" OR "홍보영상"

    Returns:
        매칭된 입찰공고 목록
    """
    # keyword_groups가 있으면 우선 사용, 없으면 기존 keywords를 단일 그룹으로
    groups = keyword_groups if keyword_groups else ([keywords] if keywords else [])
    if not groups or all(len(g) == 0 for g in groups):
        return bids

    exclude_keywords = exclude_keywords or []
    matched = []

    for bid in bids:
        bid_name = bid.get("bidNtceNm", "")
        if not bid_name:
            continue

        bid_name_lower = bid_name.lower()

        # 제외 키워드 확인
        if any(kw.lower() in bid_name_lower for kw in exclude_keywords):
            continue

        # 키워드 그룹 확인 (OR 조건: 하나의 그룹이라도 전부 매칭되면 OK)
        for group in groups:
            if group and all(kw.lower() in bid_name_lower for kw in group):
                matched.append(bid)
                break

    return matched


def get_bid_detail_url(bid: dict) -> str:
    """입찰공고 상세 URL을 생성합니다."""
    # API 응답에 포함된 실제 URL 우선 사용
    for key in ("bidNtceDtlUrl", "bidNtceUrl"):
        url = bid.get(key, "")
        if url:
            return url

    bid_no = bid.get("bidNtceNo", "")
    bid_ord = bid.get("bidNtceOrd", "")
    if bid_no and bid_ord:
        return f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={bid_no}&bidPbancOrd={bid_ord}"

    return "https://www.g2b.go.kr"
