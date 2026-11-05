import { request } from '../../shared/http';

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
  transport_mode?: 'mock' | 'live' | null;
  mode: string; synthetic: boolean; frozen_at?: string; validation: { status: string; blocking_reasons: string[] };
  posts: { position: number; kind: string; text: string; evidence_ids: string[]; evidence?: Evidence[]; weighted_length?: number | null; }[];
  evidence?: Evidence[]; evidence_bundles?: Evidence[]; allowed_actions: string[];
  publication?: { job_id?: string | null; posts: { position?: number; state?: string; status?: string; x_id?: string; }[] };
}
export interface DecisionBody { action: 'approve' | 'hold'; expected_version: number; expected_decision_revision: number; reason?: string; review_checks?: { evidence_support: boolean; conditions_preserved: boolean; relevance_and_novelty: boolean }; }
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
  return fresh && draft.edition === 'AM' && draft.posts.length <= 4 && draft.posts[0]?.kind === 'etf' && draft.mode === 'reviewed' && !draft.synthetic && draft.status === 'validated'
    && draft.validation.status === 'passed' && draft.allowed_actions.includes('approve') && evidenceVisible
    && (!draft.expires_at || Date.parse(draft.expires_at) > Date.now());
}
export function safeSourceUrl(value: string | undefined): string | undefined {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}
