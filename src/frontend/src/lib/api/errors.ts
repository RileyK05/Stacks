export type ApiErrorKind =
  | 'unauthorized'
  | 'budget'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'too_large'
  | 'unsupported_media'
  | 'validation'
  | 'unavailable'
  | 'network'
  | 'unknown';

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;

  constructor(status: number, message: string, kind?: ApiErrorKind) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind ?? kindForStatus(status, message);
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    const detail = await parseDetail(response);
    return new ApiError(response.status, detail);
  }

  static fromNetworkError(cause: unknown): ApiError {
    const message = cause instanceof Error ? cause.message : 'request failed';
    return new ApiError(0, `cannot reach the server: ${message}`, 'network');
  }
}

function kindForStatus(status: number, _message: string): ApiErrorKind {
  if (status === 401) return 'unauthorized';
  if (status === 402) return 'budget';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 413) return 'too_large';
  if (status === 415) return 'unsupported_media';
  if (status === 422) return 'validation';
  if (status === 503) return 'unavailable';
  return 'unknown';
}

function detailText(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => detailText(item))
      .filter((part): part is string => part !== null);
    return parts.length > 0 ? parts.join('; ') : null;
  }
  if (typeof detail === 'object' && detail !== null) {
    const record = detail as Record<string, unknown>;
    for (const key of ['msg', 'message', 'detail', 'error']) {
      const text = detailText(record[key]);
      if (text) return text;
    }
  }
  return null;
}

async function parseDetail(response: Response): Promise<string> {
  try {
    const raw = await response.text();
    try {
      const body: unknown = JSON.parse(raw);
      const text = detailText(body);
      if (text) return text;
    } catch {
      // Not JSON: a proxy or crash page. Show a short plain-text body.
      const plain = raw.trim();
      if (plain && plain.length <= 300 && !plain.startsWith('<')) return plain;
    }
  } catch {
    // fall through to the generic message
  }
  return `request failed with status ${response.status}`;
}
