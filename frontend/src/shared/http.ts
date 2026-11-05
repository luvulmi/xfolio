export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 15_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...options, credentials: 'same-origin', signal: controller.signal });
    if (!response.ok) {
      let code = `HTTP_${response.status}`;
      try { const body = await response.json(); code = body.error?.code ?? body.detail?.code ?? code; } catch { /* 상태 코드로 안내 */ }
      throw new ApiError(response.status, code, response.status === 401 ? '로그인이 만료되었습니다.' : response.status === 403 ? '이 작업을 수행할 권한이 없습니다.' : response.status === 409 ? '편성 상태가 변경되었습니다. 최신 내용을 확인하세요.' : '요청을 완료하지 못했습니다. 다시 확인하세요.');
    }
    return response.status === 204 ? undefined as T : await response.json() as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'RESULT_UNCONFIRMED', '응답을 확인하지 못했습니다. 최신 상태를 먼저 조회합니다.');
  } finally { clearTimeout(timer); }
}
