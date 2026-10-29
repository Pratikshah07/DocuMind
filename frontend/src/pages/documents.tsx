import { useEffect, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ArrowUpRight, ChevronLeft, ChevronRight, FileText, ReceiptText, Search, Upload } from 'lucide-react';
import { Link } from 'wouter';
import { ErrorState, LoadingRows, PageHeader, StatusBadge } from '@/components/documind';
import { errorMessage } from '@/lib/api-client';
import { formatDate, formatMoney, formatPercent, TYPE_LABEL } from '@/lib/format';
import { api, IN_PROGRESS, isInProgress, queryKeys, type DocumentFilters, type DocumentSort, type DocumentStatus, type DocumentSummary, type DocumentType } from '@/services/api';

const PAGE_SIZE = 25;
const STATUS_FILTERS: Record<string, DocumentStatus[] | undefined> = {
  'All statuses': undefined,
  Ready: ['COMPLETED'],
  'Review needed': ['NEEDS_REVIEW'],
  Processing: IN_PROGRESS,
  Failed: ['FAILED'],
};
const SORTS: Record<string, DocumentSort> = {
  'Newest first': 'newest',
  'Oldest first': 'oldest',
  'Amount high to low': 'amount_desc',
  'Amount low to high': 'amount_asc',
  'Vendor A to Z': 'vendor',
};

function Confidence({ score }: { score: number | null }) {
  if (score === null) return <span className="text-[10px] text-muted-foreground">—</span>;
  const low = score < 0.6;
  return (
    <span className="inline-flex min-w-[76px] items-center gap-2 text-[10px]" title="Heuristic extraction confidence, not measured accuracy">
      <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted"><span className={`block h-full rounded-full ${low ? 'bg-[#c49a50]' : 'bg-primary'}`} style={{ width: `${Math.round(score * 100)}%` }} /></span>
      <span className={low ? 'text-[#947037]' : 'text-muted-foreground'}>{formatPercent(score)}</span>
    </span>
  );
}

