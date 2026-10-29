# 배포 자산

| 위치 | 현재 용도 |
| --- | --- |
| [cloud/](cloud/README.md) | 이전 Streamlit·Neon 가상 미리보기와 GCP 단발성 smoke 절차 |
| `cloud/Dockerfile` | `python -m xfolio.cloud`를 실행하는 가상 시험 이미지 |
| `cloud/secrets.example.toml` | 값이 없는 설정 예제. 실제 비밀은 Git에 저장하지 않음 |

현재 제품 목표는 React·FastAPI·PostgreSQL·별도 Python worker의 Docker/AWS 배포다. 위 Dockerfile을 제품 운영 이미지로 취급하지 않는다. 새 배포 자산은 구현과 검증이 이루어진 뒤 별도 폴더로 추가한다.

[배포 작업 계획](../tasks/plans/클라우드_전환.md) · [프로젝트 실행 안내](../README.md) · [기존 대시보드](../dashboard/README.md)
