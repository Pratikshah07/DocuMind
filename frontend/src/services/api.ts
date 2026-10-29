/**
 * DocuMind API: typed contracts mirroring the FastAPI schemas (backend/app/schemas)
 * and the calls the UI makes. This module is the single integration seam; pages
 * use these functions through TanStack Query.
 */
import { apiBlob, apiJson } from '@/lib/api-client';

// --- Enums ------------------------------------------------------------------------

export type DocumentStatus =
  | 'UPLOADED'
  | 'PROCESSING'
  | 'OCR'
  | 'EXTRACTING'
  | 'VALIDATING'
  | 'COMPLETED'
  | 'NEEDS_REVIEW'
  | 'FAILED';
export type DocumentType = 'INVOICE' | 'RECEIPT' | 'UNKNOWN';
export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
export type FieldStatus = 'ok' | 'uncertain' | 'invalid' | 'missing';
export type Severity = 'INFO' | 'WARNING' | 'ERROR';

export const IN_PROGRESS: DocumentStatus[] = ['UPLOADED', 'PROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'];
export const isInProgress = (status: DocumentStatus) => IN_PROGRESS.includes(status);
export const isProcessed = (status: DocumentStatus) => status === 'COMPLETED' || status === 'NEEDS_REVIEW';

// --- Documents --------------------------------------------------------------------

export type DocumentSummary = {
  id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  document_type: DocumentType | null;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  total: number | null;
  category: string | null;
  overall_confidence: number | null;
  created_at: string;
  updated_at: string;
};

export type DocumentPage = {
  page_number: number;
  text: string | null;
  text_source: 'EMBEDDED' | 'OCR' | null;
  ocr_confidence: number | null;
  width: number | null;
  height: number | null;
  has_preview: boolean;
};

export type DocumentDetail = DocumentSummary & {
  due_date: string | null;
  subtotal: number | null;
  tax: number | null;
  discount: number | null;
  payment_method: string | null;
  error_message: string | null;
  processed_at: string | null;
  pages: DocumentPage[];
};

export type DocumentList = { items: DocumentSummary[]; total: number; limit: number; offset: number };
export type DocumentSort = 'newest' | 'oldest' | 'amount_desc' | 'amount_asc' | 'vendor';
export type DocumentFilters = {
  q?: string;
  status?: DocumentStatus[];
  document_type?: DocumentType;
  date_from?: string;
  date_to?: string;
  sort?: DocumentSort;
  limit?: number;
  offset?: number;
};

export type UploadResponse = {
  id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
  job_id: string;
};

export type ProcessingJob = {
  id: string;
  status: JobStatus;
  stage: DocumentStatus | null;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  /** Whether retrying the same file can help; null when the job did not fail. */
  retryable: boolean | null;
  created_at: string;
};

export type DocumentStatusResponse = {
  document_id: string;
  status: DocumentStatus;
  page_count: number | null;
  error_message: string | null;
  processed_at: string | null;
  job: ProcessingJob | null;
};

// --- Extraction -------------------------------------------------------------------

export type ExtractedField = {
  name: string;
  status: FieldStatus;
  value: string | null;
  normalized_value: string | number | null;
  confidence: number | null;
  effective_confidence: number | null;
  confidence_level: 'high' | 'medium' | 'low' | null;
  method: string | null;
  page_number: number | null;
  required: boolean;
  is_user_edited: boolean;
};

export type LineItem = {
  position: number;
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  total: number | null;
  confidence: number | null;
  page_number: number | null;
};

export type ValidationWarning = { field: string | null; code: string; message: string; severity: Severity };

export type Extraction = {
  document_id: string;
  status: DocumentStatus;
  document_type: DocumentType;
  document_type_confidence: number | null;
  document_type_user_edited: boolean;
  overall_confidence: number;
  needs_review: boolean;
  line_items_user_edited: boolean;
  fields: ExtractedField[];
  line_items: LineItem[];
  warnings: ValidationWarning[];
};

export type ExtractionEdit = {
  kind: 'edit' | 'reset';
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  created_at: string;
};

export type LineItemInput = {
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  total: number | null;
};

