import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, request } from '../../shared/http';
import type { Session } from '../../shared/session';
import { ErrorNotice } from './components/feedback';
import { Dashboard } from './pages/DashboardPage';
import { EditionsPage } from './pages/NewslettersPage';
import { DeliveriesPage } from './pages/DeliveriesPage';
import { Detail } from './pages/DetailPage';
import { SettingsPage } from './pages/SettingsPage';
import { WatchlistPage } from './pages/WatchlistPage';

const route = () => location.hash.replace(/^#/, '') || '/';
const menus = [['/', '대시보드'], ['/newsletters', '뉴스레터'], ['/deliveries', '발송 이력'], ['/watchlist', '관심 종목'], ['/settings', '알림 설정']];

export function NewsletterApp() {
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
