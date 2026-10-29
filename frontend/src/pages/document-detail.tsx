import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle, ArrowLeft, Check, ChevronLeft, ChevronRight, CircleAlert, Download, FileJson2, FileText, Info,
  LoaderCircle, Plus, RotateCcw, Trash2, X, ZoomIn, ZoomOut,
} from 'lucide-react';
import { Link, useLocation, useParams } from 'wouter';
import { EmptyState, ErrorState, FieldStatusBadge, StatusBadge } from '@/components/documind';
import { ApiError, errorMessage } from '@/lib/api-client';
import {
  AMOUNT_FIELDS, DATE_FIELDS, FIELD_LABEL, formatBytes, formatDate, formatMoney, formatPercent, METHOD_LABEL, STATUS_LABEL, TYPE_LABEL,
} from '@/lib/format';
import { buttonBase, notify, saveBlob } from '@/lib/ui';
import {
  api, isInProgress, isProcessed, queryKeys, type DocumentType, type Extraction, type ExtractionUpdate, type LineItemInput,
} from '@/services/api';

type Row = { key: string; description: string; quantity: string; unit_price: string; total: string; confidence: number | null };
const toText = (n: number | null) => (n === null || n === undefined ? '' : String(n));
const rowsFrom = (data: Extraction): Row[] =>
  data.line_items.map((i) => ({ key: `srv-${i.position}`, description: i.description ?? '', quantity: toText(i.quantity), unit_price: toText(i.unit_price), total: toText(i.total), confidence: i.confidence }));
const num = (s: string) => (s.trim() === '' ? null : Number(s));

