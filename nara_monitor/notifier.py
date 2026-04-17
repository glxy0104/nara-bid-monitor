"""알림 모듈.

macOS 데스크톱 알림, Telegram, Slack 웹훅, 이메일을 통해 새 입찰공고를 알려줍니다.
"""

import logging
import smtplib
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

from .api import get_bid_detail_url
from .storage import BidStorage, get_subscriber_store

logger = logging.getLogger(__name__)


def _format_price(value) -> str:
    """가격을 읽기 쉬운 형태로 포맷합니다. (예: 36818182 -> 3,681만원)"""
    if not value:
        return "-"
    try:
        num = int(float(str(value)))
        if num >= 100_000_000:
            return f"{num / 100_000_000:.1f}억원"
        elif num >= 10_000:
            return f"{num / 10_000:,.0f}만원"
        else:
            return f"{num:,}원"
    except (ValueError, TypeError):
        return str(value)


def _format_datetime(bid: dict, date_key: str, time_key: str) -> str:
    """날짜와 시간 필드를 결합합니다."""
    date = bid.get(date_key, "")
    time = bid.get(time_key, "")
    if date and time:
        return f"{date} {time}"
    return date or ""


def format_bid_summary(bid: dict) -> dict[str, str]:
    """입찰공고 정보를 읽기 쉬운 형태로 포맷합니다."""
    return {
        "공고명": bid.get("bidNtceNm", ""),
        "공고번호": f"{bid.get('bidNtceNo', '')}-{bid.get('bidNtceOrd', '')}",
        "공고기관": bid.get("ntceInsttNm", ""),
        "수요기관": bid.get("dmndInsttNm", ""),
        "공고일시": _format_datetime(bid, "bidNtceDate", "bidNtceBgn"),
        "마감일시": _format_datetime(bid, "bidClseDate", "bidClseTm"),
        "추정가격": _format_price(bid.get("presmptPrce", "")),
        "배정예산": _format_price(bid.get("asignBdgtAmt", "")),
        "계약방법": bid.get("cntrctCnclsMthdNm", ""),
        "낙찰방법": bid.get("bidwinrDcsnMthdNm", ""),
        "URL": get_bid_detail_url(bid),
    }


class MacOSNotifier:
    """macOS 데스크톱 알림."""

    def notify(self, bids: list[dict]) -> None:
        if not bids:
            return

        for bid in bids:
            title = "🔔 나라장터 입찰공고"
            bid_name = bid.get("bidNtceNm", "새 입찰공고")
            org = bid.get("ntceInsttNm", "")
            message = f"{bid_name}\n기관: {org}"

            try:
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'display notification "{message}" with title "{title}" sound name "default"',
                    ],
                    check=True,
                    capture_output=True,
                )
                logger.info(f"macOS 알림 전송: {bid_name}")
            except subprocess.CalledProcessError as e:
                logger.error(f"macOS 알림 실패: {e}")


