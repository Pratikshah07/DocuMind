import { useRef, useState } from 'react';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowUpRight, Check, CircleAlert, CloudUpload, FileText, LoaderCircle, RotateCcw, ShieldCheck, X } from 'lucide-react';
import { Link } from 'wouter';
import { PageHeader, StatusBadge } from '@/components/documind';
import { ApiError, errorMessage } from '@/lib/api-client';
import { formatBytes, STAGES, STATUS_LABEL } from '@/lib/format';
import { notify } from '@/lib/ui';
import { api, isInProgress, queryKeys, type DocumentStatus } from '@/services/api';

const EXTENSIONS = /\.(pdf|png|jpe?g)$/i;
const SAMPLES_URL = 'https://github.com/Pratikshah07/DocuMind/tree/main/backend/samples';

type QueueItem = {
  key: string;
  name: string;
  size: number;
  documentId?: string;
  state: 'waiting' | 'uploading' | 'uploaded' | 'rejected';
  error?: string;
};

function StageSteps({ status }: { status: DocumentStatus }) {
  const current = STAGES.indexOf(status);
  return (
    <div className="mt-2 flex items-center gap-1" aria-label={`Stage: ${STATUS_LABEL[status]}`}>
      {STAGES.map((stage, i) => (
        <span key={stage} title={STATUS_LABEL[stage]} className={`h-1.5 flex-1 rounded-full ${current === -1 || i < current ? 'bg-primary' : i === current ? 'animate-pulse bg-primary/60' : 'bg-muted'}`} />
      ))}
    </div>
  );
}

