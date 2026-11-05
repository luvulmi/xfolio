import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, request } from './api';
import type { Session } from './api';
import { App as LegacyApp } from './LegacyApp';

type Settings = { revision: number; morning_enabled: boolean; paused: boolean; intraday_enabled: boolean; close_enabled: boolean };
type Instrument = { code: string; name: string; market: string; currency: string; eligible: boolean; retrieved_at?: string };
type Watchlist = { revision: number; codes: string[]; items: Instrument[]; max_active: number };
type Edition = { id: string; target_date: string; slot: string; status: string; price_count: number; news_count: number; reasons: string[]; settings_revision: number; watchlist_revision: number; mode: string; synthetic: boolean; body?: string; created_at: string; expires_at: string; settings?: Settings };
type Delivery = { id: string; edition_id: string; target_date: string; slot: string; status: string; transport_mode: string; created_at: string; updated_at: string; parts?: { position?: number; status?: string; message_id?: string | number; error_code?: string; attempt_count?: number }[]; body?: string | null };
type Summary = { market_open: boolean | null; settings: Settings; watchlist: Watchlist; newsletters: Edition[] };
const names: Record<string, string> = { ready: '준비됨', partial: '일부 준비·일부 성공', failed: '실패', skipped: '정상 건너뜀', pending: '대기', sending: '전송 중', confirmed: '전송 확인', unknown: '결과 불명', retryable_failure: '안전한 재시도 대기', mock: '모의', live: '실제' };
const label = (value: string) => names[value] ?? value;
const time = (value?: string) => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '확인 대기';
const route = () => location.hash.replace(/^#/, '') || '/';
const menus = [['/', '대시보드'], ['/newsletters', '뉴스레터'], ['/deliveries', '발송 이력'], ['/watchlist', '관심 종목'], ['/settings', '알림 설정']];

function ErrorNotice({ error }: { error: unknown }) {
  const client = useQueryClient();
  useEffect(() => { if (error instanceof ApiError && error.status === 401) void client.invalidateQueries({ queryKey: ['session'] }); }, [error, client]);
  if (!error) return null;
  const value = error as ApiError;
  return <div className="notice" role="alert">{value.code === 'DELIVERIES_NOT_CONNECTED' ? '발송 이력은 자동 전송 기능 연결 후 확인할 수 있습니다.' : `${value.message || '조회에 실패했습니다.'} ${value.code ? `(${value.code})` : ''}`}</div>;
}
function Status({ value }: { value: string }) { return <span className={`badge ${value}`}>{label(value)}</span>; }

export function App() {
  return new URLSearchParams(location.search).get('legacy') === '1' ? <LegacyApp /> : <NewsletterApp />;
}
function NewsletterApp() {
  const client = useQueryClient(); const [path, setPath] = useState(route); const [error, setError] = useState<unknown>();
  const session = useQuery({ queryKey: ['session'], queryFn: () => request<Session>('/api/auth/me'), retry: false });
  useEffect(() => { const change = () => setPath(route()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  const unauthorized = session.error instanceof ApiError && session.error.status === 401;
  async function logout() {
    try { await request('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.data!.csrf_token } }); client.clear(); location.hash = '#/'; await session.refetch(); }
    catch (e) { setError(e); }
  }
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#/">X<span>Folio</span><small>NEWSLETTER</small></a><div className="nav-caption">본인용 관리자</div><nav aria-label="메뉴">{menus.map(([url, title]) => <a key={url} className={`nav-link ${path === url ? 'active' : ''}`} href={`#${url}`}>{title}</a>)}</nav><div className="sidebar-bottom">비공개 접속 · 국내 ETF · Telegram</div></aside>
    <div className="workspace"><header className="topbar"><span>개인 뉴스레터 관리</span>{session.data && !session.error && <div><span className="operator">{typeof session.data.operator === 'string' ? session.data.operator : session.data.operator.display_name ?? session.data.operator.email}</span><button className="text-button" onClick={logout}>로그아웃</button></div>}</header>
      <main className="newsletter-admin"><ErrorNotice error={error} />{session.isPending ? <p role="status">운영자 세션을 확인하고 있습니다.</p> : session.error ? <section className="login-panel"><h1>{unauthorized ? '운영자 로그인' : '접속을 확인해 주세요'}</h1><p>뉴스레터·종목·알림 설정을 확인합니다.</p><ErrorNotice error={unauthorized ? null : session.error} />{unauthorized ? <a className="button primary" href="/api/auth/login">Google로 로그인</a> : <button className="button" onClick={() => session.refetch()}>다시 확인</button>}</section> : session.data ? <AdminPage path={path} session={session.data} /> : null}</main>
      <footer>모든 시각은 KST · 한국 휴장 평일/주말 미발송 · 전송 결과는 실제 응답 기록으로 확인합니다.</footer></div></div>;
}

function AdminPage({ path, session }: { path: string; session: Session }) {
  if (path === '/settings') return <SettingsPage session={session} />;
  if (path === '/watchlist') return <WatchlistPage session={session} />;
  if (path.startsWith('/newsletters/') || path.startsWith('/deliveries/')) { const [kind, id] = path.slice(1).split('/'); return <Detail kind={kind} id={id} />; }
  if (path === '/newsletters') return <EditionsPage />;
  if (path === '/deliveries') return <DeliveriesPage />;
  return <Dashboard />;
}
function Dashboard() {
  const q = useQuery({ queryKey: ['newsletter-summary'], queryFn: () => request<Summary>('/api/newsletter-operations/summary') });
  return <><h1>대시보드</h1><p>한국 거래일 07:50 준비 → 08:00 발송 · 08:10 마감</p><ErrorNotice error={q.error} />{q.isPending ? <p role="status">운영 상태를 조회하고 있습니다.</p> : q.data && <><div className="summary-grid"><Card title="오늘 한국 시장" value={q.data.market_open === true ? '개장' : q.data.market_open === false ? '휴장 · 발송 없음' : '개장 여부 확인 대기'} /><Card title="발송 설정" value={q.data.settings.paused ? '전체 일시 중지' : q.data.settings.morning_enabled ? '아침 활성' : '아침 비활성'} /><Card title="활성 종목" value={`${q.data.watchlist.codes.length} / 10`} /><Card title="오늘 편성" value={`${q.data.newsletters.length}건`} /></div><section className="panel"><h2>운영 확인</h2><p>시세 신선도와 비용 원장은 연결·관측 전까지 확인 대기로 표시합니다.</p><p>편성 준비는 전송 성공을 뜻하지 않습니다. <a href="#/deliveries">발송 이력 확인</a></p></section><EditionTable items={q.data.newsletters} /></>}</>;
}
function Card({ title, value }: { title: string; value: string }) { return <article className="summary-card"><span>{title}</span><strong>{value}</strong></article>; }
function EditionTable({ items }: { items: Edition[] }) { return <section className="panel"><h2>뉴스레터</h2>{items.length ? <table><thead><tr><th>날짜/슬롯</th><th>상태</th><th>자료</th><th>환경</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><a href={`#/newsletters/${encodeURIComponent(item.id)}`}>{item.target_date} · {item.slot}</a></td><td><Status value={item.status} /></td><td>가격 {item.price_count} · 뉴스 {item.news_count}</td><td>{item.synthetic ? '합성 시험' : label(item.mode)}</td></tr>)}</tbody></table> : <p>표시할 뉴스레터가 없습니다. 수집·발송 성공을 뜻하지 않습니다.</p>}</section>; }
function EditionsPage() {
  const [day, setDay] = useState(''); const [status, setStatus] = useState(''); const params = new URLSearchParams(); if (day) params.set('date', day); if (status) params.set('status', status);
  const q = useQuery({ queryKey: ['newsletters', day, status], queryFn: () => request<{ items: Edition[] }>(`/api/newsletters?${params}`) });
  return <><h1>뉴스레터</h1><div className="filters"><label>날짜 <input type="date" value={day} onChange={e => setDay(e.target.value)} /></label><label>상태 <select value={status} onChange={e => setStatus(e.target.value)}><option value="">전체</option>{['ready', 'partial', 'failed', 'skipped'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label></div><ErrorNotice error={q.error} />{q.isPending ? <p role="status">뉴스레터를 조회하고 있습니다.</p> : q.data && <EditionTable items={q.data.items} />}</>;
}
function DeliveriesPage() {
  const q = useQuery({ queryKey: ['deliveries'], queryFn: () => request<{ items: Delivery[] }>('/api/deliveries') });
  return <><h1>발송 이력</h1><p>부분 성공·결과 불명은 자동으로 재송신하지 않습니다.</p><ErrorNotice error={q.error} />{q.isPending ? <p role="status">발송 이력을 조회하고 있습니다.</p> : q.data && <section className="panel">{q.data.items.length ? <table><thead><tr><th>날짜</th><th>환경</th><th>상태</th><th>갱신</th></tr></thead><tbody>{q.data.items.map(x => <tr key={x.id}><td><a href={`#/deliveries/${encodeURIComponent(x.id)}`}>{x.target_date} · {x.slot}</a></td><td>{label(x.transport_mode)}</td><td><Status value={x.status} /></td><td>{time(x.updated_at)}</td></tr>)}</tbody></table> : <p>발송 기록이 없습니다. 전송 성공을 뜻하지 않습니다.</p>}</section>}</>;
}
function Detail({ kind, id }: { kind: string; id: string }) {
  const q = useQuery({ queryKey: [kind, id], queryFn: () => request<Edition & Delivery>(`/api/${kind}/${id}`) });
  return <><a href={`#/${kind}`}>← 목록</a><h1>{kind === 'newsletters' ? '뉴스레터 상세' : '발송 상세'}</h1><ErrorNotice error={q.error} />{q.data && !q.error && <section className="panel"><h2>{q.data.target_date} · {q.data.slot}</h2><Status value={q.data.status} /><p>{q.data.synthetic ? '합성 시험 자료' : label(q.data.transport_mode ?? q.data.mode)}</p><p>생성 {time(q.data.created_at)} · 갱신 {time(q.data.updated_at)} · 보존 만료 {time(q.data.expires_at)}</p>{q.data.settings && <p>종목 v{q.data.watchlist_revision} · 설정 v{q.data.settings.revision}</p>}{q.data.edition_id && <a href={`#/newsletters/${q.data.edition_id}`}>원본 뉴스레터 확인</a>}<pre className="newsletter-body">{q.data.body}</pre>{q.data.reasons?.length > 0 && <p>검사·제외 사유: {q.data.reasons.join(', ')}</p>}{q.data.parts?.map((part, i) => <p key={part.position ?? i}>조각 {part.position ?? i + 1} · {label(part.status ?? 'unknown')} · 시도 {part.attempt_count ?? '확인 대기'} · message_id {part.message_id ?? '없음'} {part.error_code ?? ''}</p>)}<p>실제 전송은 응답 기록으로 확인하며 보존기한이 지난 본문은 제공하지 않습니다.</p></section>}</>;
}
function SettingsPage({ session }: { session: Session }) {
  const client = useQueryClient(); const q = useQuery({ queryKey: ['notification-settings'], queryFn: () => request<Settings>('/api/notification-settings') });
  const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(); const [message, setMessage] = useState('');
  async function update(changes: Partial<Settings>) {
    if (!q.data) return; setBusy(true); setError(undefined); setMessage('');
    try { await request('/api/notification-settings', { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token }, body: JSON.stringify({ expected_revision: q.data.revision, ...changes }) }); setMessage('설정을 저장했습니다.'); }
    catch (e) { setError(e); }
    finally { await q.refetch(); await client.invalidateQueries({ queryKey: ['newsletter-summary'] }); setBusy(false); }
  }
  const blocked = busy || q.isFetching || q.isError || !q.data;
  return <><h1>알림 설정</h1><p>한국 거래일 08:00 고정 · 한국 휴장 평일/주말에는 가격·뉴스 모두 미발송</p><ErrorNotice error={q.error || error} />{message && <p role="status">{message}</p>}{q.data && !q.error && <section className="panel"><p>현재 설정 v{q.data.revision}</p><label className="setting-control"><input type="checkbox" checked={q.data.morning_enabled} disabled={blocked} onChange={e => void update({ morning_enabled: e.target.checked })} />아침 08:00 알림</label><label className="setting-control"><input type="checkbox" checked={q.data.paused} disabled={blocked} onChange={e => void update({ paused: e.target.checked })} />전체 발송 일시 중지</label><label className="setting-control"><input type="checkbox" checked={false} disabled />14:00 장중 알림 · 인수 전</label><label className="setting-control"><input type="checkbox" checked={false} disabled />16:00 마감 알림 · 인수 전</label><p>재개해도 마감이 지난 뉴스레터를 몰아서 보내지 않습니다.</p></section>}</>;
}
function WatchlistPage({ session }: { session: Session }) {
  const client = useQueryClient(); const q = useQuery({ queryKey: ['watchlist'], queryFn: () => request<Watchlist>('/api/watchlist') });
  const [text, setText] = useState(''); const [query, setQuery] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(); const [message, setMessage] = useState('');
  const search = useQuery({ queryKey: ['instruments', query], queryFn: () => request<{ items: Instrument[] }>(`/api/instruments?q=${encodeURIComponent(query)}`), enabled: !!query });
  async function save(codes: string[]) {
    if (!q.data) return; setBusy(true); setError(undefined); setMessage('');
    try { await request('/api/watchlist', { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token }, body: JSON.stringify({ expected_revision: q.data.revision, codes }) }); setMessage('관심 종목을 저장했습니다.'); }
    catch (e) { setError(e); }
    finally { await q.refetch(); await client.invalidateQueries({ queryKey: ['newsletter-summary'] }); setBusy(false); }
  }
  const blocked = busy || q.isFetching || q.isError || !q.data;
  function move(index: number, delta: number) { const codes = [...q.data!.codes]; [codes[index], codes[index + delta]] = [codes[index + delta], codes[index]]; void save(codes); }
  return <><h1>관심 종목</h1><p>지원 확인된 국내 상장 해외 ETF를 최대10개 활성화합니다.</p><ErrorNotice error={q.error || error} />{message && <p role="status">{message}</p>}{q.data && !q.error && <section className="panel"><h2>활성 {q.data.codes.length} / 10 · v{q.data.revision}</h2><table><thead><tr><th>순서</th><th>종목</th><th>표시 순서·활성</th></tr></thead><tbody>{q.data.items.map((item, i) => <tr key={item.code}><td>{i + 1}</td><td>{item.name} <small>{item.code} · {item.currency}</small></td><td><button className="button" aria-label={`${item.name} 위로`} disabled={blocked || i === 0} onClick={() => move(i, -1)}>↑</button> <button className="button" aria-label={`${item.name} 아래로`} disabled={blocked || i === q.data!.codes.length - 1} onClick={() => move(i, 1)}>↓</button> <button className="button" disabled={blocked || q.data!.codes.length <= 1} onClick={() => void save(q.data!.codes.filter(c => c !== item.code))}>비활성화</button></td></tr>)}</tbody></table></section>}
    <section className="panel"><h2>종목 검색·추가</h2><form onSubmit={e => { e.preventDefault(); setQuery(text.trim()); }}><label>종목명 또는 코드 <input value={text} maxLength={120} onChange={e => setText(e.target.value)} /></label> <button className="button" disabled={!text.trim()}>검색</button></form><ErrorNotice error={search.error} />{search.data && <>{!search.data.items.length && <p>검색 결과가 없습니다. 서버 종목 마스터 확인이 필요할 수 있습니다.</p>}{search.data.items.map(item => <article className="instrument-result" key={item.code}><strong>{item.name} · {item.code}</strong><p>{item.market} · {item.currency} · {item.eligible ? '지원 확인' : '지원 미확인'} · 정보 조회 {time(item.retrieved_at)}</p><button className="button" disabled={blocked || !item.eligible || q.data!.codes.includes(item.code) || q.data!.codes.length >= 10} onClick={() => void save([...q.data!.codes, item.code])}>{q.data?.codes.includes(item.code) ? '활성 종목' : '확인 후 추가'}</button></article>)}</>}</section></>;
}