class TelegramNotifier:
    """Telegram Bot 알림 (핸드폰 푸시 알림)."""

    SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, storage, default_chat_id: str = ""):
        self.bot_token = bot_token
        self.storage = storage
        self.default_chat_id = default_chat_id

    def _format_detail_price(self, value) -> str:
        """상세 가격 포맷 (원 단위 포함)."""
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

    def _format_detail_message(self, bid: dict) -> str:
        """공고 상세 정보를 메시지로 포맷합니다."""
        detail_url = get_bid_detail_url(bid)

        # 빈 값이 아닌 항목만 표시하는 헬퍼
        def line(label: str, value: str) -> str:
            if value and value.strip() and value != "-":
                return f"  • {label}: {value}\n"
            return ""

        ntce_dt = _format_datetime(bid, "bidNtceDate", "bidNtceBgn")
        close_dt = _format_datetime(bid, "bidClseDate", "bidClseTm")
        openg_dt = _format_datetime(bid, "opengDate", "opengTm")
        担当 = bid.get("ntceInsttOfclNm", "")
        tel = bid.get("ntceInsttOfclTel", "")
        담당자 = f"{担当} ({tel})" if 担当 and tel else 担当

        lines = "🔔 <b>나라장터 입찰공고</b>\n\n"
        lines += f"📌 <b>{bid.get('bidNtceNm', '')}</b>\n\n"

        # 기본 정보
        section = ""
        section += line("공고번호", f"{bid.get('bidNtceNo', '')}-{bid.get('bidNtceOrd', '')}")
        section += line("공고상태", bid.get("bidNtceSttusNm", ""))
        section += line("업무구분", bid.get("bsnsDivNm", ""))
        if section:
            lines += f"<b>▸ 기본 정보</b>\n{section}\n"

        # 기관 정보
        section = ""
        section += line("공고기관", bid.get("ntceInsttNm", ""))
        section += line("수요기관", bid.get("dmndInsttNm", ""))
        section += line("담당자", 담당자)
        if section:
            lines += f"<b>▸ 기관 정보</b>\n{section}\n"

        # 금액 정보
        section = ""
        section += line("배정예산", self._format_detail_price(bid.get("asignBdgtAmt", "")))
        section += line("추정가격", self._format_detail_price(bid.get("presmptPrce", "")))
        if section:
            lines += f"<b>▸ 금액 정보</b>\n{section}\n"

        # 입찰 정보
        section = ""
        section += line("계약방법", bid.get("cntrctCnclsMthdNm", ""))
        section += line("낙찰방법", bid.get("bidwinrDcsnMthdNm", ""))
        section += line("예가방법", bid.get("rsrvtnPrceDcsnMthdNm", ""))
        if section:
            lines += f"<b>▸ 입찰 정보</b>\n{section}\n"

        # 일정
        section = ""
        section += line("공고일시", ntce_dt)
        section += line("입찰마감", close_dt)
        section += line("개찰일시", openg_dt)
        if section:
            lines += f"<b>▸ 일정</b>\n{section}\n"

        # 첨부 문서
        attachments = bid.get("attachments", [])
        if attachments:
            docs = "\n".join(f'  📎 <a href="{a["url"]}">{a["name"]}</a>' for a in attachments)
            lines += f"<b>▸ 첨부 문서</b>\n{docs}\n\n"

        lines += f'🔗 <a href="{detail_url}">나라장터에서 보기</a>'
        return lines

    def _get_chat_ids(self) -> list[str]:
        """알림을 보낼 모든 구독자 chat_id 목록을 반환합니다."""
        chat_ids = set(self.storage.get_all_subscribers())
        if self.default_chat_id:
            chat_ids.add(self.default_chat_id)
        return list(chat_ids)

    def notify(self, bids: list[dict]) -> None:
        if not bids:
            return

        chat_ids = self._get_chat_ids()
        if not chat_ids:
            logger.warning("Telegram 구독자가 없습니다.")
            return

        for bid in bids:
            text = self._format_detail_message(bid)
            detail_url = get_bid_detail_url(bid)

            for chat_id in chat_ids:
                url = self.SEND_URL.format(token=self.bot_token)
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": {
                        "inline_keyboard": [[
                            {
                                "text": "🔗 나라장터에서 보기",
                                "url": detail_url,
                            },
                        ]]
                    },
                }

                try:
                    resp = requests.post(url, json=payload, timeout=10)
                    resp.raise_for_status()
                    logger.info(f"Telegram 알림 전송 ({chat_id}): {bid.get('bidNtceNm', '')}")
                except requests.RequestException as e:
                    logger.error(f"Telegram 알림 실패 ({chat_id}): {e}")


