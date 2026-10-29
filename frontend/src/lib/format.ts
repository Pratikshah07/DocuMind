import type { DocumentStatus, DocumentType } from '@/services/api';

/** Money with its own currency; without a known currency, a plain number (never a guessed symbol). */
export function formatMoney(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined) return '—';
  if (currency) {
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(amount);
    } catch {
      /* unknown ISO code: fall through */
    }
  }
  const plain = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount);
  return currency ? `${currency} ${plain}` : plain;
}

export function formatDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }): string {
  if (!iso) return '—';
  const date = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, opts);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatPercent(score: number | null | undefined): string {
  return score === null || score === undefined ? '—' : `${Math.round(score * 100)}%`;
}

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  UPLOADED: 'Queued',
  PROCESSING: 'Reading document',
  OCR: 'Running OCR',
  EXTRACTING: 'Extracting fields',
  VALIDATING: 'Validating',
  COMPLETED: 'Ready',
  NEEDS_REVIEW: 'Review needed',
  FAILED: 'Failed',
};

/** Real pipeline stages in order (OCR only happens for scanned pages/images). */
export const STAGES: DocumentStatus[] = ['UPLOADED', 'PROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'];

export const TYPE_LABEL: Record<DocumentType, string> = { INVOICE: 'Invoice', RECEIPT: 'Receipt', UNKNOWN: 'Unknown' };

export const FIELD_LABEL: Record<string, string> = {
  vendor_name: 'Vendor',
  invoice_number: 'Invoice / receipt number',
  invoice_date: 'Date',
  due_date: 'Due date',
  currency: 'Currency',
  subtotal: 'Subtotal',
  tax: 'Tax',
  discount: 'Discount',
  total: 'Total',
  payment_method: 'Payment method',
  billing_address: 'Billing address',
  shipping_address: 'Shipping address',
};

export const DATE_FIELDS = new Set(['invoice_date', 'due_date']);
export const AMOUNT_FIELDS = new Set(['subtotal', 'tax', 'discount', 'total']);

export const METHOD_LABEL: Record<string, string> = {
  regex: 'Found next to a label',
  pattern: 'Inferred from layout',
  user: 'Edited by you',
  rule: 'Rule-based classifier',
};
