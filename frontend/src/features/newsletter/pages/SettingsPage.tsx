import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Session } from '../../../shared/session';
import type { Settings } from '../types';
import { ErrorNotice } from '../components/feedback';

export function SettingsPage({ session }: { session: Session }) {
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
