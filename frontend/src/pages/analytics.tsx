import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, FileCheck2, ReceiptText, Store } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link } from 'wouter';
import { EmptyState, ErrorState, Metric, PageHeader } from '@/components/documind';
import { errorMessage } from '@/lib/api-client';
import { formatMoney, STATUS_LABEL, TYPE_LABEL } from '@/lib/format';
import { api, queryKeys, type DocumentStatus } from '@/services/api';

const chartColors = ['#316c65', '#c28c49', '#728b9c', '#bc796d', '#76977d', '#9b8e77'];
const tooltipStyle = { borderRadius: 4, border: '1px solid #dedfd9', fontSize: 12 };

function ChartPanel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-card">
      <div className="px-5 pt-5"><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-[11px] text-muted-foreground">{description}</p></div>
      <div className="h-[280px] p-4">{children}</div>
    </section>
  );
}

const Empty = ({ children }: { children: ReactNode }) => <div className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">{children}</div>;

export default function AnalyticsPage() {
  const overview = useQuery({ queryKey: queryKeys.analytics('overview'), queryFn: api.analyticsOverview });
  const spending = useQuery({ queryKey: queryKeys.analytics('spending'), queryFn: api.analyticsSpending });
  const vendors = useQuery({ queryKey: queryKeys.analytics('vendors'), queryFn: api.analyticsVendors });
  const o = overview.data;
  const loading = overview.isLoading;
  const primary = o?.spend[0];
  const currency = primary?.currency ?? null;
  const otherCurrencies = (o?.spend ?? []).slice(1);
  const monthly = (spending.data?.months ?? []).filter((m) => m.currency === currency);
  const vendorRows = (vendors.data?.vendors ?? []).filter((v) => v.currency === currency).slice(0, 8);
  const types = Object.entries(o?.type_counts ?? {}).filter(([, n]) => n > 0).map(([t, count]) => ({ name: TYPE_LABEL[t as keyof typeof TYPE_LABEL] ?? 'Unclassified', count }));
  const statuses = Object.entries(o?.status_counts ?? {}).filter(([, count]) => count > 0).map(([s, count]) => ({ name: STATUS_LABEL[s as DocumentStatus] ?? s, count }));
  const error = overview.error ?? spending.error ?? vendors.error;

  return (
    <div className="page-enter">
      <PageHeader eyebrow="Workspace intelligence" title="Analytics" description="Calculated from the values extracted from your processed documents." />

      {error && <ErrorState message={errorMessage(error)} onRetry={() => { void overview.refetch(); void spending.refetch(); void vendors.refetch(); }} testid="status-analytics-error" />}

      {!loading && o && o.processed === 0 ? (
        <EmptyState
          title="No analytics yet"
          body={o.total_documents === 0 ? 'Analytics appear as documents are processed. Upload a few invoices or receipts to get started.' : 'Your documents are still processing (or failed). Analytics appear once at least one is processed.'}
          action={<Link href="/app/upload" className="inline-flex items-center gap-2 rounded-sm bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground">Upload documents</Link>}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Metric label="Total spending" value={loading ? '—' : primary ? formatMoney(primary.total, currency) : '—'} caption={primary ? `${primary.document_count} document${primary.document_count === 1 ? '' : 's'}${currency ? '' : ' with no currency found'}` : 'No totals extracted yet'} icon={ReceiptText} />
            <Metric label="Average per document" value={loading ? '—' : primary ? formatMoney(primary.average, currency) : '—'} caption="Total ÷ documents with a total" icon={BarChart3} />
            <Metric label="Documents processed" value={loading ? '—' : o?.processed} caption={o ? `${o.needs_review} still need review` : ''} icon={FileCheck2} />
            <Metric label="Vendors" value={vendors.isLoading ? '—' : new Set((vendors.data?.vendors ?? []).map((v) => v.vendor)).size} caption="Distinct vendors with a total (top 10 shown)" icon={Store} />
          </div>

          {o && (o.spend_includes_needs_review > 0 || otherCurrencies.length > 0 || o.processed_without_total > 0) && (
            <div className="mt-4 rounded-sm border border-border bg-card px-4 py-3 text-[11px] leading-5 text-muted-foreground" data-testid="analytics-notes">
              {o.spend_includes_needs_review > 0 && <p>Includes {o.spend_includes_needs_review} document{o.spend_includes_needs_review === 1 ? '' : 's'} still marked “Review needed”; their values may change after review.</p>}
              {otherCurrencies.length > 0 && <p>Charts show {currency ?? 'documents without a currency'}. Also processed: {otherCurrencies.map((c) => `${formatMoney(c.total, c.currency)} (${c.document_count} doc${c.document_count === 1 ? '' : 's'}${c.currency ? '' : ', currency not found'})`).join(', ')}. Currencies are never added together.</p>}
              {o.processed_without_total > 0 && <p>{o.processed_without_total} processed document{o.processed_without_total === 1 ? ' has' : 's have'} no total and {o.processed_without_total === 1 ? 'is' : 'are'} not counted.</p>}
            </div>
          )}

          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <ChartPanel title="Monthly spending" description={`By invoice date${currency ? ` · ${currency}` : ''}${spending.data?.processed_without_date ? ` · ${spending.data.processed_without_date} without a date not shown` : ''}`}>
              {spending.isLoading ? <div className="h-full animate-pulse rounded-sm bg-muted" /> : monthly.length === 0 ? <Empty>No dated totals yet.</Empty> : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e8e9e4" />
                    <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#737c7d' }} />
                    <YAxis axisLine={false} tickLine={false} width={64} tick={{ fontSize: 9, fill: '#8a9090' }} tickFormatter={(v) => formatMoney(Number(v), null)} />
                    <Tooltip formatter={(v) => formatMoney(Number(v), currency)} contentStyle={tooltipStyle} />
                    <Bar dataKey="total" fill="#316c65" radius={[3, 3, 0, 0]} maxBarSize={38} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel title="Spending by vendor" description={`Highest totals${currency ? ` · ${currency}` : ''}`}>
              {vendors.isLoading ? <div className="h-full animate-pulse rounded-sm bg-muted" /> : vendorRows.length === 0 ? <Empty>No vendor totals yet.</Empty> : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={vendorRows} layout="vertical" margin={{ top: 0, right: 20, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e8e9e4" />
                    <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: '#8a9090' }} tickFormatter={(v) => formatMoney(Number(v), null)} />
                    <YAxis type="category" dataKey="vendor" width={120} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: '#737c7d' }} />
                    <Tooltip formatter={(v) => formatMoney(Number(v), currency)} contentStyle={tooltipStyle} />
                    <Bar dataKey="total" fill="#316c65" radius={[0, 3, 3, 0]} maxBarSize={22} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel title="Processing status" description="All documents in this workspace">
              {loading ? <div className="h-full animate-pulse rounded-sm bg-muted" /> : statuses.length === 0 ? <Empty>No documents yet.</Empty> : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={statuses} layout="vertical" margin={{ top: 0, right: 20, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e8e9e4" />
                    <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: '#8a9090' }} />
                    <YAxis type="category" dataKey="name" width={110} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: '#737c7d' }} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="count" radius={[0, 3, 3, 0]} maxBarSize={22}>{statuses.map((s, i) => <Cell key={s.name} fill={chartColors[i % chartColors.length]} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel title="Document types" description="Processed documents by classified type">
              {loading ? <div className="mx-auto mt-10 h-40 w-40 animate-pulse rounded-full bg-muted" /> : types.length === 0 ? <Empty>No processed documents yet.</Empty> : (
                <div className="relative h-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart><Pie data={types} dataKey="count" nameKey="name" innerRadius={56} outerRadius={82} paddingAngle={4} stroke="none">{types.map((t, i) => <Cell key={t.name} fill={chartColors[i % chartColors.length]} />)}</Pie><Tooltip /></PieChart>
                  </ResponsiveContainer>
                  <div className="absolute bottom-1 left-0 right-0 flex justify-center gap-5">{types.map((t, i) => <div key={t.name} className="flex items-center gap-1.5 text-[10px] text-muted-foreground"><span className="h-2 w-2 rounded-full" style={{ background: chartColors[i % chartColors.length] }} />{t.name} <b className="text-foreground">{t.count}</b></div>)}</div>
                </div>
              )}
            </ChartPanel>
          </div>
        </>
      )}
      <p className="mt-5 text-[10px] text-muted-foreground">Figures are sums of extracted values, not audited financial reporting. Confidence scores are heuristics, not measured accuracy.</p>
    </div>
  );
}
