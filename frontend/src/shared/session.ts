export interface Session { operator: string | { email?: string; display_name?: string }; mode: string; csrf_token: string; }
