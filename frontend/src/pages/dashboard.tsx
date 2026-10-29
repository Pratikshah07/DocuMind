import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, CircleAlert, CloudUpload, FileCheck2, FileText, ReceiptText, Timer } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link } from 'wouter';
import { EmptyState, ErrorState, LoadingRows, Metric, PageHeader, StatusBadge } from '@/components/documind';
import { errorMessage } from '@/lib/api-client';
import { formatDate, formatMoney, STATUS_LABEL, TYPE_LABEL } from '@/lib/format';
import { api, isInProgress, queryKeys, type DocumentSummary } from '@/services/api';

const colors = ['#316c65', '#c28c49', '#728b9c', '#bc796d'];

function RecentDocument({ document }: { document: DocumentSummary }) {
  return (
    <Link href={`/app/documents/${document.id}`} className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/45 sm:px-5" data-testid={`row-recent-document-${document.id}`}>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">
        {document.document_type === 'RECEIPT' ? <ReceiptText size={16} /> : <FileText size={16} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold">{document.vendor_name ?? document.original_filename}</span>
        <span className="mt-1 block truncate text-[10px] text-muted-foreground">
          {document.original_filename} · uploaded {formatDate(document.created_at, { month: 'short', day: 'numeric' })}
        </span>
      </span>
      <span className="hidden text-right text-xs font-semibold sm:block">{formatMoney(document.total, document.currency)}</span>
      <span className="hidden sm:block"><StatusBadge status={document.status} /></span>
    </Link>
  );
}

export default function DashboardPage() {
  const overview = useQuery({ queryKey: queryKeys.analytics('overview'), queryFn: api.analyticsOverview });
  const recent = useQuery({
    queryKey: queryKeys.documents({ limit: 5 }),
    queryFn: () => api.listDocuments({ limit: 5 }),
    refetchInterval: (query) => (query.state.data?.items.some((d) => isInProgress(d.status)) ? 3000 : false),
  });
  const spending = useQuery({ queryKey: queryKeys.analytics('spending'), queryFn: api.analyticsSpending });

  const o = overview.data;
  const loading = overview.isLoading;
  const documents = recent.data?.items ?? [];
  // Chart the currency with the most documents; other currencies are never mixed in.
  const primaryCurrency = o?.spend[0]?.currency ?? null;
  const monthly = (spending.data?.months ?? []).filter((m) => m.currency === primaryCurrency);
  const distribution = Object.entries(o?.type_counts ?? {})
    .filter(([, count]) => count > 0)
    .map(([type, count]) => ({ name: TYPE_LABEL[type as keyof typeof TYPE_LABEL] ?? 'Unclassified', count }));
  const empty = !loading && o?.total_documents === 0;

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="Workspace overview"
        title="Your documents at a glance"
        description="Live counts and totals from the documents in this private workspace."
        action={<Link href="/app/upload" className="inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90" data-testid="link-dashboard-upload"><CloudUpload size={15} />Upload documents</Link>}
      />

      {(overview.isError || recent.isError) && (
        <ErrorState message={errorMessage(overview.error ?? recent.error)} onRetry={() => { void overview.refetch(); void recent.refetch(); }} testid="status-dashboard-error" />
      )}

      {empty ? (
        <EmptyState
          title="No documents yet"
          body={<>Upload an invoice or receipt (PDF, PNG or JPG) to see real extraction results here. No file handy? Use the synthetic <a className="font-semibold text-primary underline" href="https://github.com/Pratikshah07/DocuMind/tree/main/backend/samples" target="_blank" rel="noreferrer">sample documents</a>.</>}
          action={<Link href="/app/upload" className="inline-flex items-center gap-2 rounded-sm bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground" data-testid="link-empty-upload"><CloudUpload size={14} />Upload a document</Link>}
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Total documents" value={loading ? '—' : o?.total_documents} caption="Uploaded to this workspace" icon={FileText} />
            <Metric label="Processed" value={loading ? '—' : o?.processed} caption={o ? `${o.needs_review} need review` : 'Ready or needing review'} icon={FileCheck2} />
            <Metric label="Processing" value={loading ? '—' : o?.in_progress} caption="Queued, OCR or extraction" icon={Timer} />
            <Metric label="Failed" value={loading ? '—' : o?.failed} caption="Could not be read; retry from the document" icon={AlertTriangle} />
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_.85fr]">
            <section className="overflow-hidden rounded-md border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-5">
                <div><h2 className="text-sm font-semibold">Recent documents</h2><p className="mt-1 text-[11px] text-muted-foreground">Latest uploads</p></div>
                <Link href="/app/documents" className="text-[11px] font-semibold text-primary" data-testid="link-documents-view">View all</Link>
              </div>
              {recent.isLoading ? <div className="p-5"><LoadingRows /></div> : <div className="divide-y divide-border">{documents.map((d) => <RecentDocument key={d.id} document={d} />)}</div>}
            </section>

            <section className="rounded-md border border-border bg-card">
              <div className="flex items-center gap-2 px-5 pt-5">
                <Activity size={15} className="text-primary" />
                <div><h2 className="text-sm font-semibold">Needs attention</h2><p className="mt-1 text-[11px] text-muted-foreground">Documents in progress, failed or flagged for review</p></div>
              </div>
              <div className="mt-2 divide-y divide-border px-5 pb-2">
                {documents.filter((d) => d.status !== 'COMPLETED').length === 0 && !recent.isLoading && (
                  <p className="py-4 text-xs text-muted-foreground">Nothing needs attention in your latest uploads.</p>
                )}
                {documents.filter((d) => d.status !== 'COMPLETED').map((d) => (
                  <Link key={d.id} href={`/app/documents/${d.id}`} className="flex items-center gap-3 py-3 hover:opacity-80" data-testid={`activity-document-${d.id}`}>
                    {d.status === 'FAILED' ? <AlertTriangle size={15} className="text-red-700" /> : d.status === 'NEEDS_REVIEW' ? <CircleAlert size={15} className="text-[#947037]" /> : <Timer size={15} className="text-[#526e7d]" />}
                    <span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-medium">{d.vendor_name ?? d.original_filename}</span><span className="mt-1 block text-[10px] text-muted-foreground">{STATUS_LABEL[d.status]}</span></span>
                    <StatusBadge status={d.status} />
                  </Link>
                ))}
              </div>
            </section>
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <section className="rounded-md border border-border bg-card">
              <div className="px-5 pt-5">
                <h2 className="text-sm font-semibold">Monthly spending</h2>
                <p className="mt-1 text-[11px] text-muted-foreground">By invoice date{primaryCurrency ? ` · ${primaryCurrency}` : ''}. Values are as extracted; check flagged documents.</p>
              </div>
              <div className="h-[230px] p-4">
                {spending.isLoading ? <div className="h-full animate-pulse rounded-sm bg-muted" /> : monthly.length === 0 ? (
                  <div className="grid h-full place-items-center text-center text-xs text-muted-foreground">Spending appears once processed documents have a date and a total.</div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={monthly} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
                      <defs><linearGradient id="dashboard-spend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#316c65" stopOpacity={0.2} /><stop offset="100%" stopColor="#316c65" stopOpacity={0} /></linearGradient></defs>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e8e9e4" />
                      <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#737c7d' }} />
                      <YAxis axisLine={false} tickLine={false} width={60} tick={{ fontSize: 9, fill: '#8a9090' }} tickFormatter={(v) => formatMoney(Number(v), null)} />
                      <Tooltip formatter={(v) => formatMoney(Number(v), primaryCurrency)} contentStyle={{ borderRadius: 4, border: '1px solid #dedfd9', fontSize: 12 }} />
                      <Area type="monotone" dataKey="total" stroke="#316c65" strokeWidth={2} fill="url(#dashboard-spend-fill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>

            <section className="rounded-md border border-border bg-card">
              <div className="px-5 pt-5"><h2 className="text-sm font-semibold">Document types</h2><p className="mt-1 text-[11px] text-muted-foreground">Processed documents by classified type</p></div>
              <div className="relative flex h-[230px] items-center justify-center">
                {loading ? <div className="h-40 w-40 animate-pulse rounded-full bg-muted" /> : distribution.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Types appear once documents are processed.</p>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart><Pie data={distribution} dataKey="count" nameKey="name" innerRadius={58} outerRadius={82} paddingAngle={4} stroke="none">{distribution.map((item, i) => <Cell key={item.name} fill={colors[i % colors.length]} />)}</Pie><Tooltip /></PieChart>
                    </ResponsiveContainer>
                    <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center"><div className="text-xl font-semibold">{o?.processed ?? 0}</div><div className="text-[9px] text-muted-foreground">processed</div></div>
                  </>
                )}
              </div>
              <div className="flex flex-wrap justify-center gap-x-5 gap-y-2 pb-5">
                {distribution.map((item, i) => <div key={item.name} className="flex items-center gap-1.5 text-[10px] text-muted-foreground"><span className="h-2 w-2 rounded-full" style={{ background: colors[i % colors.length] }} />{item.name}<b className="text-foreground">{item.count}</b></div>)}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