/** Show "Read as …" only when the reading isn't obvious from the raw text (EU decimals, OCR noise, signs, non-ISO dates). */
export function readingDiffers(name: string, raw: string | null, normalized: string | number | null): boolean {
  if (raw === null || normalized === null) return false;
  if (AMOUNT_FIELDS.has(name)) {
    const plain = raw.replace(/[,\s$€£₹¥']|[A-Z]{3}/g, '');
    return Number.isNaN(Number(plain)) || Number(plain) !== Number(normalized) || plain.startsWith('-');
  }
  return String(normalized).toLowerCase() !== raw.toLowerCase();
}

function Button({ children, onClick, variant = 'primary', disabled, testid, className = '' }: { children: ReactNode; onClick?: () => void; variant?: 'primary' | 'outline' | 'ghost' | 'danger'; disabled?: boolean; testid?: string; className?: string }) {
  const style = variant === 'primary' ? 'bg-primary text-primary-foreground hover:bg-primary/90' : variant === 'outline' ? 'border border-border bg-card text-foreground hover:bg-muted' : variant === 'danger' ? 'bg-red-700 text-white hover:bg-red-800' : 'text-muted-foreground hover:bg-muted hover:text-foreground';
  return <button type="button" onClick={onClick} disabled={disabled} data-testid={testid} className={`${buttonBase} ${style} ${className}`}>{children}</button>;
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-foreground/35 p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="modal-title" className="w-full max-w-md rounded-md border border-border bg-card p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3"><h2 id="modal-title" className="text-base font-semibold">{title}</h2><button onClick={onClose} className="grid h-7 w-7 place-items-center rounded-sm text-muted-foreground hover:bg-muted" aria-label="Close dialog" data-testid="button-close-dialog"><X size={16} /></button></div>
        <div className="mt-3">{children}</div>
      </section>
    </div>
  );
}

function PagePreview({ documentId, page, zoom }: { documentId: string; page: number; zoom: number }) {
  const preview = useQuery({
    queryKey: ['documents', 'preview', documentId, page],
    queryFn: () => api.pagePreview(documentId, page).then((r) => r.blob),
    staleTime: Infinity,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!preview.data) return;
    const objectUrl = URL.createObjectURL(preview.data);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [preview.data]);
  if (preview.isError) return <p className="text-xs text-muted-foreground">Preview not available for this page.</p>;
  if (!url) return <div className="h-[520px] w-full max-w-[460px] animate-pulse rounded-sm bg-card" />;
  return <img src={url} alt={`Page ${page}`} className="w-full max-w-[560px] origin-top bg-white shadow-[0_4px_18px_rgba(35,45,43,.12)] transition-transform" style={{ transform: `scale(${zoom / 100})` }} data-testid="img-page-preview" />;
}

export default function DocumentDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [values, setValues] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Row[]>([]);
  const [docType, setDocType] = useState<DocumentType | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'delete' | 'reprocess' | null>(null);

  const detail = useQuery({
    queryKey: queryKeys.document(id),
    queryFn: () => api.getDocument(id),
    refetchInterval: (q) => (q.state.data && isInProgress(q.state.data.status) ? 2000 : false),
  });
  const doc = detail.data;
  const ready = Boolean(doc && isProcessed(doc.status));
  const extraction = useQuery({ queryKey: queryKeys.extraction(id), queryFn: () => api.getExtraction(id), enabled: ready });
  const data = extraction.data;

  const serverValues = useMemo(() => Object.fromEntries((data?.fields ?? []).map((f) => [f.name, f.value ?? ''])), [data]);
  const serverRows = useMemo(() => (data ? rowsFrom(data) : []), [data]);
  // Reset the form whenever fresh server data arrives (initial load, save, reprocess).
  useEffect(() => {
    if (!data) return;
    setValues(serverValues);
    setRows(serverRows);
    setDocType(data.document_type);
    setFieldErrors({});
    setFormError(null);
  }, [data, serverValues, serverRows]);

  const changedFields = Object.keys(values).filter((name) => values[name] !== serverValues[name]);
  const rowsChanged = JSON.stringify(rows.map(({ key, confidence, ...r }) => r)) !== JSON.stringify(serverRows.map(({ key, confidence, ...r }) => r));
  const typeChanged = Boolean(data && docType && docType !== data.document_type);
  const dirty = changedFields.length > 0 || rowsChanged || typeChanged;
  const editedCount = (data?.fields ?? []).filter((f) => f.is_user_edited).length + (data?.document_type_user_edited ? 1 : 0);

  const invalidateLists = () => {
    void queryClient.invalidateQueries({ queryKey: ['documents', 'list'] });
    void queryClient.invalidateQueries({ queryKey: ['analytics'] });
  };

  const save = useMutation({
    mutationFn: () => {
      const update: ExtractionUpdate = {};
      if (changedFields.length) update.fields = Object.fromEntries(changedFields.map((n) => [n, values[n].trim() === '' ? null : values[n]]));
      if (typeChanged && docType) update.document_type = docType;
      if (rowsChanged) {
        const items: LineItemInput[] = rows.map((r) => ({ description: r.description.trim() || null, quantity: num(r.quantity), unit_price: num(r.unit_price), total: num(r.total) }));
        if (items.some((i) => [i.quantity, i.unit_price, i.total].some((v) => v !== null && (Number.isNaN(v) || v < 0)))) {
          throw new ApiError(422, 'validation_failed', 'Line item numbers must be non-negative numbers.');
        }
        update.line_items = items;
      }
      return api.updateExtraction(id, update);
    },
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.extraction(id), result);
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(id) });
      invalidateLists();
      notify(result.needs_review ? 'Saved. Some values still need review.' : 'Saved. The document is ready.');
    },
    onError: (error) => {
      // Keep the user's input; show what the server rejected.
      const errors: Record<string, string> = {};
      if (error instanceof ApiError && Array.isArray(error.details)) {
        for (const d of error.details as { field?: string; loc?: (string | number)[]; message?: string; msg?: string }[]) {
          const field = d.field ?? (d.loc ? String(d.loc[d.loc.length - 1]) : undefined);
          if (field) errors[field] = d.message ?? d.msg ?? 'Invalid value.';
        }
      }
      setFieldErrors(errors);
      setFormError(error instanceof ApiError && error.status === 409 ? 'This document is being processed; try again when it has finished.' : errorMessage(error));
    },
  });

  const reprocess = useMutation({
    mutationFn: () => api.reprocess(id),
    onSuccess: () => {
      setConfirm(null);
      queryClient.removeQueries({ queryKey: queryKeys.extraction(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(id) });
      invalidateLists();
      notify('Reprocessing started.', 'info');
    },
    onError: (error) => notify(errorMessage(error), 'error'),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteDocument(id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.document(id) });
      invalidateLists();
      notify('Document deleted.');
      setLocation('/app/documents');
    },
    onError: (error) => notify(errorMessage(error), 'error'),
  });

  const download = async () => {
    try {
      const { blob, filename } = await api.downloadOriginal(id);
      saveBlob(blob, filename ?? doc?.original_filename ?? 'document');
    } catch (error) {
      notify(errorMessage(error), 'error');
    }
  };
  const exportJson = () => {
    if (!data || !doc) return;
    saveBlob(new Blob([JSON.stringify({ document: { id: doc.id, filename: doc.original_filename, status: data.status }, ...data }, null, 2)], { type: 'application/json' }), `${doc.original_filename.replace(/\.[^.]+$/, '')}-extraction.json`);
  };

  if (detail.isLoading) return <div className="page-enter"><div className="mb-6 h-8 w-64 animate-pulse rounded bg-muted" /><div className="grid gap-5 lg:grid-cols-2"><div className="h-[540px] animate-pulse rounded-md bg-muted" /><div className="h-[540px] animate-pulse rounded-md bg-muted" /></div></div>;
  if (detail.isError || !doc) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return <div className="page-enter"><EmptyState title={notFound ? 'Document not found' : 'Could not load this document'} body={notFound ? 'It may have been deleted, or it belongs to another browser’s workspace.' : errorMessage(detail.error)} action={<Link href="/app/documents" className={`${buttonBase} bg-primary text-primary-foreground`}>Back to documents</Link>} /></div>;
  }

  const pageCount = doc.page_count ?? doc.pages.length;
  const hasPreview = doc.pages.some((p) => p.has_preview);
  const warnings = data?.warnings ?? [];
  const fieldWarnings = (name: string) => warnings.filter((w) => w.field === name);
  const lineItemsTotal = rows.reduce((sum, r) => sum + (num(r.total) ?? 0), 0);
  const currency = data?.fields.find((f) => f.name === 'currency')?.normalized_value as string | null | undefined;

  return (
    <div className="page-enter">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <Link href="/app/documents" className="inline-flex items-center gap-2 text-xs font-semibold text-muted-foreground hover:text-primary" data-testid="link-back-documents"><ArrowLeft size={15} />All documents</Link>
        <div className="flex flex-wrap items-center gap-2">
          {ready && <span className="hidden text-[10px] text-muted-foreground sm:inline" data-testid="text-save-state">{dirty ? 'Unsaved changes' : 'All changes saved'}</span>}
          {ready && <Button variant="outline" onClick={exportJson} testid="button-export-json"><FileJson2 size={15} /><span className="hidden sm:inline">Export JSON</span></Button>}
          <Button variant="outline" onClick={() => void download()} testid="button-download-document"><Download size={15} /><span className="hidden sm:inline">Original</span></Button>
          {!isInProgress(doc.status) && <Button variant="outline" onClick={() => setConfirm('reprocess')} testid="button-reprocess"><RotateCcw size={15} /><span className="hidden sm:inline">Reprocess</span></Button>}
          {ready && <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending} testid="button-save-document">{save.isPending ? <LoaderCircle className="animate-spin" size={15} /> : <Check size={15} />}Save</Button>}
          <Button variant="ghost" className="h-9 w-9 px-0" onClick={() => setConfirm('delete')} testid="button-delete-document"><Trash2 size={16} /><span className="sr-only">Delete document</span></Button>
        </div>
      </div>

      <div className="mb-5">
        <h1 className="max-w-3xl truncate text-xl font-semibold tracking-tight sm:text-2xl" data-testid="heading-page">{doc.vendor_name ?? doc.original_filename}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
          <span>{doc.original_filename}</span><span>·</span><span>{formatBytes(doc.size_bytes)}</span><span>·</span><span>uploaded {formatDate(doc.created_at)}</span>
          {doc.document_type && <><span>·</span><span>{TYPE_LABEL[doc.document_type]}</span></>}
          <span className="ml-1"><StatusBadge status={doc.status} /></span>
        </p>
      </div>

      {isInProgress(doc.status) && (
        <div className="mb-5 flex items-center gap-3 rounded-md border border-border bg-card p-4 text-sm" data-testid="banner-processing">
          <LoaderCircle size={18} className="animate-spin text-primary" />
          <div><div className="font-semibold">{STATUS_LABEL[doc.status]}…</div><div className="text-xs text-muted-foreground">This page updates automatically when processing finishes.</div></div>
        </div>
      )}
      {doc.status === 'FAILED' && (
        <div className="mb-5 flex flex-col gap-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200 sm:flex-row sm:items-center sm:justify-between" data-testid="banner-failed">
          <span className="flex items-start gap-2"><AlertTriangle size={17} className="mt-0.5 shrink-0" /><span><b>Processing failed.</b> {doc.error_message}</span></span>
          <Button variant="outline" onClick={() => reprocess.mutate()} disabled={reprocess.isPending} testid="button-retry-processing"><RotateCcw size={14} />Retry</Button>
        </div>
      )}
      {data?.needs_review && (
        <div className="mb-5 rounded-md border border-[#e7d9b8] bg-[#fbf6ea] p-4 text-sm dark:border-[#4a3d22] dark:bg-[#2b2416]" data-testid="banner-review">
          <div className="flex items-center gap-2 font-semibold text-[#7d5d27] dark:text-[#e2bd7a]"><CircleAlert size={16} />Review needed</div>
          {warnings.length > 0 ? (
            <ul className="mt-2 space-y-1 text-xs leading-5 text-[#6f5426] dark:text-[#d9c28f]">{warnings.filter((w) => w.severity !== 'INFO').map((w, i) => <li key={i} data-testid={`warning-${w.code}`}>• {w.message}</li>)}</ul>
          ) : <p className="mt-1 text-xs text-[#6f5426] dark:text-[#d9c28f]">Some required values have low confidence. Check them against the document.</p>}
        </div>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,.95fr)]">
        <section className="overflow-hidden rounded-md border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2 text-xs font-semibold"><FileText size={15} className="text-primary" />Document preview</div>
            <div className="flex items-center gap-1">
              <button className="grid h-7 w-7 place-items-center rounded-sm text-muted-foreground hover:bg-muted" onClick={() => setZoom((z) => Math.max(60, z - 10))} aria-label="Zoom out" data-testid="button-zoom-out"><ZoomOut size={15} /></button>
              <span className="w-10 text-center font-mono text-[10px]">{zoom}%</span>
              <button className="grid h-7 w-7 place-items-center rounded-sm text-muted-foreground hover:bg-muted" onClick={() => setZoom((z) => Math.min(160, z + 10))} aria-label="Zoom in" data-testid="button-zoom-in"><ZoomIn size={15} /></button>
            </div>
          </div>
          <div className="subtle-grid flex min-h-[540px] justify-center overflow-auto bg-[#eeefeb] p-6 dark:bg-muted/30">
            {hasPreview ? <PagePreview documentId={id} page={page} zoom={zoom} /> : (
              <p className="self-center text-center text-xs text-muted-foreground">{isInProgress(doc.status) ? 'The preview appears when processing finishes.' : 'No preview is available. Download the original instead.'}</p>
            )}
          </div>
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-[10px] text-muted-foreground">
            <span>{pageCount ? `${pageCount} page${pageCount === 1 ? '' : 's'}` : '—'}{doc.pages[page - 1]?.text_source ? ` · page text from ${doc.pages[page - 1].text_source === 'OCR' ? `OCR (${formatPercent(doc.pages[page - 1].ocr_confidence)} engine confidence)` : 'the PDF text layer'}` : ''}</span>
            {pageCount > 1 && (
              <div className="flex items-center gap-2">
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="grid h-6 w-6 place-items-center rounded-sm hover:bg-muted disabled:opacity-40" aria-label="Previous page" data-testid="button-page-previous"><ChevronLeft size={14} /></button>
                <span>{page} / {pageCount}</span>
                <button onClick={() => setPage((p) => Math.min(pageCount, p + 1))} disabled={page >= pageCount} className="grid h-6 w-6 place-items-center rounded-sm hover:bg-muted disabled:opacity-40" aria-label="Next page" data-testid="button-page-next"><ChevronRight size={14} /></button>
              </div>
            )}
          </div>
        </section>

        <div className="space-y-5">
          {!ready ? (
            <section className="rounded-md border border-border bg-card p-6 text-center text-xs text-muted-foreground">
              {doc.status === 'FAILED' ? 'No data could be extracted. Retry processing or upload a clearer file.' : 'Extracted fields will appear here when processing finishes.'}
            </section>
          ) : extraction.isLoading ? (
            <section className="h-[420px] animate-pulse rounded-md bg-muted" />
          ) : extraction.isError || !data ? (
            <ErrorState message={errorMessage(extraction.error)} onRetry={() => void extraction.refetch()} />
          ) : (
            <>
              {formError && <ErrorState message={formError} testid="status-save-error" />}
              <section className="rounded-md border border-border bg-card">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3.5">
                  <div><h2 className="text-sm font-semibold">Extracted fields</h2><p className="mt-1 text-[10px] text-muted-foreground">Edit any value, then save. Required fields are marked *.</p></div>
                  <label className="flex items-center gap-2 text-[10px] text-muted-foreground">Type
                    <select value={docType ?? ''} onChange={(e) => setDocType(e.target.value as DocumentType)} className="h-8 rounded-sm border border-border bg-background px-2 text-[11px] text-foreground" data-testid="select-document-type">
                      {(['INVOICE', 'RECEIPT', 'UNKNOWN'] as DocumentType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                    </select>
                    {data.document_type_confidence !== null && <span title="Heuristic classification confidence">{formatPercent(data.document_type_confidence)}</span>}
                  </label>
                </div>
                <div className="grid gap-x-4 gap-y-4 p-4 sm:grid-cols-2">
                  {data.fields.map((field) => {
                    const error = fieldErrors[field.name];
                    const changed = values[field.name] !== serverValues[field.name];
                    const effective = field.effective_confidence;
                    const low = field.status === 'uncertain' || field.status === 'invalid';
                    const showNormalized = !changed && readingDiffers(field.name, field.value, field.normalized_value);
                    const wide = field.name.endsWith('address');
                    return (
                      <label key={field.name} className={`block ${wide ? 'sm:col-span-2' : ''}`} data-testid={`field-${field.name}`}>
                        <span className="mb-1.5 flex items-center justify-between gap-2 text-[10px] font-semibold text-muted-foreground">
                          <span className="flex items-center gap-1.5">{FIELD_LABEL[field.name] ?? field.name}{field.required && <span className="text-red-700">*</span>}<FieldStatusBadge status={field.status} />{field.is_user_edited && <span className="rounded-sm bg-accent px-1.5 py-0.5 text-[9px] text-primary">Edited</span>}</span>
                          {effective !== null && <span className={low ? 'text-[#a77c36]' : 'text-primary'} title={`${METHOD_LABEL[field.method ?? ''] ?? ''}${field.page_number ? ` · page ${field.page_number}` : ''}. Heuristic score, not measured accuracy.`}>{formatPercent(effective)} {field.confidence_level}</span>}
                        </span>
                        <input
                          value={values[field.name] ?? ''}
                          onChange={(e) => { setValues((v) => ({ ...v, [field.name]: e.target.value })); setFieldErrors((f) => ({ ...f, [field.name]: '' })); }}
                          placeholder={field.status === 'missing' ? 'Not found in the document' : DATE_FIELDS.has(field.name) ? 'YYYY-MM-DD' : AMOUNT_FIELDS.has(field.name) ? '0.00' : ''}
                          className={`h-9 w-full rounded-sm border bg-background px-2.5 text-xs outline-none focus:border-primary ${error ? 'border-red-500' : low ? 'border-[#d8c59e]' : 'border-border'}`}
                          data-testid={`input-field-${field.name}`}
                          aria-invalid={Boolean(error)}
                        />
                        {effective !== null && <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-muted"><span className={`block h-full rounded-full ${low ? 'bg-[#c49a50]' : 'bg-primary'}`} style={{ width: `${Math.round(effective * 100)}%` }} /></span>}
                        {error && <span className="mt-1 block text-[10px] text-red-700 dark:text-red-300" data-testid={`error-field-${field.name}`}>{error}</span>}
                        {!error && showNormalized && <span className="mt-1 block text-[10px] text-muted-foreground">Read as {AMOUNT_FIELDS.has(field.name) ? formatMoney(Number(field.normalized_value), currency) : String(field.normalized_value)}</span>}
                        {!error && fieldWarnings(field.name).map((w, i) => <span key={i} className={`mt-1 block text-[10px] ${w.severity === 'INFO' ? 'text-muted-foreground' : 'text-[#947037] dark:text-[#e2bd7a]'}`}>{w.severity === 'INFO' ? <Info size={10} className="mr-1 inline" /> : null}{w.message}</span>)}
                      </label>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-md border border-border bg-card">
                <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
                  <div><h2 className="text-sm font-semibold">Line items</h2><p className="mt-1 text-[10px] text-muted-foreground">{rows.length ? 'Edit rows or add missing ones.' : 'No line items were detected.'}</p></div>
                  <Button variant="outline" className="px-2.5 py-1.5 text-[11px]" onClick={() => setRows((r) => [...r, { key: `new-${Date.now()}`, description: '', quantity: '', unit_price: '', total: '', confidence: null }])} testid="button-add-line-item"><Plus size={13} />Add row</Button>
                </div>
                {rows.length > 0 && (
                  <>
                    <div className="grid grid-cols-[1fr_56px_80px_84px_24px] gap-2 px-4 pt-3 text-[9px] font-bold uppercase tracking-wider text-muted-foreground"><span>Description</span><span className="text-right">Qty</span><span className="text-right">Unit price</span><span className="text-right">Total</span><span /></div>
                    <div className="divide-y divide-border">
                      {rows.map((row, index) => (
                        <div key={row.key} className="grid grid-cols-[1fr_56px_80px_84px_24px] items-center gap-2 px-4 py-2.5" data-testid={`line-item-${index + 1}`}>
                          <input value={row.description} onChange={(e) => setRows((r) => r.map((x) => (x.key === row.key ? { ...x, description: e.target.value } : x)))} className="min-w-0 rounded-sm border border-transparent bg-transparent px-1 py-1 text-[11px] outline-none focus:border-primary focus:bg-background" aria-label={`Line ${index + 1} description`} data-testid={`input-item-description-${index + 1}`} />
                          {(['quantity', 'unit_price', 'total'] as const).map((key) => (
                            <input key={key} inputMode="decimal" value={row[key]} onChange={(e) => setRows((r) => r.map((x) => (x.key === row.key ? { ...x, [key]: e.target.value } : x)))} className="w-full rounded-sm border border-border bg-background px-1.5 py-1 text-right font-mono text-[10px] outline-none focus:border-primary" aria-label={`Line ${index + 1} ${key.replace('_', ' ')}`} data-testid={`input-item-${key}-${index + 1}`} />
                          ))}
                          <button onClick={() => setRows((r) => r.filter((x) => x.key !== row.key))} className="grid h-6 w-6 place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-red-700" aria-label={`Remove line ${index + 1}`} data-testid={`button-remove-item-${index + 1}`}><X size={13} /></button>
                        </div>
                      ))}
                    </div>
                    <div className="flex justify-between border-t border-border px-4 py-3 text-xs"><span className="font-semibold">Line items total</span><span className="font-mono font-semibold">{formatMoney(lineItemsTotal, currency)}</span></div>
                  </>
                )}
                {fieldErrors.line_items && <p className="px-4 pb-3 text-[10px] text-red-700">{fieldErrors.line_items}</p>}
              </section>

              <div className="rounded-sm border border-[#e7e4d9] bg-[#f8f7f1] p-3.5 text-[10px] leading-5 text-muted-foreground dark:border-border dark:bg-muted/40">
                <span className="font-semibold text-foreground">About these values</span>
                <p className="mt-1">Fields were extracted with deterministic rules{doc.pages.some((p) => p.text_source === 'OCR') ? ' from OCR text' : ' from the PDF text layer'}. Confidence is a heuristic score (overall {formatPercent(data.overall_confidence)}), not measured accuracy. Always check figures against the document.</p>
              </div>
            </>
          )}
        </div>
      </div>

      {confirm === 'delete' && (
        <Modal title="Delete this document?" onClose={() => setConfirm(null)}>
          <p className="text-sm leading-6 text-muted-foreground">“{doc.original_filename}” and its extracted data will be permanently deleted from the server.</p>
          <div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()} testid="button-confirm-delete">{remove.isPending ? 'Deleting…' : 'Delete document'}</Button></div>
        </Modal>
      )}
      {confirm === 'reprocess' && (
        <Modal title="Reprocess this document?" onClose={() => setConfirm(null)}>
          <p className="text-sm leading-6 text-muted-foreground">The file is read again and every extracted value is replaced.{editedCount > 0 && <b className="text-foreground"> Your {editedCount} manual correction{editedCount === 1 ? '' : 's'} will be lost.</b>}{dirty && ' Unsaved changes will be discarded.'}</p>
          <div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setConfirm(null)}>Cancel</Button><Button disabled={reprocess.isPending} onClick={() => reprocess.mutate()} testid="button-confirm-reprocess">{reprocess.isPending ? 'Starting…' : 'Reprocess'}</Button></div>
        </Modal>
      )}
    </div>
  );
}
