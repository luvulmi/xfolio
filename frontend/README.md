# XFolio 관리자

React·TypeScript·Vite의 편성 목록/상세 화면입니다. 같은 origin의 FastAPI `/api`만 사용하고 브라우저에 공급자·DB·Google·Telegram 비밀을 저장하지 않습니다.

```powershell
cd frontend
npm ci
npm run dev
npm run build
npm test
```

개발 서버는 `127.0.0.1:5173`이고 `/api`를 `127.0.0.1:8000`으로 전달합니다. 실제 Google 로그인은 FastAPI의 허용 운영자·OIDC·HTTPS 설정이 필요합니다. 설정 미완료 오류를 개발 로그인으로 우회하지 않습니다. 화면은 실제 API 결과만 표시합니다.

`npm run build`는 TypeScript 검사와 정적 파일 생성을 수행합니다. 결과는 `dist/`에 생성되며 배포에서는 같은 origin의 `/api`를 서버로 전달해야 합니다.

## 회귀 테스트

`npm test`는 jsdom에서 로그인 안내·합성 자료/근거 누락 승인 차단·409·응답 불명 재전송·최신 조회 실패를 확인합니다.

```powershell
npm run test:e2e
```

Playwright는 전용 `127.0.0.1:5177` 서버를 띄워 API를 브라우저 안에서 모의합니다. 로컬 Windows는 설치된 Microsoft Edge를 사용합니다. CI에서는 `CI=true`로 Chromium을 선택하며 먼저 `npx playwright install --with-deps chromium`을 실행합니다. 실제 API·DB·Google·X·Telegram과 연결하지 않으므로 이 결과를 전체 제품 E2E/외부 연동 합격으로 해석하지 않습니다. 문서의 합성 입력을 제품의 실제 자료로 바꾸지 않습니다.

브라우저 시험은 미인증 로그인 안내, 목록→상세의 근거 표시, 409 뒤 재조회, 응답 불명 뒤 같은 멱등 키·본문 재전송을 검증합니다. `test-results/review-detail.png`는 격리된 모의 화면의 확인용 이미지이며 실제 운영 결과가 아닙니다.
