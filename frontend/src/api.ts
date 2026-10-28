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

export interface Session { operator: string | { email?: string; display_name?: string }; mode: string; csrf_token: string; }
export interface DraftSummary {
  id: string; target_date: string; edition: 'AM' | 'PM'; market_trade_date?: string | null;
  version: number; decision_revision: number; status: string; news_count: number;
  scheduled_at?: string | null; expires_at?: string | null; hold_reason?: string | null;
}
export interface Evidence {
  id?: string; evidence_id?: string; source?: string; url?: string; published_at?: string; collected_at?: string;
  event_key?: string; fact_version?: string; text?: string; claims?: unknown[];
}
export interface Draft extends DraftSummary {
  mode: string; synthetic: boolean; frozen_at?: string; validation: { status: string; blocking_reasons: string[] };
  posts: { position: number; kind: string; text: string; evidence_ids: string[]; evidence?: Evidence[]; weighted_length?: number; }[];
  evidence?: Evidence[]; evidence_bundles?: Evidence[]; allowed_actions: string[];
  publication?: { job_id?: string | null; posts: { position?: number; state?: string; status?: string; x_id?: string; }[] };
}
export interface DecisionBody { action: 'approve' | 'hold'; expected_version: number; expected_decision_revision: number; reason?: string; }
export interface Attempt { id: string; body: DecisionBody; key: string; }
export function decide(attempt: Attempt, csrf: string) {
  return request(`/api/drafts/${encodeURIComponent(attempt.id)}/decision`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': attempt.key },
    body: JSON.stringify(attempt.body),
  });
}
export function canApprove(draft: Draft, fresh: boolean) {
  const sharedEvidence = draft.evidence ?? draft.evidence_bundles ?? [];
  const evidenceVisible = draft.posts.length > 0 && draft.posts.every(post => (post.evidence?.length ?? 0) > 0 || (post.evidence_ids.length > 0 && post.evidence_ids.every(id => sharedEvidence.some(evidence => (evidence.id ?? evidence.evidence_id) === id))));
  return fresh && draft.mode === 'reviewed' && !draft.synthetic && draft.status === 'validated'
    && draft.validation.status === 'passed' && draft.allowed_actions.includes('approve') && evidenceVisible
    && (!draft.expires_at || Date.parse(draft.expires_at) > Date.now());
}
export function safeSourceUrl(value: string | undefined): string | undefined {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}
