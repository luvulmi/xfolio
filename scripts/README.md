# 개발·실험 도구

이 폴더는 애플리케이션 패키지와 별개인 실행 보조 도구를 보관한다. 명령은 기본적으로 저장소 루트에서 실행한다.

| 위치 | 용도 |
| --- | --- |
| [dev/](dev/README.md) | 로컬 FastAPI 실행·HTTPS 프록시·개발 인증 연결 |
| [experiments/](experiments/README.md) | 뉴스 제공처·공식 자료·AI·저장 방식의 제한 표본 조사 |
| `run_dashboard.ps1` | 기존 로컬 Streamlit 가상 미리보기 실행 |

새 일상 개발 도구는 `dev/`, 재현 가능한 조사 코드는 `experiments/`에 둔다. 실험 결과와 관측 원본은 [작업 기록 체계](../tasks/README.md)에 연결한다. 파일별 외부 조회·모델 호출 옵션은 해당 스크립트와 검증 문서에서 확인하며, 모든 실험이 무통신이라고 가정하지 않는다.

[애플리케이션 코드](../src/xfolio/README.md) · [시험](../tests/README.md) · [배포 자산](../deploy/README.md)