export default function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, staleTime: Infinity });
  const maxBytes = meta.data?.max_upload_bytes ?? 15 * 1024 * 1024;

  // Poll each uploaded document's real status until it reaches a terminal state.
  const statuses = useQueries({
    queries: queue
      .filter((item) => item.documentId)
      .map((item) => ({
        queryKey: queryKeys.status(item.documentId!),
        queryFn: () => api.getStatus(item.documentId!),
        refetchInterval: (query: { state: { data?: { status: DocumentStatus } } }) =>
          query.state.data && !isInProgress(query.state.data.status) ? false : 2000,
      })),
  });
  const statusById = new Map(statuses.filter((s) => s.data).map((s) => [s.data!.document_id, s.data!]));

  const update = (key: string, patch: Partial<QueueItem>) => setQueue((items) => items.map((i) => (i.key === key ? { ...i, ...patch } : i)));

  const startUploads = async (files: File[]) => {
    if (busy || files.length === 0) return; // guards double drops/clicks
    const items: QueueItem[] = files.map((file, i) => {
      const key = `${Date.now()}-${i}-${file.name}`;
      if (!EXTENSIONS.test(file.name)) return { key, name: file.name, size: file.size, state: 'rejected', error: 'Unsupported file type. Use PDF, PNG or JPG.' };
      if (file.size > maxBytes) return { key, name: file.name, size: file.size, state: 'rejected', error: `Larger than the ${formatBytes(maxBytes)} limit.` };
      if (file.size === 0) return { key, name: file.name, size: 0, state: 'rejected', error: 'The file is empty.' };
      return { key, name: file.name, size: file.size, state: 'waiting' };
    });
    setQueue((current) => [...items, ...current]);
    setBusy(true);
    let uploaded = 0;
    try {
      for (const [index, item] of items.entries()) {
        if (item.state !== 'waiting') continue;
        update(item.key, { state: 'uploading' });
        try {
          const response = await api.upload(files[index]);
          update(item.key, { state: 'uploaded', documentId: response.id });
          uploaded += 1;
        } catch (error) {
          update(item.key, { state: 'rejected', error: errorMessage(error) });
          if (error instanceof ApiError && error.code === 'rate_limited') {
            items.slice(index + 1).filter((i) => i.state === 'waiting').forEach((i) => update(i.key, { state: 'rejected', error: 'Not uploaded: rate limit reached.' }));
            break;
          }
        }
      }
    } finally {
      setBusy(false);
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics'] });
      if (uploaded) notify(`${uploaded} file${uploaded === 1 ? '' : 's'} uploaded. Processing has started.`);
    }
  };

  const onDrop = (event: React.DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragging(false);
    void startUploads(Array.from(event.dataTransfer.files));
  };

  return (
    <div className="page-enter">
      <PageHeader eyebrow="Bring in a file" title="Upload documents" description="Invoices and receipts as PDF, PNG or JPG. Text is read from the PDF, or with OCR for scans and photos, then fields are extracted and validated." />

      <section className="rounded-md border border-border bg-card p-4 sm:p-6">
        <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" multiple className="sr-only" onChange={(e) => { void startUploads(Array.from(e.target.files ?? [])); e.target.value = ''; }} data-testid="input-upload-files" />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
          onDrop={onDrop}
          disabled={busy}
          className={`flex min-h-[260px] w-full flex-col items-center justify-center rounded-sm border border-dashed px-5 py-9 text-center transition-colors disabled:cursor-wait disabled:opacity-70 ${dragging ? 'border-primary bg-accent/60' : 'border-border bg-background hover:border-primary/60 hover:bg-muted/30'}`}
          aria-label="Choose or drop invoice and receipt files"
          data-testid="dropzone-upload"
        >
          <span className="grid h-12 w-12 place-items-center rounded-full bg-accent text-primary">{busy ? <LoaderCircle size={22} className="animate-spin" /> : <CloudUpload size={22} />}</span>
          <span className="mt-4 text-sm font-semibold">{busy ? 'Uploading…' : dragging ? 'Drop files to upload them' : 'Drop files here or browse'}</span>
          <span className="mt-2 text-xs text-muted-foreground">Up to {formatBytes(maxBytes)} each{meta.data ? ` · up to ${meta.data.max_pages} pages` : ''}</span>
          <span className="mt-4 flex flex-wrap justify-center gap-2">{['PDF', 'PNG', 'JPG', 'JPEG'].map((f) => <span key={f} className="rounded-sm border border-border bg-card px-2 py-1 text-[9px] font-semibold text-muted-foreground">{f}</span>)}</span>
        </button>

        <div className="mt-4 flex items-start gap-2 rounded-sm border border-[#e6dfce] bg-[#faf8f1] p-3 text-[11px] leading-5 text-muted-foreground dark:border-border dark:bg-muted/40">
          <ShieldCheck size={15} className="mt-0.5 shrink-0 text-primary" />
          <span>
            {meta.data?.demo_mode
              ? `Public demo: please upload only sample or synthetic documents, not real personal or financial records. Your uploads are visible only in this browser and are deleted automatically after ${meta.data.retention_hours} hours.`
              : 'Files are stored on this DocuMind server and processed there.'}{' '}
            Need a file? <a href={SAMPLES_URL} target="_blank" rel="noreferrer" className="font-semibold text-primary underline" data-testid="link-samples">Download synthetic samples</a>.
          </span>
        </div>
      </section>

      <section className="mt-5 rounded-md border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-5">
          <div><h2 className="text-sm font-semibold">This session's uploads</h2><p className="mt-1 text-[10px] text-muted-foreground">{queue.length ? 'Live status from the server. You can leave this page; processing continues.' : 'Files you upload will appear here.'}</p></div>
          {queue.some((i) => i.state === 'rejected' || (i.documentId && !isInProgress(statusById.get(i.documentId)?.status ?? 'UPLOADED'))) && (
            <button type="button" onClick={() => setQueue((items) => items.filter((i) => i.state !== 'rejected' && (!i.documentId || isInProgress(statusById.get(i.documentId)?.status ?? 'UPLOADED'))))} className="text-[10px] font-semibold text-muted-foreground hover:text-foreground" data-testid="button-clear-completed">Clear finished</button>
          )}
        </div>
        {queue.length === 0 ? (
          <div className="p-7 text-center"><FileText className="mx-auto text-muted-foreground" size={21} /><p className="mt-2 text-xs font-medium">No uploads in this session</p></div>
        ) : (
          <div className="divide-y divide-border">
            {queue.map((item) => {
              const status = item.documentId ? statusById.get(item.documentId) : undefined;
              const failed = item.state === 'rejected' || status?.status === 'FAILED';
              const done = status && !isInProgress(status.status);
              return (
                <div key={item.key} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5" data-testid={`upload-item-${item.documentId ?? item.key}`}>
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">
                    {failed ? <CircleAlert size={16} className="text-red-700" /> : done ? <Check size={16} /> : <LoaderCircle size={16} className="animate-spin" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-semibold">{item.name}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground" data-testid="text-upload-stage">
                      {item.state === 'waiting' && 'Waiting to upload'}
                      {item.state === 'uploading' && `Uploading ${formatBytes(item.size)}…`}
                      {item.state === 'rejected' && <span className="text-red-700 dark:text-red-300">{item.error}</span>}
                      {item.state === 'uploaded' && (status ? (status.status === 'FAILED' ? <span className="text-red-700 dark:text-red-300">{status.error_message}</span> : STATUS_LABEL[status.status]) : 'Uploaded · waiting for status')}
                    </div>
                    {status && isInProgress(status.status) && <StageSteps status={status.status} />}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {status && <StatusBadge status={status.status} />}
                    {item.documentId && (
                      <Link href={`/app/documents/${item.documentId}`} className="inline-flex items-center gap-1 text-[10px] font-semibold text-primary" data-testid={`link-open-${item.documentId}`}>Open <ArrowUpRight size={12} /></Link>
                    )}
                    {item.state === 'rejected' && (
                      <button type="button" aria-label="Dismiss" onClick={() => setQueue((items) => items.filter((i) => i.key !== item.key))} className="text-muted-foreground hover:text-foreground"><X size={14} /></button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="mt-5 flex justify-end">
        <Link href="/app/documents" className="inline-flex items-center gap-2 text-xs font-semibold text-primary hover:underline" data-testid="link-upload-documents">View all documents <RotateCcw size={13} /></Link>
      </div>
    </div>
  );
}