export type ExtractionUpdate = {
  fields?: Record<string, string | null>;
  document_type?: DocumentType;
  line_items?: LineItemInput[];
};

// --- Analytics, health, meta ------------------------------------------------------

export type CurrencyTotal = { currency: string | null; total: number; document_count: number; average: number };
export type AnalyticsOverview = {
  total_documents: number;
  processed: number;
  in_progress: number;
  needs_review: number;
  failed: number;
  status_counts: Record<string, number>;
  type_counts: Record<string, number>;
  spend: CurrencyTotal[];
  processed_without_total: number;
  spend_includes_needs_review: number;
};
export type MonthTotal = { month: string; currency: string | null; total: number; document_count: number };
export type Spending = { months: MonthTotal[]; processed_without_date: number };
export type VendorTotal = { vendor: string; currency: string | null; total: number; document_count: number };

export type Health = {
  status: 'ok' | 'degraded';
  version: string;
  environment: string;
  components: Record<string, { status: 'ok' | 'error' | 'disabled'; detail: string | null }>;
};

export type Meta = {
  version: string;
  demo_mode: boolean;
  retention_hours: number;
  max_upload_bytes: number;
  max_pages: number;
  max_documents_per_workspace: number;
  upload_rate_limit_per_hour: number;
  accepted_types: string[];
  date_order: string;
};

// --- Calls ------------------------------------------------------------------------

export const api = {
  health: () => apiJson<Health>('/health', { timeoutMs: 10_000 }),
  meta: () => apiJson<Meta>('/meta'),

  listDocuments: (filters: DocumentFilters = {}) => apiJson<DocumentList>('/documents', { query: filters }),
  getDocument: (id: string) => apiJson<DocumentDetail>(`/documents/${id}`),
  getStatus: (id: string) => apiJson<DocumentStatusResponse>(`/documents/${id}/status`),
  upload: (file: File, options: { allowDuplicate?: boolean } = {}) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return apiJson<UploadResponse>('/documents/upload', {
      method: 'POST',
      body: form,
      timeoutMs: 120_000,
      query: { allow_duplicate: options.allowDuplicate ? 'true' : undefined },
    });
  },
  reprocess: (id: string, options: { discardCorrections?: boolean } = {}) =>
    apiJson<DocumentStatusResponse>(`/documents/${id}/process`, {
      method: 'POST',
      query: { discard_corrections: options.discardCorrections ? 'true' : undefined },
    }),
  deleteDocument: (id: string) => apiJson<void>(`/documents/${id}`, { method: 'DELETE' }),
  deleteAllDocuments: () => apiJson<{ deleted: number }>('/documents', { method: 'DELETE' }),
  downloadOriginal: (id: string) => apiBlob(`/documents/${id}/file`, { timeoutMs: 120_000 }),
  pagePreview: (id: string, page: number) => apiBlob(`/documents/${id}/pages/${page}/preview`),

  getExtraction: (id: string) => apiJson<Extraction>(`/documents/${id}/extraction`),
  updateExtraction: (id: string, update: ExtractionUpdate) =>
    apiJson<Extraction>(`/documents/${id}/extraction`, { method: 'PATCH', json: update }),
  getEdits: (id: string) => apiJson<{ document_id: string; edits: ExtractionEdit[] }>(`/documents/${id}/edits`),

  analyticsOverview: () => apiJson<AnalyticsOverview>('/analytics/overview'),
  analyticsSpending: () => apiJson<Spending>('/analytics/spending'),
  analyticsVendors: () => apiJson<{ vendors: VendorTotal[] }>('/analytics/vendors'),
};

/** TanStack Query keys. Invalidate `['documents']` / `['analytics']` prefixes after mutations. */
export const queryKeys = {
  health: ['health'] as const,
  meta: ['meta'] as const,
  documents: (filters: DocumentFilters = {}) => ['documents', 'list', filters] as const,
  document: (id: string) => ['documents', 'detail', id] as const,
  status: (id: string) => ['documents', 'status', id] as const,
  extraction: (id: string) => ['documents', 'extraction', id] as const,
  edits: (id: string) => ['documents', 'edits', id] as const,
  analytics: (part: 'overview' | 'spending' | 'vendors') => ['analytics', part] as const,
};
