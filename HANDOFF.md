# 나라장터 알리미 — 핸드오프 문서

> 마지막 업데이트: 2026-07-13
> 이 문서는 새 계정/새 담당자가 이 프로젝트를 이어받기 위한 안내서입니다.
> **비밀값(API 키, 봇 토큰)은 이 문서에 없습니다** — 저장소가 공개(public)이기 때문입니다.
> 같은 맥의 같은 사용자 계정이라면 `~/nara-bid-monitor/config.yaml`이 이미 존재합니다(복사 불필요).
> 비밀값은 `/Users/Shared` 같은 공용 폴더에 절대 두지 마세요(모든 로컬 계정이 읽음).

## 1. 프로젝트 개요

나라장터(g2b.go.kr) 입찰공고를 매일 확인해서, 키워드에 맞는 새 공고를 텔레그램으로 알려주는 시스템.

- **키워드 조건**: (`영상` AND `제작`) OR `홍보영상` — 공고명 기준
- **알림 시각**: 매일 오전 9시 KST 예약 (GitHub Actions 특성상 실제로는 9:00~10:30 사이 도착)
- **수신자**: `subscribers.json`의 구독자 전원 + 기본 chat_id
- **실행 위치**: 전부 GitHub Actions (로컬/서버 불필요, 컴퓨터 꺼도 동작)

## 2. 구성 요소

| 파일 | 역할 |
|---|---|
| `run.py` | 메인 모니터링. API 조회 → 키워드 필터 → 신규 판별 → 텔레그램 발송 |
| `bot.py` | 텔레그램 봇 수신 처리. 아무 메시지나 보내면 자동 구독 등록, `/detail 공고번호` 상세조회 |
| `nara_monitor/api.py` | 나라장터 API 클라이언트 + 키워드 필터 + 첨부파일 조회 |
| `nara_monitor/notifier.py` | 텔레그램 메시지 포맷/발송 |
| `nara_monitor/storage.py` | SQLite(중복 알림 방지) + `subscribers.json`(구독자) |
| `subscribers.json` | 구독자 명단 (저장소에 커밋됨, 봇이 자동 갱신) |
| `.github/workflows/monitor.yml` | 매일 0시 UTC(9시 KST) 모니터링 실행 |
| `.github/workflows/bot.yml` | 5분마다 봇 메시지 처리 (구독 등록 등) |
| `config.yaml` | **커밋 안 됨(gitignore)**. 로컬 실행 시에만 필요 |

### 사용하는 API 2개 (동일한 인증키 사용)

1. **공공데이터개방표준서비스** `apis.data.go.kr/1230000/ao/PubDataOpnStdService`
   - 공고 목록 조회 (메인). 파라미터: `bidNtceBgnDt`/`bidNtceEndDt` (기간 최대 약 14일)
2. **입찰공고정보서비스** `apis.data.go.kr/1230000/ad/BidPublicInfoService`
   - 첨부파일(공고문/과업지시서 등) URL 조회용. `ntceSpecDocUrl1~10`, `ntceSpecFileNm1~10` 필드
   - 두 API 모두 공공데이터포털(data.go.kr)에서 활용신청 승인된 상태 (활용기간 ~2028-04-17)

### 비밀값 위치

- **GitHub Actions**: 리포 Settings → Secrets → `NARA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (이미 등록됨, 워크플로우가 사용)
- **로컬 실행용**: `~/nara-bid-monitor/config.yaml` (같은 맥·같은 사용자면 이미 존재. gitignore라 리포에는 안 올라감)
- 텔레그램 봇: `@Naratestbot` (봇 이름 NaraAlarm)

## 3. 새 계정에서 시작하기

> **같은 맥·같은 사용자 계정인 경우**: 리포(`~/nara-bid-monitor`)와 `config.yaml`이 이미 있으므로
> 아래 1)·2) 클론 단계는 건너뛰고, 새 GitHub 계정으로 `gh auth login`만 다시 하면 됩니다.
> (실제로 바꿔야 하는 건 push 권한뿐 — 아래 "push 권한" 참고)

```bash
# 1) GitHub CLI 설치 + 로그인 (새 계정으로)
brew install gh
gh auth login --web --git-protocol https

# 2) (리포가 없을 때만) 클론
git clone https://github.com/glxy0104/nara-bid-monitor.git ~/nara-bid-monitor
cd ~/nara-bid-monitor

