# 나라장터 입찰공고 모니터링

나라장터(g2b.go.kr)에서 **영상 제작** 관련 입찰공고가 등록되면 자동으로 알림을 보내주는 프로그램입니다.

## 주요 기능

- 나라장터 입찰공고 API를 통해 실시간 공고 조회
- 키워드 기반 필터링 (영상 제작, 홍보영상, 영상 촬영 등)
- 중복 알림 방지 (SQLite로 이력 관리)
- 다양한 알림 채널 지원:
  - macOS 데스크톱 알림
  - Slack 웹훅
  - 이메일 (SMTP)
  - 콘솔 출력
- 1회 실행 (cron 연동) 또는 데몬 모드 지원

## 사전 준비

### 1. 공공데이터포털 API 키 발급

1. [공공데이터포털](https://www.data.go.kr) 회원가입 및 로그인
2. [조달청_나라장터 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do) 페이지에서 **활용신청**
3. 마이페이지에서 **인증키(ServiceKey)** 확인

### 2. Python 환경 설정

```bash
# Python 3.10 이상 필요
python3 --version

# 프로젝트 디렉토리 이동
cd ~/nara-bid-monitor

# 가상환경 생성 (권장)
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

## 설정

`config.yaml` 파일을 편집합니다:

```yaml
# 필수: 공공데이터포털에서 발급받은 API 키
api_key: "발급받은_API_키를_여기에_입력"

# 검색 키워드 (필요에 따라 수정/추가)
keywords:
  - "영상 제작"
  - "영상제작"
  - "홍보영상"
  - "영상 촬영"
```

### 알림 설정

**macOS 데스크톱 알림** (기본 활성):
```yaml
notification:
  macos:
    enabled: true
```

**Slack 알림**:
```yaml
notification:
  slack:
    enabled: true
    webhook_url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

**이메일 알림** (Gmail 예시):
```yaml
notification:
  email:
    enabled: true
    smtp_server: "smtp.gmail.com"
    smtp_port: 587
    sender: "your-email@gmail.com"
    password: "앱 비밀번호"  # Gmail의 경우 앱 비밀번호 사용
    recipients:
      - "recipient@example.com"
```

## 실행

### 1회 실행
```bash
python run.py
```

### 데몬 모드 (백그라운드 지속 실행)
```bash
# 포그라운드 실행
python run.py --daemon

# 백그라운드 실행
nohup python run.py --daemon > monitor.log 2>&1 &
```

### 상세 로그 출력
```bash
python run.py -v
```

### 조회 기간 지정
```bash
# 최근 48시간 내 공고 조회
python run.py --hours 48
```

## cron 자동 실행 설정

매 30분마다 자동 실행하려면:

```bash
crontab -e
```

다음 줄을 추가합니다:
```
*/30 * * * * cd ~/nara-bid-monitor && ~/nara-bid-monitor/venv/bin/python run.py >> ~/nara-bid-monitor/cron.log 2>&1
```

## 프로젝트 구조

```
nara-bid-monitor/
├── config.yaml              # 사용자 설정 파일
├── run.py                   # 실행 진입점
├── nara_monitor/
│   ├── __init__.py
│   ├── api.py               # 나라장터 API 클라이언트
│   ├── notifier.py          # 알림 모듈 (macOS, Slack, Email)
│   └── storage.py           # SQLite 이력 저장소
├── requirements.txt         # Python 의존성
├── bid_history.db           # 알림 이력 DB (자동 생성)
└── README.md
```

## 문제 해결

- **API 키 오류**: 공공데이터포털에서 키 발급 후 `config.yaml`에 정확히 입력했는지 확인
- **데이터 없음**: API 키가 승인 완료 상태인지 확인 (보통 자동승인)
- **macOS 알림 안 됨**: 시스템 설정 > 알림에서 터미널/Python 알림이 허용되었는지 확인
