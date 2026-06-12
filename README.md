# 월드컵 토토 - 경기 결과 자동수집기

월드컵 경기 스코어를 무료 축구 API에서 가져와 토토 사이트의 Supabase(`matches` 테이블)에
자동 기록한다. **공개(public) 저장소** — GitHub Actions 무료 무제한을 쓰기 위함이며,
민감한 값(키)은 코드가 아니라 **저장소 Secrets**에 들어간다.

```
[이 저장소] Actions 5분마다 ──기록──▶ [Supabase matches] ──읽기──▶ [토토 사이트(private)]
 fetch_scores.py                       home_score/finished        순위표가 알아서 갱신
```

토토 본체 코드는 들어있지 않다. 여기 있는 건 "API에서 점수 받아 DB에 적는" 스크립트 하나뿐.

## 한 번만 하는 셋업

### 1) football-data.org 무료 토큰 발급
- https://www.football-data.org/client/register 가입 → 메일/대시보드로 API 토큰 수령 (무료, 월드컵 포함, 10회/분)

### 2) 이 폴더를 공개 저장소로 올리기
```
cd D:\코드\월드컵토토스코어
git init
git add .
git commit -m "월드컵 결과 자동수집기"
gh repo create worldcup-toto-scores --public --source=. --push
```
(`.env`는 .gitignore라 안 올라감 — 키가 코드에 섞일 일 없음)

### 3) 저장소 Secrets 3개 등록
GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret** 로 3개:

| 이름 | 값 |
|---|---|
| `SUPABASE_URL` | `https://<프로젝트>.supabase.co` (토토 config.js의 그 주소) |
| `SUPABASE_SERVICE_KEY` | Supabase 대시보드 > Settings > API > **service_role** 키 |
| `FOOTBALL_DATA_TOKEN` | 1)에서 받은 토큰 |

> Secrets는 암호화 저장되고 로그·포크·외부 PR에 노출되지 않는다. 공개 저장소여도 안전.
> 단 `service_role` 키는 DB 마스터키이니, 이 저장소의 협업자(쓰기권한)는 본인만 둘 것.

### 4) 끝. 5분마다 자동 실행
- 즉시 한 번 돌려보려면: 저장소 **Actions 탭 → "월드컵 결과 수집" → Run workflow**

## 로컬에서 먼저 점검(권장)
실제 쓰기 전에 매칭이 맞는지 확인:
```
copy .env.example .env      # 그리고 .env에 실제 키 3개 채우기
set DRY_RUN=1 && py fetch_scores.py
```
- "매칭 N건"이 우리 경기와 맞는지, "매핑 안 된 API 팀명"이 없는지 확인.
- 팀명이 안 잡히면 `fetch_scores.py`의 `TEAM_ALIASES`에 그 영문명을 추가.
- 확인되면 `DRY_RUN` 빼고 `py fetch_scores.py` → 실제 기록.

## 다음 대회로 재사용
`fetch_scores.py` 상단의 대회코드만 바꾸면 됨:
- `FD_COMPETITION` : football-data 대회코드 (월드컵=WC)
- `TOTO_COMPETITION` : 우리 matches.competition 값 (worldcup 등)
- `TEAM_ALIASES` : 출전팀 한글↔영문 표 갱신

## 동작 규칙
- 우리 `matches`에서 `finished=false`인 월드컵 경기만 대상.
- API 스코어가 있으면 기록(진행중이면 `finished=false`, 종료면 `true`).
- 홈/원정 순서가 API와 반대면 스코어를 뒤집어 맞춤.
- 바뀐 값이 없으면 쓰지 않음(불필요한 쓰기 방지).
- 커스텀 카테고리(야구·결승 등)는 건드리지 않음 → 관리자 수동입력 그대로.
