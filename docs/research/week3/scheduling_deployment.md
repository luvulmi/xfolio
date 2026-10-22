# R7. 예약 실행·배포 조사

- 확인일: 2026-10-22, Asia/Seoul
- 범위: 공식 문서·가격 확인 및 Windows 로컬 실행안 후속 조사. 계정 생성·작업 등록·배포·결제·예약 실행 지연 측정은 하지 않았다.
- 기준: [조사계획](../../../tasks/week3_research_plan.md), [운영 추천안](../../market_briefing_operating_plan.md)
- 관련: [저장·관리자 사이트](storage_admin.md)

## 조사 결론

후속 결정: 사용자가 [약 2.1만 원 초기 구성](../../minimum_cost_configuration.md)을 선택했다. 현재 실행 기준은 기존 Windows PC·작업 스케줄러이며 아래 VM·systemd 추천은 비용 절감 결정 이전 비교 이력이다. 실제 Windows 작업 등록·실행 시험은 미완료다.

후속 조사에서는 **현재 Windows PC + 작업 스케줄러 + SQLite + 로컬 Streamlit**을 초기 구성으로 삼는다. PC가 켜져 있고 인터넷을 사용할 수 있을 때 동작하며 새 VM 구독료는 없다. 상시 운영이 필요해질 때 아래 Linux VM 비교를 사용한다. Windows의 예약 지연과 절전 복귀는 실기 시험이 필요하다. GitHub Actions는 시험·정적 검사에 쓰고, 운영 게시 예약의 우선 후보에서는 내린다. Actions 공식 문서는 예약 실행 지연과 일부 작업 누락 가능성을 명시한다. 최단 5분 예약 지원이 5분 안에 실행을 보장한다는 뜻은 아니다. [GitHub 예약 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule), [실행 문제 해결](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

아래 비용은 인프라만의 가격이며 뉴스·지수·AI·X 사용료가 별도다. 단일 서버 역시 장애가 없어지는 구성이 아니며 실제 목표 충족 여부는 예약 시험으로 확인해야 한다.

## 후보 비교

| 후보 | 예약·저장·화면 | 공식 가격 입력 | 판단 |
| --- | --- | --- | --- |
| AWS Lightsail Linux + SQLite | 지속 서버 한 곳에 Streamlit·작업·DB 배치. OS timer와 로컬 트랜잭션 사용 | IPv4 포함 1GB RAM/40GB SSD $7/월, 2GB/60GB $12/월. 스냅샷 $0.05/GB·월 | 우선 검증 후보. 1GB에서 실제 메모리 시험 후 선택. OS 업데이트·HTTPS·백업은 직접 관리 |
| Hetzner CX23 + SQLite | 같은 단일 서버 구조. 독일/핀란드 비용표 비교 | CX23 €5.49/월(IPv4·VAT 제외), IPv4 €0.50/월 추가. 백업 별도 | 가격 대안. €5.99+백업+세금이 비교 기준. 지역별 재고·계정 승인·현재 주문가 확인 필요 |
| GitHub Actions + 원격 PostgreSQL + 별도 Streamlit 사이트 | 작업은 단발 실행, 사이트·DB는 별도 서비스 | 공개 저장소 표준 runner 무료. 비공개 GitHub Free 월 2,000분·artifact 500MB. 추가 Linux 2-core $0.006/분 | 개발·시연 대안. 예약 지연·서비스 분리·외부 DB 백업 관리로 현재 운영 시각 목표에는 보류 |

가격 근거: [Lightsail](https://aws.amazon.com/lightsail/pricing/), [Hetzner 2026-06 가격 조정](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Hetzner Primary IP](https://docs.hetzner.com/cloud/servers/primary-ips/overview/), [GitHub Actions 과금](https://docs.github.com/en/billing/concepts/product-billing/github-actions). Hetzner 공식 상품 페이지는 조사 시 Cost-Optimized에 현재 제공 불가 표시가 있어 CX23 즉시 주문 가능으로 확정하지 않았다. [상품 페이지](https://www.hetzner.com/cloud/)

## 단일 VM에서의 최소 실행 구성

수집·AI·게시 CLI는 같은 Python 프로젝트를 사용한다. Streamlit과 예약 작업을 별도 OS 서비스로 실행하되 DB와 설정을 공유한다. 타이머를 Streamlit 화면 세션 내부에 두면 사용자가 화면을 닫거나 앱이 재시작될 때 실행이 흔들릴 수 있으므로 OS에서 관리한다.

| 작업 | 추천 실행 방식 | 실행 전 확인 |
| --- | --- | --- |
| 아침 준비 | 07:00 준비 시작, 07:30 정보 기준·07:45 초안 목표 | 직전 완료 미국 거래일·자료 버전·수집 성공 |
| 기업 뉴스 수집 | 해당 운영일 09:00~17:30 30분 간격, 하루 18회 | 미국 거래일·수집 진행 기록·중복·예산 |
| 승인 발행 | 운영 시간 5분 간격 승인 큐 확인, 아침 08:00 발행 처리 | 후보 버전·승인·예약 한도·마감·비용 |
| 백업·정리 | 일일 DB 일관 사본 생성·외부 보관 | 저장 허용 기간·백업 성공·복원 가능 |

위 시간은 서비스 사양이 아닌 기존 운영 추천값이다. 타이머가 실행됐더라도 수집·승인이 늦으면 발행을 생략할 수 있다. UTC 저장과 KST 운영 시간을 명시하고 거래일·서머타임은 애플리케이션의 거래소 달력 검사로 처리한다.

systemd timer는 같은 service가 실행 중이면 중복 인스턴스를 새로 시작하지 않는다. 기본 `AccuracySec`는 1분이므로 아침 목표에 맞춰 명시적으로 조정하고 무작위 지연은 넣지 않는다. `Persistent` 복구 실행을 사용해도 애플리케이션에서 마감·승인 만료를 확인해 지난 게시를 자동 재생하지 않는다. [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)

다른 타이머·수동 CLI 실행까지 막아 주는 것은 아니므로 DB의 고유 발행 키와 상태 점유를 병행한다. 게시 직전 현재 시각을 확인하고 09:00/18:00 이후 새 요청을 차단한다. 서버 재시작 뒤 성공 불명 요청을 재전송하지 않고 대조 대상으로 남긴다. 이는 제품에서 구현해야 할 로직이다.

## GitHub Actions 제약과 비용 예시

공식 문서는 최소 5분 예약, 기본 브랜치 최신 커밋 실행을 지원한다. 확인일 현재 기본 UTC 외 IANA `timezone`도 지정할 수 있다. 과거의 UTC 전용 설명을 그대로 쓰지 않는다. 정시에는 부하로 지연될 수 있으며 일부 대기 작업이 누락될 수도 있다. [예약 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule), [문제 해결](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

일반 `ubuntu-latest` 작업은 매번 새 VM에서 실행되므로 로컬 SQLite를 사이트와 공통 영속 DB로 사용할 수 없다. Artifact·cache를 운영 DB의 잠금·트랜잭션 저장소로 대신하지 않는다. 원격 PostgreSQL과 별도 사이트를 연결해야 한다. [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

비공개 저장소 GitHub Free에 정상 Linux 2-core runner를 사용한다는 **가정 계산**이다. 운영일을 월 22일, 각 job을 과금되는 1분으로 가정했다. 실제 실행·설치 시간, 다른 저장소·CI 사용량과 artifact 비용은 별도다.

- 수집 18회 + 아침 관련 3회만 실행: `21 × 22 = 462분/월`.
- 승인 확인을 07:00~17:55의 5분 간격 132회와 합쳐 하나의 job으로 처리: `132 × 22 = 2,904분/월`.
- 무료 2,000분이 모두 남았어도 후자는 `904 × $0.006 = $5.424/월` 초과분이다.
- 무료 분이 다른 작업으로 이미 소진됐으면 2,904분 전체는 `$17.424/월`이다. job 평균 2분이면 각각 두 배의 분 수가 된다.

[무료량·단가 근거](https://docs.github.com/en/billing/concepts/product-billing/github-actions). 공개 저장소 표준 runner 무료는 가격 비교에 쓸 수 있지만 비공개 자료를 공개하거나 저장소 공개 전환을 추천하는 근거는 아니다. 공개 저장소에서는 장기 비활동 시 예약 비활성화 조건도 확인해야 한다. 실행 자격증명은 Actions Secrets 등으로 전달하되 DB·기사·키를 artifact나 로그에 노출하지 않는다.

## 서버·백업 월 비용 입력

Lightsail의 신규 무료 혜택은 계정별 적용 여부를 확인하지 않았으므로 정상 월 가격으로 계산한다. IPv6 전용 1GB $5도 있지만 외부 API와 운영자 네트워크의 IPv6 호환을 확인하지 않아 기본안에서 제외한다. [Lightsail 가격](https://aws.amazon.com/lightsail/pricing/)

| 시나리오 | 인프라 소계(USD, 세전) | 의미 |
| --- | --- | --- |
| 1GB VM + 과금 스냅샷 평균 10GB 가정 | `$7 + 10 × $0.05 = $7.50/월` | 작은 단일 운영자 앱의 우선 성능 시험안 |
| 2GB VM + 같은 스냅샷 가정 | `$12 + $0.50 = $12.50/월` | 메모리가 부족할 때 상향 비교안 |
| 스냅샷 저장량 평균 40GB로 증가 | `$7 + 40 × $0.05 = $9/월` | 백업이 무료 또는 항상 $0.50이라고 보지 않음 |

10GB는 실제 측정값이 아닌 과금 저장량 예시다. 백업 개수·변경량·보관 기간에 따라 증가한다. 스냅샷과 별도의 외부 DB 사본 저장은 중복 보관 비용도 고려해야 한다. 도메인·초과 전송·외부 백업·세금·환율·결제 수수료는 위 소계에 포함되지 않았다. HTTPS는 무료 인증서를 활용하는 구현 후보지만 도메인 확보·갱신·운영 비용은 따로 확인한다.

Hetzner는 꺼 두어도 서버를 삭제할 때까지 과금한다. 자동 백업은 하루 단위 최대 7개이며 별도 볼륨은 포함하지 않는다. 공식 가격 조정표에 IPv4가 제외돼 있으므로 이를 누락한 €5.49만으로 총비용을 비교하지 않는다. [과금 FAQ](https://docs.hetzner.com/cloud/billing/faq/), [백업·스냅샷](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/)

## 다음 확인과 발표 설명

발표에서는 “GitHub Actions를 처음 검토했지만 예약 지연과 공통 DB 요구를 확인해 단일 VM을 우선 후보로 제안했다”고 설명할 수 있다. 서비스 선택은 총비용표와 최소 배포 시험 뒤 결정한다.

4주차에는 1GB VM에서 Streamlit·수집·OpenAI 요청 대기·DB 백업이 겹칠 때 메모리와 실행 시간을 확인한다. HTTPS/OIDC 로그인, 서버 재시작, 중복 타이머, 마감 직전 승인, DB 복원, 외부 API 통신도 시험한다. 30시간 개발 가능 여부는 아직 실측하지 않았으며 OS 운영 경험이 없으면 설치·인증·백업 시간을 별도 잡아야 한다. 서버 구매·계정 생성·실제 게시 권한은 이번 조사에 포함하지 않았다.

## 후속 조사: 현재 Windows PC의 작업 스케줄러

위 VM 성능 시험은 유료 서버로 이전할 때의 확인 항목이다. 초기 단계는 이미 있는 Windows PC에서 같은 폴더의 DB를 사용하는 CLI와 관리자 사이트를 시험한다. 소프트웨어 구독의 추가 인프라 비용은 0원으로 잡을 수 있지만 PC 전력·인터넷·백업 매체·기존 장비 비용까지 무료라고 가정하지 않는다. PC 종료·업데이트·인터넷 중단 중에는 아침 발행이 생략될 수 있다.

아래는 **등록 전 설정 추천**이다. 이번 작업에서는 작업 등록·계정 비밀번호 조회·전원 정책 변경·재부팅을 하지 않았다.

| 항목 | 공식 지원과 추천 설정 | 한계·구현 과제 |
| --- | --- | --- |
| 주기 실행 | 수집은 기존 운영 시간 30분, 승인 작업은 5분. 절대 Python 실행 파일 경로·인수·작업 디렉토리 명시 | UI의 상대 경로/PATH에 의존하지 않고 같은 venv·DB 사용 |
| 절전 복귀 | `WakeToRun=True`로 실행 시 깨우기 가능 | 하드웨어·전원 정책 실기 확인 필요. PC 전원 꺼짐과 인터넷 단절을 해결하지 않음 |
| 놓친 작업 | `StartWhenAvailable`로 예정 시각 후 시작 가능. 기본 False, 적용 가능한 트리거 조건과 기본 지연 10분 명시 | 즉시 복구·승인 후 10분 보장 기능이 아님. 발행은 놓친 스케줄을 재생하지 않고 현재 날짜·마감·승인 재확인 |
| 중복 실행 | `MultipleInstances=IgnoreNew`(값 2) | 같은 작업의 중복만 억제. 다른 작업명·수동 CLI의 중복은 DB 발행 키·점유로 차단 |
| 프로세스 실패 후 재시작 | `RestartCount`와 `RestartInterval` 지원, interval 최저 1분 | 초기 게시 작업은 스케줄러 자동 재시작을 끄고 다음 정상 주기에서 DB 상태를 읽는 쪽 추천. OS 재시작으로 API 재시도 횟수를 초기화하면 안 됨 |
| 로그온 | `INTERACTIVE_TOKEN`은 이미 로그인한 세션에서만 실행. `PASSWORD` 방식은 등록 시 비밀번호 필요 | 초기 검증은 운영자 로그인 상태에서 진행. 로그아웃 중 실행은 별도 계정·권한 설정/시험 필요 |
| 권한·네트워크 | 최소 권한 계정으로 DB·로그·설정 접근. `S4U`는 비밀번호 미저장 대신 네트워크·암호화 파일 접근 제한 명시 | 외부 API 작업에 `S4U`를 무심코 적용하지 않음. 일반적인 API 요청에 최고 관리자 권한을 기본 요구하지 않음 |

공식 근거: [WakeToRun](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-waketorun), [StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable), [MultipleInstances](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-multipleinstances), [RestartCount](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-restartcount), [RestartInterval](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-restartinterval), [TASK_LOGON_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_logon_type), [실행 보안 문맥](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks).

로컬 Streamlit은 사용자가 로그인했을 때 시작하거나 수동으로 띄우고 브라우저는 필요할 때 연다. 백그라운드 예약 CLI가 브라우저 로그인 화면을 조작하게 하지 않는다. 로그인하지 않은 상태로도 PC가 켜져 있는 것과 사용자 세션·권한이 준비돼 있는 것은 다르다. 로그아웃 중 백그라운드 운영을 원할 경우 사용자가 Windows 자격증명을 직접 등록해야 하며 비밀번호를 코드·명령 인수·문서에 기록하지 않는다.

## KST·UTC·거래일 경계

운영 시각은 KST 고정이며 데이터에는 UTC와 미국 거래일을 구별해 저장한다. 작업 XML `StartBoundary`에는 UTC 오프셋 표기를 사용할 수 있다. 등록 전 내보낸 XML과 “다음 실행 시간”을 대조하고 PC 시간대 변경 후도 확인한다. [Microsoft StartBoundary](https://learn.microsoft.com/en-us/windows/win32/taskschd/trigger-startboundary)

| 운영 시각 | UTC 환산 | 날짜 주의 |
| --- | --- | --- |
| D일 07:00 준비 | D-1일 22:00Z | UTC 요일을 KST 요일로 혼동하지 않음 |
| D일 07:30 정보 기준 | D-1일 22:30Z | 아침 뉴스 버전 판정 기준 |
| D일 08:00 목표 | D-1일 23:00Z | 직전 완료 미국 거래일을 별도로 조회 |
| D일 09:00 아침 마감·기업 시작 | D일 00:00Z | 두 편성의 운영일은 별도 판정 |
| D일 17:30 마지막 수집·18:00 마감 | D일 08:30Z·09:00Z | 18:00부터 새 글 전송 금지 |

예를 들어 KST 토요일 아침은 직전 미국 금요일 거래의 아침 호 후보가 될 수 있지만 같은 토요일 기업 뉴스 수집은 미국 거래일 조건에서 제외될 수 있다. 한국의 월~금 트리거만 걸어 거래일 검사를 대신하지 않는다. 미국 서머타임과 휴장은 거래소 달력에서 판정하고 KST를 미국 현지 시각과 고정 차이로 처리하지 않는다.

실제 남은 시험은 예정 시각 전후 실행 기록, 절전 복귀, PC 재시작 뒤 지연 시작, 로그인/로그아웃, 전원·네트워크 중단, 마감 뒤 누락 작업 시작이다. 현재는 등록할 실제 수집·게시 CLI가 없으므로 이 시험을 완료로 표시하지 않는다. SQLite의 독립 동시 연결·승인 버전·롤백·복원 실험 결과는 [R6 후속 확인](storage_admin.md#후속-확인-현재-windows-pc와-sqlite-실험)에 기록했다.
