# 실행 API 계약

`openapi.json`은 현재 FastAPI 구현에서 생성한 OpenAPI snapshot이다. 계획상의 목표 API와 구현된 경로를 구분한다. 목표 명세는 [설계 문서 목록](../docs/README.md)에서 확인한다.

저장소 루트에서 다음 명령으로 현재 코드의 계약을 생성한다. 외부 통신 없이 파일을 갱신한다.

```powershell
uv run python -m xfolio.api.export_openapi
```

계약 변경은 실제 API 변경과 함께 검토한다. 프론트가 기대하는 요청·응답을 바꾸면서 snapshot만 수동으로 수정하지 않는다.

[API 구현](../src/xfolio/api/app.py) · [검증 안내](../tests/README.md) · [관리자 앱](../frontend/README.md)
