import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Session } from '../../../shared/session';
import type { Watchlist, Instrument } from '../types';
import { time } from '../format';
import { ErrorNotice } from '../components/feedback';

export function WatchlistPage({ session }: { session: Session }) {
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
  return <><h1>관심 종목</h1><p>지원 확인된 국내 상장 해외 ETF를 최대10개 활성화합니다.</p><ErrorNotice error={q.error || error} />{message && <p role="status">{message}</p>}{q.data && !q.error && <section className="panel"><h2>활성 {q.data.codes.length} / 10 · v{q.data.revision}</h2><div className="table-scroll"><table><thead><tr><th>순서</th><th>종목</th><th>표시 순서·활성</th></tr></thead><tbody>{q.data.items.map((item, i) => <tr key={item.code}><td>{i + 1}</td><td>{item.name} <small>{item.code} · {item.currency}</small></td><td><button className="button" aria-label={`${item.name} 위로`} disabled={blocked || i === 0} onClick={() => move(i, -1)}>↑</button> <button className="button" aria-label={`${item.name} 아래로`} disabled={blocked || i === q.data!.codes.length - 1} onClick={() => move(i, 1)}>↓</button> <button className="button" disabled={blocked || q.data!.codes.length <= 1} onClick={() => void save(q.data!.codes.filter(c => c !== item.code))}>비활성화</button></td></tr>)}</tbody></table></div></section>}
    <section className="panel"><h2>종목 검색·추가</h2><form onSubmit={e => { e.preventDefault(); setQuery(text.trim()); }}><label>종목명 또는 코드 <input value={text} maxLength={120} onChange={e => setText(e.target.value)} /></label> <button className="button" disabled={!text.trim()}>검색</button></form><ErrorNotice error={search.error} />{search.data && <>{!search.data.items.length && <p>검색 결과가 없습니다. 서버 종목 마스터 확인이 필요할 수 있습니다.</p>}{search.data.items.map(item => <article className="instrument-result" key={item.code}><strong>{item.name} · {item.code}</strong><p>{item.market} · {item.currency} · {item.eligible ? '지원 확인' : '지원 미확인'} · 정보 조회 {time(item.retrieved_at)}</p><button className="button" disabled={blocked || !item.eligible || q.data!.codes.includes(item.code) || q.data!.codes.length >= 10} onClick={() => void save([...q.data!.codes, item.code])}>{q.data?.codes.includes(item.code) ? '활성 종목' : '확인 후 추가'}</button></article>)}</>}</section></>;
}