# 3) 로컬 실행이 필요할 때만: 가상환경 + config
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# config.yaml이 이미 있으면 그대로 사용. 없을 때만 config.example.yaml을 복사해 값 채우기
[ -f config.yaml ] || cp config.yaml.example config.yaml

# 4) 로컬 테스트 실행 (텔레그램으로 실제 발송되니 주의)
python run.py --hours 24
```

**push 권한**: 리포 소유자는 `glxy0104` 계정. 팀 계정으로 push하려면
`glxy0104` 계정으로 GitHub → Settings → Collaborators에서 팀 계정을 초대해야 함.
(또는 리포를 팀 계정/조직으로 Transfer)

## 4. 운영 런북

```bash
# 워크플로우 상태 확인 (disabled_inactivity로 꺼져있으면 안 됨!)
gh workflow list --repo glxy0104/nara-bid-monitor --all

# 최근 실행 로그 확인
gh run list --repo glxy0104/nara-bid-monitor --limit 5
gh run view <RUN_ID> --repo glxy0104/nara-bid-monitor --log | grep -E "매칭|알림 전송|ERROR"

# 모니터링 수동 실행 (⚠️ 주의: 실행하면 캐시가 갱신됨. 아래 '과거 사건 2' 참고)
gh workflow run monitor.yml --repo glxy0104/nara-bid-monitor

# 구독자 확인
cat subscribers.json

# 구독자 수동 추가: 대상자가 봇(@Naratestbot)에 아무 메시지나 보내면
# 5분 내 bot.yml이 자동 등록 + subscribers.json 자동 커밋됨.
# 직접 추가하려면 subscribers.json 편집 후 커밋/푸시해도 됨.
```

### 키워드 변경 방법

`.github/workflows/monitor.yml`의 `NARA_KEYWORD_GROUPS` 수정:
```yaml
NARA_KEYWORD_GROUPS: "영상+제작|홍보영상"   # +는 AND, |는 OR
```

## 5. 과거 사건과 배운 것 (중요)

1. **60일 무활동 → 워크플로우 자동 정지** (2026-06-17 발생, 7-13 복구)
   - GitHub는 커밋이 60일 없으면 스케줄 워크플로우를 자동 비활성화함 (`disabled_inactivity`)
   - **대책 적용됨**: monitor.yml이 매일 `.last-run` 파일을 커밋(keepalive)
   - 그래도 멈추면: `gh workflow enable <ID> --repo glxy0104/nara-bid-monitor`

2. **중복 알림 사건** (2026-04-17)
   - 원인: 캐시 키가 run_id 기반이라, 수동 실행이 빈 DB를 캐시에 저장 → 다음 정기 실행이 그걸 복원
   - 수정됨: 고정 캐시 키 `bid-history-db` 사용. 단, GitHub 캐시는 **7일간 미사용 시 삭제**되므로
     장기 중단 후 재개하면 최근 24시간 공고가 한 번 더 올 수 있음 (치명적이지 않음)

3. **구독자 저장 403 사건**: GitHub Repository Variable은 기본 GITHUB_TOKEN으로 읽기/쓰기 불가
   → `subscribers.json` 파일 커밋 방식으로 전환 (현재 방식)

4. **입찰마감일이 빈 공고 주의**: 제안서 방식 공고 등은 API가 `bidClseDate`를 빈 값으로 반환.
   마감 여부는 `opengDate`(개찰일)로도 교차 확인해야 함

5. **API 특성**:
   - 조회 기간 최대 약 14일 (넘으면 0건 반환됨)
   - Python 3.9(맥 기본)에서는 `X | None` 타입 문법 불가 → `Optional[X]` 사용 (Actions는 3.12)
   - 텔레그램 chat_id는 숫자만 유효 (이름/유저명 불가)

6. **저장소가 PUBLIC**: config.yaml은 gitignore 되어 있으니 **절대 커밋 금지**.
   비공개 전환은 가능하지만 Actions 무료 사용량(월 2,000분) 제한이 생겨
   5분 주기 bot.yml이 초과할 수 있음 → 공개 유지가 현재 전제

## 6. 현재 상태 (2026-07-13 기준)

- 구독자 3명: 운영자(8631009063), 이세용(8719189633), Aaron Jeong/팀장(5105249792)
- 워크플로우 2개 모두 active, keepalive 적용됨
- 첨부파일 조회 기능 정상 작동 확인됨
- 6/17~7/13 중단 기간의 놓친 공고 71건은 요약본으로 일괄 발송 완료 (정정 1회 포함)
