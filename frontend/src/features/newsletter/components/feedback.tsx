import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../../shared/http';
import { label } from '../format';

export function ErrorNotice({ error }: { error: unknown }) {
  const client = useQueryClient();
  useEffect(() => { if (error instanceof ApiError && error.status === 401) void client.invalidateQueries({ queryKey: ['session'] }); }, [error, client]);
  if (!error) return null;
  const value = error as ApiError;
  return <div className="notice" role="alert">{value.code === 'DELIVERIES_NOT_CONNECTED' ? '발송 이력은 자동 전송 기능 연결 후 확인할 수 있습니다.' : `${value.message || '조회에 실패했습니다.'} ${value.code ? `(${value.code})` : ''}`}</div>;
}

export function Status({ value }: { value: string }) { return <span className={`badge ${value}`}>{label(value)}</span>; }
