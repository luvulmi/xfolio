# 기존 Streamlit 가상 미리보기

이 폴더는 가상 자료로 저장·조회·인증을 시험한 기존 관리자 자산이다. 새 React 관리자 제품과 별도로 보존한다.

| 파일 | 역할 |
| --- | --- |
| `app.py` | 로컬 가상 미리보기 |
| `cloud_app.py` | 기존 Streamlit Cloud 인증·DB 미리보기 진입점 |
| `requirements.txt` | Streamlit 배포용 의존성 진입 파일 |

로컬 실행은 저장소 루트에서 다음 명령을 사용한다.

```powershell
uv run --extra dashboard streamlit run dashboard/app.py
```

클라우드 앱의 기존 배포 설정이 파일 경로를 참조하므로 이름과 위치를 유지한다. 이 자산을 실제 뉴스 자동 수집·승인·X 게시 전체가 구현된 관리자라고 해석하지 않는다.

[새 React 관리자](../frontend/README.md) · [기존 클라우드 시험 절차](../deploy/cloud/README.md) · [프로젝트 안내](../README.md)
