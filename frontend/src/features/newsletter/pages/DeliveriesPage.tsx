import { useQuery } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Delivery } from '../types';
import { label, time } from '../format';
import { ErrorNotice, Status } from '../components/feedback';

export function DeliveriesPage() {
  const q = useQuery({ queryKey: ['deliveries'], queryFn: () => request<{ items: Delivery[] }>('/api/deliveries') });
  return <><h1>발송 이력</h1><p>부분 성공·결과 불명은 자동으로 재송신하지 않습니다.</p><ErrorNotice error={q.error} />{q.isPending ? <p role="status">발송 이력을 조회하고 있습니다.</p> : q.data && <section className="panel">{q.data.items.length ? <table><thead><tr><th>날짜</th><th>환경</th><th>상태</th><th>갱신</th></tr></thead><tbody>{q.data.items.map(x => <tr key={x.id}><td><a href={`#/deliveries/${encodeURIComponent(x.id)}`}>{x.target_date} · {x.slot}</a></td><td>{label(x.transport_mode)}</td><td><Status value={x.status} /></td><td>{time(x.updated_at)}</td></tr>)}</tbody></table> : <p>발송 기록이 없습니다. 전송 성공을 뜻하지 않습니다.</p>}</section>}</>;
}
