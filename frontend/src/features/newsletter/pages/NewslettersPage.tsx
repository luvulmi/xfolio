import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Edition } from '../types';
import { label } from '../format';
import { ErrorNotice } from '../components/feedback';
import { EditionTable } from '../components/EditionTable';

export function EditionsPage() {
  const [day, setDay] = useState(''); const [status, setStatus] = useState(''); const params = new URLSearchParams(); if (day) params.set('date', day); if (status) params.set('status', status);
  const q = useQuery({ queryKey: ['newsletters', day, status], queryFn: () => request<{ items: Edition[] }>(`/api/newsletters?${params}`) });
  return <><h1>뉴스레터</h1><div className="filters"><label>날짜 <input type="date" value={day} onChange={e => setDay(e.target.value)} /></label><label>상태 <select value={status} onChange={e => setStatus(e.target.value)}><option value="">전체</option>{['ready', 'partial', 'failed', 'skipped'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label></div><ErrorNotice error={q.error} />{q.isPending ? <p role="status">뉴스레터를 조회하고 있습니다.</p> : q.data && <EditionTable items={q.data.items} />}</>;
}
