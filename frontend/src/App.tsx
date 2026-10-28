import { useCallback, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, canApprove, decide, request, safeSourceUrl } from './api';
import type { Attempt, Draft, DraftSummary, Session } from './api';

const labels: Record<string, string> = { prepared: '검증 준비', validated: '승인 대기', approved: '승인됨', scheduled: '예약됨', held: '보류', sending: '게시 중', published: '게시 완료', partial: '일부 게시', unknown: '결과 불명', failed: '실패', expired: '만료', no_content: '정상 · 선정 뉴스 없음', not_operating: '운영일 아님', complete: '완료', dry_run: '시험 실행', reviewed: '운영자 검토', auto: '자동 운영' };
const label = (value: string) => labels[value] ?? value;
function todayKst() { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); }
function time(value?: string | null) { return value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—'; }
function detailId() { try { const match = location.hash.match(/^#\/drafts\/(.+)$/); return match ? decodeURIComponent(match[1]) : null; } catch { return null; } }

export function App() {
  const client = useQueryClient();
  const session = useQuery({ queryKey: ['session'], queryFn: () => request<Session>('/api/auth/me'), retry: false });
  const [selected, setSelected] = useState(detailId);
  const [logoutError, setLogoutError] = useState('');
  const refreshSession = useCallback(() => { void session.refetch(); }, [session.refetch]);
  useEffect(() => { const change = () => setSelected(detailId()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  const unauthorized = session.error instanceof ApiError && session.error.status === 401;
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/">X<span>Folio</span><small>OPERATIONS</small></a><div className="nav-caption">작업 공간</div><a className="nav-link active" href="#/"><span>▦</span> 편성 검토</a><div className="sidebar-bottom"><span className="status-dot" /> 운영자 전용<div>미국 시장 브리핑</div></div></aside>
    <div className="workspace"><header className="topbar"><span>미국 시장 <span className="muted">/</span> 편성 관리</span><div>{session.data && !session.error && <><span className="mode">{label(session.data.mode)}</span><span className="operator">{typeof session.data.operator === 'string' ? session.data.operator : session.data.operator.display_name ?? session.data.operator.email}</span><button className="text-button" onClick={async () => { try { await request('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.data.csrf_token } }); client.clear(); location.hash = '#/'; await session.refetch(); } catch { setLogoutError('로그아웃을 확인하지 못했습니다. 다시 시도하세요.'); } }}>로그아웃</button></>}</div></header>
    <main>{logoutError && <Notice message={logoutError} />}{session.isPending ? <Loading text="운영자 세션을 확인하고 있습니다." /> : session.error ? <section className="login-panel"><div className="eyebrow">XFOLIO ADMIN</div><h1>{unauthorized ? '운영자 로그인' : '접속을 확인해 주세요'}</h1><p>{unauthorized ? '편성의 근거와 문안을 확인하고 승인합니다.' : session.error.message}</p>{unauthorized ? <a className="button primary" href="/api/auth/login">Google로 로그인</a> : <button className="button" onClick={() => session.refetch()}>다시 확인</button>}</section> : session.data ? selected ? <Detail id={selected} session={session.data} onAuthFailure={refreshSession} /> : <Dashboard onAuthFailure={refreshSession} /> : null}</main>
    <footer>모든 운영 시각은 KST · 게시 결과는 X 응답 기록으로 확인합니다.</footer></div>
  </div>;
}

function Notice({ message }: { message: string }) { return <div className="notice" role="alert">{message}</div>; }
function Loading({ text }: { text: string }) { return <div className="loading" role="status"><span className="spinner" />{text}</div>; }
function Badge({ status }: { status: string }) { return <span className={`badge ${status}`}>{label(status)}</span>; }

function Dashboard({ onAuthFailure }: { onAuthFailure: () => void }) {
  const [date, setDate] = useState(todayKst); const [edition, setEdition] = useState(''); const [status, setStatus] = useState('');
  const [cursors, setCursors] = useState<(string | null)[]>([null]); const cursor = cursors[cursors.length - 1];
  const params = new URLSearchParams({ date, limit: '20' }); if (edition) params.set('edition', edition); if (status) params.set('status', status); if (cursor) params.set('cursor', cursor);
  const list = useQuery({ queryKey: ['drafts', date, edition, status, cursor], queryFn: () => request<{ items: DraftSummary[]; next_cursor: string | null }>(`/api/drafts?${params}`) });
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => request<Record<string, unknown>>('/api/operations/summary') });
  useEffect(() => { if ([list.error, summary.error].some(e => e instanceof ApiError && e.status === 401)) onAuthFailure(); }, [list.error, summary.error, onAuthFailure]);
  const updateFilter = (set: (value: string) => void, value: string) => { set(value); setCursors([null]); };
  return <><div className="page-title"><div><div className="eyebrow">EDITORIAL DESK</div><h1>편성 검토</h1><p>확인된 근거를 검토하고, 정확한 버전의 편성 전체를 승인하세요.</p></div><button className="button" disabled={list.isFetching || summary.isFetching} onClick={() => { void list.refetch(); void summary.refetch(); }}>↻ 새로고침</button></div>
    <section className="summary-grid" aria-label="운영 현황"><SummaryCard title="최근 수집" value={collectionLabel((summary.data?.collection as {status?: string})?.status)} description="정상 0건과 불완전 수집을 구분합니다." /><SummaryCard title="월 사용 현황" value={usageLabel(summary.data?.usage)} description="앱 관측 원장 · 계정 전체 청구액 아님" /><SummaryCard title="조치가 필요한 상태" value={alertLabel(summary.data?.alerts)} description="보류·알림 실패의 원인을 확인하세요." /></section>
    {summary.error && <Notice message="운영 현황의 최신 조회에 실패했습니다." />}
    <section className="panel"><div className="panel-heading"><h2>검토할 편성</h2><span className="muted">마지막 조회 {list.dataUpdatedAt ? time(new Date(list.dataUpdatedAt).toISOString()) : '—'}</span></div><div className="filters"><label>대상일<input type="date" value={date} onChange={e => updateFilter(setDate, e.target.value)} /></label><label>편성<select value={edition} onChange={e => updateFilter(setEdition, e.target.value)}><option value="">전체 편성</option><option value="AM">아침 브리핑</option><option value="PM">18시 추가 뉴스</option></select></label><label>상태<select value={status} onChange={e => updateFilter(setStatus, e.target.value)}><option value="">전체 상태</option>{Object.entries(labels).filter(([key]) => ['prepared','validated','scheduled','held','published','partial','unknown','failed','expired'].includes(key)).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label></div>
      {list.error && <Notice message="편성 목록을 확인하지 못했습니다. 새로고침으로 다시 확인하세요." />}
      {list.isPending ? <Loading text="편성 목록을 불러오고 있습니다." /> : list.data?.items.length ? <div className="table-wrap"><table><thead><tr><th>대상일 · 편성</th><th>미국 거래일</th><th>버전 · 뉴스</th><th>상태</th><th>발행 목표 / 마감</th><th><span className="sr-only">상세</span></th></tr></thead><tbody>{list.data.items.map(item => <tr key={item.id}><td><strong>{item.target_date}</strong><div>{item.edition === 'AM' ? '아침 브리핑' : '18시 추가 뉴스'}</div></td><td>{item.market_trade_date ?? '—'}</td><td>v{item.version}<div className="muted">뉴스 {item.news_count}건</div></td><td><Badge status={item.status} />{item.hold_reason && <div className="muted">{item.hold_reason}</div>}</td><td>{time(item.scheduled_at)}<div className="muted">{time(item.expires_at)}</div></td><td><a className="detail-link" href={`#/drafts/${encodeURIComponent(item.id)}`}>검토 →</a></td></tr>)}</tbody></table></div> : !list.error && <div className="empty"><span>▤</span><h3>표시할 편성이 없습니다</h3><p>선택한 날짜와 필터를 확인하세요. 빈 목록은 수집 성공을 뜻하지 않습니다.</p></div>}
      <div className="pagination"><button className="button" disabled={cursors.length === 1 || list.isFetching} onClick={() => setCursors(cursors.slice(0, -1))}>이전</button><span>{cursors.length} 페이지</span><button className="button" disabled={!list.data?.next_cursor || list.isFetching || !!list.error} onClick={() => setCursors([...cursors, list.data!.next_cursor])}>다음</button></div>
    </section></>;
}

function SummaryCard({ title, value, description }: { title: string; value: unknown; description: string }) {
  const display = value == null ? '확인 대기' : typeof value === 'string' ? label(value) : typeof value === 'number' ? String(value) : JSON.stringify(value);
  return <article className="summary-card"><span>{title}</span><strong>{display}</strong><small>{description}</small></article>;
}

function collectionLabel(value?: string) {
  return value ? ({ not_observed: '수집 기록 없음', complete: '수집 완료', partial: '수집 불완전', failed: '수집 실패', no_content: '정상 · 선정 뉴스 없음', not_operating: '운영일 아님' }[value] ?? value) : undefined;
}

function usageLabel(value: unknown) {
  if (!value || typeof value !== 'object') return undefined;
  const usage = value as {estimated_krw?: number; reserved_krw?: number; confirmed_krw?: number; monthly_limit_krw?: number};
  return `${new Intl.NumberFormat('ko-KR').format((usage.confirmed_krw ?? 0) + (usage.reserved_krw ?? 0))}원 / ${new Intl.NumberFormat('ko-KR').format(usage.monthly_limit_krw ?? 50_000)}원`;
}
function alertLabel(value: unknown) {
  if (!value || typeof value !== 'object') return undefined;
  const alerts = value as {open?: number; failed?: number; status?: string};
  if (alerts.status === 'not_implemented') return '알림 미연결';
  return `미해결 ${alerts.open ?? 0} · 알림 실패 ${alerts.failed ?? 0}`;
}

function Detail({ id, session, onAuthFailure }: { id: string; session: Session; onAuthFailure: () => void }) {
  const client = useQueryClient();
  const detail = useQuery({ queryKey: ['draft', id], queryFn: () => request<Draft>(`/api/drafts/${encodeURIComponent(id)}`) });
  const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false); const [message, setMessage] = useState(''); const [uncertain, setUncertain] = useState<Attempt | null>(null); const [decisionBlocked, setDecisionBlocked] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => { const timer = setInterval(() => tick(value => value + 1), 30_000); return () => clearInterval(timer); }, []);
  useEffect(() => { setUncertain(null); setReason(''); setMessage(''); setDecisionBlocked(false); }, [id, session.csrf_token]);
  useEffect(() => { if (detail.error instanceof ApiError && detail.error.status === 401) onAuthFailure(); }, [detail.error, onAuthFailure]);
  async function submit(attempt: Attempt) {
    setBusy(true); setMessage('');
    try { await decide(attempt, session.csrf_token); setUncertain(null); setMessage('결정 요청을 확인했습니다. 최신 편성 상태와 게시 결과를 확인하세요. 이미 시작된 전송은 취소되지 않습니다.'); }
    catch (error) { const e = error as ApiError; setUncertain(e.status === 0 ? attempt : null); setMessage(`${e.message} (${e.code})`); if (e.status === 403) setDecisionBlocked(true); if ([401, 403].includes(e.status)) onAuthFailure(); }
    finally { await detail.refetch(); await Promise.all([client.invalidateQueries({ queryKey: ['drafts'] }), client.invalidateQueries({ queryKey: ['summary'] })]); setBusy(false); }
  }
  const draft = detail.data; const fresh = !detail.isError && !detail.isFetching && !busy && !decisionBlocked;
  const evidenceList = draft ? (draft.evidence ?? draft.evidence_bundles ?? draft.posts.flatMap(post => post.evidence ?? [])) : [];
  function begin(action: 'approve' | 'hold') { if (!draft) return; void submit({ id, key: crypto.randomUUID(), body: { action, expected_version: draft.version, expected_decision_revision: draft.decision_revision, ...(action === 'hold' ? { reason: reason.trim() } : {}) } }); }
  return <><a className="back-link" href="#/">← 편성 목록</a><div className="page-title"><div><div className="eyebrow">EDITION REVIEW</div><h1>{draft?.edition === 'AM' ? '아침 브리핑' : draft ? '18시 추가 뉴스' : '편성 상세'}</h1><p>{draft?.target_date ?? '근거와 상태를 확인하고 있습니다.'}{draft && <> · v{draft.version} · <Badge status={draft.status} /></>}</p></div><button className="button" disabled={detail.isFetching || busy} onClick={() => detail.refetch()}>↻ 최신 상태 확인</button></div>
    {message && <Notice message={message} />}{detail.error && <Notice message="최신 확인 실패 · 승인 동작을 차단했습니다. 다시 조회하세요." />}
    {detail.isPending ? <Loading text="편성과 근거를 불러오고 있습니다." /> : draft && <><section className="edition-meta"><div><span>게시 구성</span><strong>{draft.edition === 'AM' ? '지수부터 이어지는 스레드' : '사건별 독립 글'}</strong></div><div><span>발행 목표 · 마감</span><strong>{time(draft.scheduled_at)} · {time(draft.expires_at)}</strong></div><div><span>근거 동결</span><strong>{time(draft.frozen_at)}</strong></div></section>
      {draft.synthetic && <div className="preview-banner">합성 시험 자료 · 실제 게시 예약 불가</div>}
      <div className="review-layout"><section><div className="section-title"><h2>완성 게시글</h2><span>{draft.posts.length}개 글 · 편성 전체 검토</span></div>{draft.posts.map(post => <article className="post-card" key={post.position}><div className="post-heading"><span className="post-number">{post.position.toString().padStart(2, '0')}</span><span>{post.kind === 'index' ? '두 지수 종가' : '중요 뉴스'}</span>{post.weighted_length != null && <small>{post.weighted_length} / 280</small>}</div><p className="post-text">{post.text}</p><div className="evidence-ids">연결 근거: {post.evidence_ids.join(', ') || '없음'}</div></article>)}
        <section className="panel evidence-panel"><h2>주장과 출처 근거</h2>{evidenceList.length ? evidenceList.map((evidence, i) => <article key={evidence.id ?? i}><strong>{evidence.source ?? evidence.id ?? evidence.evidence_id}</strong>{safeSourceUrl(evidence.url) && <a href={safeSourceUrl(evidence.url)} target="_blank" rel="noreferrer">원문 확인 ↗</a>}<p>{evidence.text ?? '허용 근거는 상세 기록에서 확인하세요.'}</p><small>발행 {time(evidence.published_at)} · 수집 {time(evidence.collected_at)}</small>{evidence.event_key && <small> · 사건 {evidence.event_key} / {evidence.fact_version ?? '버전 미상'}</small>}{evidence.claims && <pre>{JSON.stringify(evidence.claims, null, 2)}</pre>}</article>) : <p className="muted">표시 가능한 상세 근거가 없습니다. 연결 근거와 검증 결과를 확인하세요.</p>}</section>
      </section><aside className="review-side"><section className="panel decision-panel"><div className="eyebrow">VERSION {draft.version}</div><h2>편성 결정</h2><Badge status={draft.status} /><p>이 버전의 모든 글을 예약합니다. 일부 글을 제외하려면 먼저 보류하고 CLI에서 새 버전을 만드세요.</p><div className={`validation ${draft.validation.status === 'passed' ? 'passed' : ''}`}>검증: {draft.validation.status === 'passed' ? '통과' : '확인 필요'}</div>{draft.validation.blocking_reasons.map(code => <div key={code} className="muted">{code}</div>)}
        {draft.mode !== 'auto' && <button className="button primary full" disabled={!canApprove(draft, fresh) || !!uncertain || session.mode !== 'reviewed'} onClick={() => begin('approve')}>{busy ? '처리 중…' : '편성 전체 승인'}</button>}
        <label className="reason-label">보류 사유<textarea value={reason} maxLength={300} onChange={e => setReason(e.target.value)} placeholder="수정이 필요한 조건이나 확인 사항을 적어 주세요." /></label><small className="muted">키·기사 본문·개인정보는 입력하지 마세요.</small><button className="button full" disabled={!fresh || !!uncertain || !reason.trim() || !draft.allowed_actions.includes('hold')} onClick={() => begin('hold')}>{draft.status === 'sending' ? '남은 글 중단' : ['scheduled','approved'].includes(draft.status) ? '승인 철회·보류' : '보류'}</button>
        {uncertain && <div className="retry-panel"><p>처리 결과가 불명확합니다. 최신 상태를 확인한 뒤 같은 요청을 재전송할 수 있습니다.</p><button className="button full" disabled={!fresh} onClick={() => void submit(uncertain)}>같은 요청 다시 확인</button></div>}
        {draft.status === 'held' && <p className="muted">보류된 버전은 다시 승인할 수 없습니다. CLI에서 새 버전을 만들고 검증한 뒤 재승인하세요.</p>}
      </section><section className="panel publication-panel"><h2>게시 결과</h2>{draft.publication?.posts.length ? draft.publication.posts.map((post, i) => <div key={i}>글 {post.position ?? i + 1} · {label(post.state ?? post.status ?? 'unknown')}<small>{post.x_id ? `X ID ${post.x_id}` : '확인된 X ID 없음'}</small></div>) : <p className="muted">아직 확인된 게시 결과가 없습니다.</p>}</section></aside></div></>}
  </>;
}