class SlackNotifier:
    """Slack 웹훅 알림."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def notify(self, bids: list[dict]) -> None:
        if not bids:
            return

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🔔 나라장터 새 입찰공고 {len(bids)}건",
                },
            }
        ]

        for bid in bids:
            info = format_bid_summary(bid)
            text = (
                f"*{info['공고명']}*\n"
                f"• 공고번호: {info['공고번호']}\n"
                f"• 공고기관: {info['공고기관']}\n"
                f"• 수요기관: {info['수요기관']}\n"
                f"• 공고일시: {info['공고일시']}\n"
                f"• 마감일시: {info['마감일시']}\n"
                f"• 추정가격: {info['추정가격']}\n"
                f"• <{info['URL']}|상세보기>"
            )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
            blocks.append({"type": "divider"})

        payload = {"blocks": blocks}

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Slack 알림 전송 완료: {len(bids)}건")
        except requests.RequestException as e:
            logger.error(f"Slack 알림 실패: {e}")


class EmailNotifier:
    """이메일 알림."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        sender: str,
        password: str,
        recipients: list[str],
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipients = recipients

    def notify(self, bids: list[dict]) -> None:
        if not bids:
            return

        subject = f"[나라장터] 영상 제작 관련 입찰공고 {len(bids)}건"
        html_body = self._build_html(bids)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            logger.info(f"이메일 알림 전송 완료: {len(bids)}건")
        except smtplib.SMTPException as e:
            logger.error(f"이메일 알림 실패: {e}")

    def _build_html(self, bids: list[dict]) -> str:
        rows = ""
        for bid in bids:
            info = format_bid_summary(bid)
            rows += f"""
            <tr>
                <td style="padding:8px; border:1px solid #ddd;">
                    <a href="{info['URL']}">{info['공고명']}</a>
                </td>
                <td style="padding:8px; border:1px solid #ddd;">{info['공고번호']}</td>
                <td style="padding:8px; border:1px solid #ddd;">{info['공고기관']}</td>
                <td style="padding:8px; border:1px solid #ddd;">{info['마감일시']}</td>
                <td style="padding:8px; border:1px solid #ddd;">{info['추정가격']}</td>
            </tr>"""

        return f"""
        <html>
        <body>
            <h2>🔔 나라장터 입찰공고 알림 ({len(bids)}건)</h2>
            <table style="border-collapse:collapse; width:100%;">
                <tr style="background:#f2f2f2;">
                    <th style="padding:8px; border:1px solid #ddd;">공고명</th>
                    <th style="padding:8px; border:1px solid #ddd;">공고번호</th>
                    <th style="padding:8px; border:1px solid #ddd;">공고기관</th>
                    <th style="padding:8px; border:1px solid #ddd;">마감일시</th>
                    <th style="padding:8px; border:1px solid #ddd;">추정가격</th>
                </tr>
                {rows}
            </table>
        </body>
        </html>"""


class ConsoleNotifier:
    """콘솔 출력 알림 (항상 활성)."""

    def notify(self, bids: list[dict]) -> None:
        if not bids:
            print("\n✅ 새로운 입찰공고가 없습니다.")
            return

        print(f"\n{'='*70}")
        print(f"🔔 나라장터 새 입찰공고 {len(bids)}건 발견!")
        print(f"{'='*70}")

        for i, bid in enumerate(bids, 1):
            info = format_bid_summary(bid)
            print(f"\n[{i}] {info['공고명']}")
            print(f"    공고번호: {info['공고번호']}")
            print(f"    공고기관: {info['공고기관']}")
            print(f"    수요기관: {info['수요기관']}")
            print(f"    공고일시: {info['공고일시']}")
            print(f"    마감일시: {info['마감일시']}")
            print(f"    추정가격: {info['추정가격']}")
            print(f"    URL: {info['URL']}")

        print(f"\n{'='*70}\n")


def create_notifiers(config: dict[str, Any]) -> list:
    """설정에 따라 알림 객체들을 생성합니다."""
    notifiers = [ConsoleNotifier()]  # 콘솔은 항상 활성

    notif_config = config.get("notification", {})

    # macOS 알림
    macos_config = notif_config.get("macos", {})
    if macos_config.get("enabled", False):
        notifiers.append(MacOSNotifier())

    # Telegram 알림
    telegram_config = notif_config.get("telegram", {})
    if telegram_config.get("enabled", False):
        bot_token = telegram_config.get("bot_token", "")
        chat_id = telegram_config.get("chat_id", "")
        if bot_token and "YOUR" not in bot_token:
            storage = get_subscriber_store()
            notifiers.append(TelegramNotifier(bot_token, storage, default_chat_id=chat_id))
        else:
            logger.warning("Telegram 설정이 완료되지 않았습니다.")

    # Slack 알림
    slack_config = notif_config.get("slack", {})
    if slack_config.get("enabled", False):
        webhook_url = slack_config.get("webhook_url", "")
        if webhook_url and "YOUR" not in webhook_url:
            notifiers.append(SlackNotifier(webhook_url))
        else:
            logger.warning("Slack 웹훅 URL이 설정되지 않았습니다.")

    # 이메일 알림
    email_config = notif_config.get("email", {})
    if email_config.get("enabled", False):
        try:
            notifiers.append(
                EmailNotifier(
                    smtp_server=email_config["smtp_server"],
                    smtp_port=email_config["smtp_port"],
                    sender=email_config["sender"],
                    password=email_config["password"],
                    recipients=email_config["recipients"],
                )
            )
        except KeyError as e:
            logger.warning(f"이메일 설정 누락: {e}")

    return notifiers


def send_notifications(notifiers: list, bids: list[dict]) -> None:
    """모든 알림 채널로 알림을 전송합니다."""
    for notifier in notifiers:
        try:
            notifier.notify(bids)
        except Exception as e:
            logger.error(f"{type(notifier).__name__} 알림 전송 중 오류: {e}")
