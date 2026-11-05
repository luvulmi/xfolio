import type { Edition } from '../types';
import { label } from '../format';
import { Status } from './feedback';

export function EditionTable({ items }: { items: Edition[] }) { return <section className="panel"><h2>뉴스레터</h2>{items.length ? <table><thead><tr><th>날짜/슬롯</th><th>상태</th><th>자료</th><th>환경</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><a href={`#/newsletters/${encodeURIComponent(item.id)}`}>{item.target_date} · {item.slot}</a></td><td><Status value={item.status} /></td><td>가격 {item.price_count} · 뉴스 {item.news_count}</td><td>{item.synthetic ? '합성 시험' : label(item.mode)}</td></tr>)}</tbody></table> : <p>표시할 뉴스레터가 없습니다. 수집·발송 성공을 뜻하지 않습니다.</p>}</section>; }
