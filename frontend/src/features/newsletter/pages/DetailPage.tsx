import { useQuery } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Delivery, Edition } from '../types';
import { label, time } from '../format';
import { ErrorNotice, Status } from '../components/feedback';

export function Detail({ kind, id }: { kind: string; id: string }) {
  const q = useQuery({ queryKey: [kind, id], queryFn: () => request<Edition & Delivery>(`/api/${kind}/${id}`) });
  return <><a href={`#/${kind}`}>← 목록</a><h1>{kind === 'newsletters' ? '뉴스레터 상세' : '발송 상세'}</h1><ErrorNotice error={q.error} />{q.data && !q.error && <section className="panel"><h2>{q.data.target_date} · {q.data.slot}</h2><Status value={q.data.status} /><p>{q.data.synthetic ? '합성 시험 자료' : label(q.data.transport_mode ?? q.data.mode)}</p><p>생성 {time(q.data.created_at)} · 갱신 {time(q.data.updated_at)} · 보존 만료 {time(q.data.expires_at)}</p>{q.data.settings && <p>종목 v{q.data.watchlist_revision} · 설정 v{q.data.settings.revision}</p>}{q.data.edition_id && <a href={`#/newsletters/${q.data.edition_id}`}>원본 뉴스레터 확인</a>}<pre className="newsletter-body">{q.data.body}</pre>{q.data.reasons?.length > 0 && <p>검사·제외 사유: {q.data.reasons.join(', ')}</p>}{q.data.parts?.map((part, i) => <p key={part.position ?? i}>조각 {part.position ?? i + 1} · {label(part.status ?? 'unknown')} · 시도 {part.attempt_count ?? '확인 대기'} · message_id {part.message_id ?? '없음'} {part.error_code ?? ''}</p>)}<p>실제 전송은 응답 기록으로 확인하며 보존기한이 지난 본문은 제공하지 않습니다.</p></section>}</>;
}
