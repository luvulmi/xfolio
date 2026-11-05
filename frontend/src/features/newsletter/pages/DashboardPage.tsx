import { useQuery } from '@tanstack/react-query';
import { request } from '../../../shared/http';
import type { Budget, PriceFreshness, NewsCollection, Summary } from '../types';
import { label, time, money } from '../format';
import { ErrorNotice, Status } from '../components/feedback';
import { EditionTable } from '../components/EditionTable';

export function Dashboard() {
  const q = useQuery({ queryKey: ['newsletter-summary'], queryFn: () => request<Summary>('/api/newsletter-operations/summary'), refetchInterval: 60_000 });
  return <><div className="page-title"><div><h1>대시보드</h1><p>한국 거래일 07:50 준비 → 08:00 발송 · 08:10 마감</p><small>서버 확인 {time(q.data?.checked_at)}</small></div><button className="button" disabled={q.isFetching} onClick={() => q.refetch()}>최신 상태 확인</button></div><ErrorNotice error={q.error} />{q.isPending ? <p role="status">운영 상태를 조회하고 있습니다.</p> : q.data && !q.error && <><div className="summary-grid"><Card title="오늘 한국 시장" value={q.data.market_open === true ? '개장' : q.data.market_open === false ? '휴장 · 발송 없음' : '개장 여부 확인 대기'} /><Card title="발송 설정" value={q.data.settings.paused ? '전체 일시 중지' : q.data.settings.morning_enabled ? '아침 활성' : '아침 비활성'} /><Card title="활성 종목" value={`${q.data.watchlist.codes.length} / 10`} /><Card title="오늘 편성" value={`${q.data.newsletters.length}건`} /></div><BudgetPanel budget={q.data.budget} /><PricePanel prices={q.data.price_freshness} /><NewsPanel news={q.data.news_collection} /><DeliveryPanel summary={q.data} /><EditionTable items={q.data.newsletters} /></>}</>;
}

function BudgetPanel({ budget }: { budget?: Budget }) {
  return <section className="panel"><h2>이번 달 비용</h2><p><Status value={budget?.status ?? 'not_measured'} /> {budget?.month ?? ''}</p>{budget && <><div className="summary-grid"><Card title="원장 확정" value={money(budget.confirmed_krw)} /><Card title="예약" value={money(budget.reserved_krw)} /><Card title="추정" value={money(budget.estimated_krw)} /><Card title="월 예산" value={money(budget.limit_krw)} /></div><p>추정 포함 합계 {money(budget.committed_krw)} · 남은 예산 {money(budget.remaining_krw)} · 원장 {budget.record_count}건 · {budget.limit_source === 'server_configuration' ? '서버 설정 예산' : '정책 기본 예산'}</p></>}<p>기록된 비용 원장 범위입니다. 원장 기록 없음은 실비 0원을 뜻하지 않으며 서버·제공처 청구서 전체는 미대조입니다.</p></section>;
}

function PricePanel({ prices }: { prices?: PriceFreshness }) {
  return <section className="panel"><h2>시세 신선도</h2><p><Status value={prices?.status ?? 'not_observed'} /> {prices?.provenance && <> · {label(prices.provenance)}</>}</p>{prices?.expected_trade_date && <p>기준 거래일 {prices.expected_trade_date} · 비교 거래일 {prices.comparison_trade_date} · 판정 시각 {time(prices.reference_at)} · 최근 수집 {time(prices.finished_at)}</p>}{prices?.reason && <p>확인 사유: {prices.reason}</p>}{!!prices?.items.length && <div className="table-scroll"><table><thead><tr><th>종목/상태</th><th>거래일/버전</th><th>가격 기준시각</th><th>예정 마감/조회</th></tr></thead><tbody>{prices.items.map(p => <tr key={p.code}><td>{p.code}<br /><Status value={p.status} /></td><td>{p.trade_date ?? '확인 불가'}{p.version != null && <> · v{p.version}</>}{p.change_available === false && <small> · 등락률 보류</small>}</td><td>{p.price_as_of ? time(p.price_as_of) : '미제공'}<small> · 제공 지연 미측정</small></td><td>{time(p.scheduled_close)}<br />{time(p.retrieved_at)}</td></tr>)}</tbody></table></div>}<p>최근 완료 한국 거래일을 대조합니다. 조회시각을 실제 체결시각으로 대체하지 않으며 합성·미확인 자료는 실자료 정상으로 표시하지 않습니다.</p></section>;
}

function NewsPanel({ news }: { news?: NewsCollection }) {
  return <section className="panel"><h2>뉴스 수집</h2><p><Status value={news?.status ?? 'not_observed'} />{news?.as_of && <> · {news.current ? '오늘 아침 수집' : '이전 수집 기록'} · 기준 {time(news.as_of)} · 완료 {time(news.finished_at)}</>}</p>{news?.as_of && <><p>{news.synthetic || news.provenance === 'synthetic' ? '합성 시험 자료' : label(news.provenance ?? 'unverified')} · {news.normal_zero ? '정상 0건 · 적격 뉴스 없음' : `선정 ${news.selected_count}건`}{news.retained_selected_count !== news.selected_count && ' · 일부 선정 자료 보존 만료/누락'}</p><ul>{news.sources.map(source => <li key={source.provider}>{source.provider} · {label(source.status)} {source.errors.join(', ')}</li>)}</ul></>}<p>정상 0건과 수집 실패를 구분합니다. 뉴스는 일반·공식 합계 최대 3건입니다.</p></section>;
}

function DeliveryPanel({ summary }: { summary: Summary }) {
  return <section className="panel"><h2>최근 발송·장애</h2>{summary.worker?.recorded_at && <p>{summary.worker.stage === 'preparation' ? '준비·수집' : '발송 worker'} {summary.worker.status === 'running' ? '진행 중' : label(summary.worker.status)}{summary.worker.reason && <> · {summary.worker.reason}</>} · {time(summary.worker.recorded_at)}</p>}{summary.deliveries?.attention.length ? <p role="status">최근 10건 중 확인이 필요한 발송 {summary.deliveries.attention.length}건</p> : <p>최근 기록에서 실패·부분 성공·불명 여부를 확인합니다.</p>}{summary.deliveries?.recent.length ? <ul>{summary.deliveries.recent.map(d => <li key={d.id}><a href={`#/deliveries/${encodeURIComponent(d.id)}`}>{d.target_date} · {d.slot}</a> · {d.transport_mode === 'live' ? '실제 송신' : '모의 송신'} · <Status value={d.status} /> · {time(d.updated_at)}</li>)}</ul> : <p>발송 관측 기록 없음 · 전송 성공을 뜻하지 않습니다.</p>}<p>편성 준비와 전송 성공을 구분합니다. <a href="#/deliveries">발송 이력 확인</a></p></section>;
}

function Card({ title, value }: { title: string; value: string }) { return <article className="summary-card"><span>{title}</span><strong>{value}</strong></article>; }