function DocumentCard({ document }: { document: DocumentSummary }) {
  return (
    <Link href={`/app/documents/${document.id}`} className="block rounded-md border border-border bg-card p-4" data-testid={`card-document-${document.id}`}>
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">{document.document_type === 'RECEIPT' ? <ReceiptText size={16} /> : <FileText size={16} />}</span>
        <div className="min-w-0 flex-1"><div className="truncate text-xs font-semibold">{document.original_filename}</div><div className="mt-1 truncate text-[10px] text-muted-foreground">{document.vendor_name ?? 'Vendor not found'} · {document.document_type ? TYPE_LABEL[document.document_type] : 'Not classified yet'}</div></div>
        <StatusBadge status={document.status} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3 text-[10px]">
        <div><div className="text-muted-foreground">Date</div><div className="mt-1 font-medium">{formatDate(document.invoice_date)}</div></div>
        <div><div className="text-muted-foreground">Total</div><div className="mt-1 font-mono font-medium">{formatMoney(document.total, document.currency)}</div></div>
        <div><div className="text-muted-foreground">Confidence</div><div className="mt-1"><Confidence score={document.overall_confidence} /></div></div>
        <span className="inline-flex items-end justify-end gap-1 font-semibold text-primary">Open <ArrowUpRight size={13} /></span>
      </div>
    </Link>
  );
}

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export default function DocumentsPage() {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('All statuses');
  const [type, setType] = useState('All types');
  const [sort, setSort] = useState('Newest first');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [page, setPage] = useState(0);
  const q = useDebounced(search.trim());

  const filters: DocumentFilters = {
    q: q || undefined,
    status: STATUS_FILTERS[status],
    document_type: type === 'All types' ? undefined : (type.toUpperCase() as DocumentType),
    date_from: fromDate || undefined,
    date_to: toDate || undefined,
    sort: SORTS[sort],
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
  useEffect(() => setPage(0), [q, status, type, sort, fromDate, toDate]);

  const query = useQuery({
    queryKey: queryKeys.documents(filters),
    queryFn: () => api.listDocuments(filters),
    placeholderData: keepPreviousData,
    refetchInterval: (state) => (state.state.data?.items.some((d) => isInProgress(d.status)) ? 3000 : false),
  });
  const documents = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const filtered = Boolean(q || status !== 'All statuses' || type !== 'All types' || fromDate || toDate);
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const clearFilters = () => {
    setSearch(''); setStatus('All statuses'); setType('All types'); setSort('Newest first'); setFromDate(''); setToDate('');
  };

  const label = 'mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground';
  const select = 'h-10 w-full rounded-sm border border-border bg-background px-2.5 text-[11px] sm:h-9 sm:w-auto';

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="Your workspace"
        title="Documents"
        description="Search, filter and review every invoice and receipt you have uploaded."
        action={<Link href="/app/upload" className="inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90" data-testid="button-add-document"><Upload size={15} />Upload documents</Link>}
      />

      <section className="rounded-md border border-border bg-card">
        <div className="space-y-3 border-b border-border p-4">
          <label className="relative block">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by file name or vendor…" aria-label="Search documents" className="h-10 w-full rounded-sm border border-border bg-background pl-9 pr-3 text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 sm:max-w-sm" data-testid="input-search-documents" />
          </label>
          <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
            <label className="block"><span className={label}>Status</span><select value={status} onChange={(e) => setStatus(e.target.value)} className={`${select} min-w-32`} data-testid="select-filter-status">{Object.keys(STATUS_FILTERS).map((s) => <option key={s}>{s}</option>)}</select></label>
            <label className="block"><span className={label}>Type</span><select value={type} onChange={(e) => setType(e.target.value)} className={`${select} min-w-28`} data-testid="select-filter-type">{['All types', 'Invoice', 'Receipt', 'Unknown'].map((t) => <option key={t}>{t}</option>)}</select></label>
            <label className="block"><span className={label}>Document date from</span><input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="h-10 w-full rounded-sm border border-border bg-background px-2 text-[10px] sm:h-9 sm:w-auto" data-testid="input-filter-from-date" /></label>
            <label className="block"><span className={label}>To</span><input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="h-10 w-full rounded-sm border border-border bg-background px-2 text-[10px] sm:h-9 sm:w-auto" data-testid="input-filter-to-date" /></label>
            <label className="block"><span className={label}>Sort by</span><select value={sort} onChange={(e) => setSort(e.target.value)} className={`${select} min-w-36`} data-testid="select-sort-documents">{Object.keys(SORTS).map((s) => <option key={s}>{s}</option>)}</select></label>
            {filtered && <button type="button" onClick={clearFilters} className="h-10 px-2 text-left text-[11px] font-semibold text-primary hover:underline sm:h-9" data-testid="button-clear-filters">Clear filters</button>}
          </div>
        </div>

        <div className="flex items-center justify-between px-4 py-3 text-[10px] text-muted-foreground">
          <span data-testid="text-document-count">{query.isLoading ? 'Loading documents…' : `${total} document${total === 1 ? '' : 's'}`}</span>
          {pages > 1 && (
            <span className="flex items-center gap-2">
              <button className="grid h-9 w-9 place-items-center rounded-sm hover:bg-muted disabled:opacity-40 sm:h-6 sm:w-6" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Previous page" data-testid="button-page-previous"><ChevronLeft size={14} /></button>
              Page {page + 1} of {pages}
              <button className="grid h-9 w-9 place-items-center rounded-sm hover:bg-muted disabled:opacity-40 sm:h-6 sm:w-6" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page" data-testid="button-page-next"><ChevronRight size={14} /></button>
            </span>
          )}
        </div>

        {query.isError ? (
          <div className="m-4"><ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} testid="status-documents-error" /></div>
        ) : query.isLoading ? (
          <div className="p-4"><LoadingRows /></div>
        ) : documents.length === 0 ? (
          <div className="grid min-h-64 place-items-center px-5 py-10 text-center" data-testid="state-empty">
            <div>
              <FileText className="mx-auto text-muted-foreground" size={22} />
              <h2 className="mt-3 text-sm font-semibold">{filtered ? 'No matching documents' : 'No documents yet'}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{filtered ? 'Try changing your search or filters.' : 'Upload an invoice or receipt to get started.'}</p>
              {filtered ? (
                <button type="button" onClick={clearFilters} className="mt-4 text-xs font-semibold text-primary" data-testid="button-empty-clear-filters">Clear filters</button>
              ) : (
                <Link href="/app/upload" className="mt-4 inline-flex items-center gap-2 rounded-sm bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground" data-testid="link-empty-upload"><Upload size={14} /> Upload documents</Link>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[960px] border-collapse text-left">
                <thead className="border-y border-border bg-muted/35 text-[9px] font-semibold uppercase tracking-[.1em] text-muted-foreground">
                  <tr><th className="px-4 py-3">Document</th><th className="px-3 py-3">Type</th><th className="px-3 py-3">Vendor</th><th className="px-3 py-3">Date</th><th className="px-3 py-3 text-right">Total</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Confidence</th><th className="px-4 py-3 text-right">Actions</th></tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {documents.map((d) => (
                    <tr key={d.id} className="transition-colors hover:bg-muted/30" data-testid={`row-document-${d.id}`}>
                      <td className="max-w-[260px] px-4 py-3"><Link href={`/app/documents/${d.id}`} className="block truncate text-[11px] font-semibold hover:text-primary" data-testid={`link-document-${d.id}`}>{d.original_filename}</Link><div className="mt-1 text-[9px] text-muted-foreground">Uploaded {formatDate(d.created_at)}{d.page_count ? ` · ${d.page_count} page${d.page_count === 1 ? '' : 's'}` : ''}</div></td>
                      <td className="px-3 py-3 text-[10px]">{d.document_type ? TYPE_LABEL[d.document_type] : '—'}</td>
                      <td className="max-w-[160px] truncate px-3 py-3 text-[10px]">{d.vendor_name ?? '—'}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-[10px]">{formatDate(d.invoice_date)}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[10px]">{formatMoney(d.total, d.currency)}</td>
                      <td className="px-3 py-3"><StatusBadge status={d.status} /></td>
                      <td className="px-3 py-3"><Confidence score={d.overall_confidence} /></td>
                      <td className="px-4 py-3 text-right"><Link href={`/app/documents/${d.id}`} className="inline-flex items-center gap-1 rounded-sm border border-border px-2 py-1.5 text-[10px] font-semibold hover:border-primary hover:text-primary" data-testid={`button-review-document-${d.id}`}>Open <ArrowUpRight size={12} /></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid gap-3 p-3 md:hidden">{documents.map((d) => <DocumentCard key={d.id} document={d} />)}</div>
          </>
        )}
      </section>
    </div>
  );
}
