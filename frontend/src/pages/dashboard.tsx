import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  CircleAlert,
  CloudUpload,
  FileCheck2,
  FileText,
  ReceiptText,
  Timer,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Cell,
  CartesianGrid,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "wouter";
import { api, type Document, type ProcessingStatus } from "@/services/api";

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

const formatDate = (value: string) =>
  new Date(`${value}T12:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });

const colors = ["#316c65", "#c28c49", "#728b9c", "#bc796d"];

function Metric({
  label,
  value,
  caption,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  caption: string;
  icon: typeof FileText;
}) {
  return (
    <section
      className="rounded-md border border-border bg-card p-4 sm:p-5"
      data-testid={`metric-${label.toLowerCase().replaceAll(" ", "-")}`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className="grid h-8 w-8 place-items-center rounded-sm bg-accent text-primary">
          <Icon size={16} />
        </span>
      </div>
      <div className="mt-3 text-[25px] font-semibold tracking-[-.04em]">
        {value}
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">{caption}</div>
    </section>
  );
}

function StatusPill({ status }: { status: ProcessingStatus }) {
  const statusClass = {
    Ready: "bg-[#eaf3ee] text-[#386f58]",
    "Review needed": "bg-[#f8f1e3] text-[#947037]",
    Processing: "bg-[#edf2f5] text-[#526e7d]",
    Failed: "bg-red-50 text-red-700",
  }[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] font-semibold ${statusClass}`}
      data-testid={`status-${status.toLowerCase().replaceAll(" ", "-")}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function RecentDocument({ document }: { document: Document }) {
  return (
    <Link
      href={`/app/documents/${document.id}`}
      className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/45 sm:px-5"
      data-testid={`row-recent-document-${document.id}`}
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">
        {document.type === "Receipt" ? (
          <ReceiptText size={16} />
        ) : (
          <FileText size={16} />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold">
          {document.vendor}
        </span>
        <span className="mt-1 block truncate text-[10px] text-muted-foreground">
          {document.name} · {formatDate(document.date)}
        </span>
      </span>
      <span className="hidden text-right text-xs font-semibold sm:block">
        {formatCurrency(document.amount)}
      </span>
      <span className="hidden sm:block">
        <StatusPill status={document.status} />
      </span>
    </Link>
  );
}

function activityFor(status: ProcessingStatus) {
  switch (status) {
    case "Ready":
      return {
        label: "Extraction completed",
        icon: CheckCircle2,
        color: "text-[#386f58]",
      };
    case "Review needed":
      return {
        label: "Field review recommended",
        icon: CircleAlert,
        color: "text-[#947037]",
      };
    case "Processing":
      return {
        label: "Processing in progress",
        icon: Timer,
        color: "text-[#526e7d]",
      };
    case "Failed":
      return {
        label: "Processing failed",
        icon: AlertTriangle,
        color: "text-red-700",
      };
  }
}

export default function DashboardPage() {
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
  });
  const analyticsQuery = useQuery({
    queryKey: ["analytics"],
    queryFn: api.analytics,
  });
  const documents = documentsQuery.data ?? [];
  const analytics = analyticsQuery.data;
  const processed = documents.filter(
    (document) =>
      document.status === "Ready" || document.status === "Review needed",
  ).length;
  const processing = documents.filter(
    (document) => document.status === "Processing",
  ).length;
  const failed = documents.filter((document) => document.status === "Failed").length;
  const distribution = analytics?.types ?? [];
  const activityRank: Record<ProcessingStatus, number> = {
    Processing: 0,
    Failed: 1,
    "Review needed": 2,
    Ready: 3,
  };
  const recentActivity = [...documents]
    .sort(
      (left, right) =>
        activityRank[left.status] - activityRank[right.status] ||
        right.date.localeCompare(left.date),
    )
    .slice(0, 4);

  return (
    <div className="page-enter">
      <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[.14em] text-primary">
            Workspace overview
          </p>
          <h1
            className="text-[27px] font-semibold tracking-[-.035em] sm:text-[31px]"
            data-testid="heading-page"
          >
            Good morning, Morgan
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            A clear view of the documents moving through your workspace.
          </p>
        </div>
        <Link
          href="/app/upload"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          data-testid="link-dashboard-upload"
        >
          <CloudUpload size={15} />
          Upload documents
        </Link>
      </div>

      {(documentsQuery.isError || analyticsQuery.isError) && (
        <div
          className="mb-4 flex items-center justify-between rounded-sm border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
          data-testid="status-dashboard-error"
        >
          <span>Your demo data could not be loaded.</span>
          <button
            onClick={() => {
              void documentsQuery.refetch();
              void analyticsQuery.refetch();
            }}
            className="font-semibold underline"
            data-testid="button-dashboard-retry"
          >
            Try again
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Total documents"
          value={documentsQuery.isLoading ? "—" : documents.length}
          caption="Invoices and receipts in this workspace"
          icon={FileText}
        />
        <Metric
          label="Successfully processed"
          value={documentsQuery.isLoading ? "—" : processed}
          caption="Ready or waiting for a quick review"
          icon={FileCheck2}
        />
        <Metric
          label="Processing"
          value={documentsQuery.isLoading ? "—" : processing}
          caption="Documents in the demo queue"
          icon={Timer}
        />
        <Metric
          label="Failed"
          value={documentsQuery.isLoading ? "—" : failed}
          caption="Documents needing another attempt"
          icon={AlertTriangle}
        />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_.85fr]">
        <section className="overflow-hidden rounded-md border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-5">
            <div>
              <h2 className="text-sm font-semibold">Recent documents</h2>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Latest records in your local demo workspace
              </p>
            </div>
            <Link
              href="/app/documents"
              className="text-[11px] font-semibold text-primary"
              data-testid="link-documents-view"
            >
              View all
            </Link>
          </div>
          {documentsQuery.isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2, 3].map((row) => (
                <div
                  key={row}
                  className="h-12 animate-pulse rounded-sm bg-muted"
                />
              ))}
            </div>
          ) : documents.length === 0 ? (
            <div className="p-8 text-center">
              <FileText className="mx-auto text-muted-foreground" size={22} />
              <p className="mt-3 text-sm font-medium">No documents yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Upload an invoice or receipt to start exploring the workflow.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {documents.slice(0, 5).map((document) => (
                <RecentDocument key={document.id} document={document} />
              ))}
            </div>
          )}
        </section>

        <section className="rounded-md border border-border bg-card">
          <div className="flex items-center gap-2 px-5 pt-5">
            <Activity size={15} className="text-primary" />
            <div>
              <h2 className="text-sm font-semibold">Processing activity</h2>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Statuses from the sample documents
              </p>
            </div>
          </div>
          {documentsQuery.isLoading ? (
            <div className="space-y-4 p-5">
              {[0, 1, 2].map((row) => (
                <div
                  key={row}
                  className="h-9 animate-pulse rounded-sm bg-muted"
                />
              ))}
            </div>
          ) : recentActivity.length === 0 ? (
            <p className="p-5 text-xs text-muted-foreground">
              Processing updates will appear here when documents are added.
            </p>
          ) : (
            <div className="mt-2 divide-y divide-border px-5">
              {recentActivity.map((document) => {
                const activity = activityFor(document.status);
                const Icon = activity.icon;
                return (
                  <div
                    key={document.id}
                    className="flex items-center gap-3 py-3"
                    data-testid={`activity-document-${document.id}`}
                  >
                    <Icon className={activity.color} size={15} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11px] font-medium">
                        {activity.label}
                      </span>
                      <span className="mt-1 block truncate text-[10px] text-muted-foreground">
                        {document.vendor} · {formatDate(document.date)}
                      </span>
                    </span>
                    <StatusPill status={document.status} />
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <section className="rounded-md border border-border bg-card">
          <div className="flex items-start justify-between px-5 pt-5">
            <div>
              <h2 className="text-sm font-semibold">Monthly spending</h2>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Sample totals across the last six months
              </p>
            </div>
            <span className="rounded-sm border border-border px-2 py-1 text-[9px] text-muted-foreground">
              Demo data
            </span>
          </div>
          <div className="h-[230px] p-4">
            {analyticsQuery.isLoading ? (
              <div className="h-full animate-pulse rounded-sm bg-muted" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={analytics?.monthly ?? []}
                  margin={{ top: 10, right: 8, left: -20, bottom: 0 }}
                >
                  <defs>
                    <linearGradient
                      id="dashboard-spend-fill"
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop offset="0%" stopColor="#316c65" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="#316c65" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    stroke="#e8e9e4"
                  />
                  <XAxis
                    dataKey="month"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "#737c7d" }}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 9, fill: "#8a9090" }}
                    tickFormatter={(value) => `$${Math.round(value / 1000)}k`}
                  />
                  <Tooltip
                    formatter={(value) => formatCurrency(Number(value))}
                    contentStyle={{
                      borderRadius: 4,
                      border: "1px solid #dedfd9",
                      fontSize: 12,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="amount"
                    stroke="#316c65"
                    strokeWidth={2}
                    fill="url(#dashboard-spend-fill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </section>

        <section className="rounded-md border border-border bg-card">
          <div className="px-5 pt-5">
            <h2 className="text-sm font-semibold">Document type distribution</h2>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Invoices and receipts in the sample workspace
            </p>
          </div>
          <div className="relative flex h-[230px] items-center justify-center">
            {analyticsQuery.isLoading ? (
              <div className="h-40 w-40 animate-pulse rounded-full bg-muted" />
            ) : distribution.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Type data will appear when documents are available.
              </p>
            ) : (
              <>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={distribution}
                      dataKey="count"
                      nameKey="name"
                      innerRadius={58}
                      outerRadius={82}
                      paddingAngle={4}
                      stroke="none"
                    >
                      {distribution.map((item, index) => (
                        <Cell
                          key={item.name}
                          fill={colors[index % colors.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
                  <div className="text-xl font-semibold">
                    {analytics?.documentCount ?? 0}
                  </div>
                  <div className="text-[9px] text-muted-foreground">
                    documents
                  </div>
                </div>
              </>
            )}
          </div>
          <div className="flex flex-wrap justify-center gap-x-5 gap-y-2 pb-5">
            {distribution.map((item, index) => (
              <div
                key={item.name}
                className="flex items-center gap-1.5 text-[10px] text-muted-foreground"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: colors[index % colors.length] }}
                />
                {item.name}
                <b className="text-foreground">{item.count}</b>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="mt-5 flex flex-col gap-4 rounded-md border border-border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-sm bg-accent text-primary">
            <CloudUpload size={19} />
          </span>
          <div>
            <div className="text-sm font-semibold">
              Have an invoice or receipt to process?
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Upload a file to explore the simulated extraction flow.
            </p>
          </div>
        </div>
        <Link
          href="/app/upload"
          className="inline-flex items-center justify-center gap-2 rounded-sm border border-border bg-background px-3.5 py-2.5 text-sm font-semibold hover:bg-muted"
          data-testid="link-dashboard-upload-bottom"
        >
          Upload documents
        </Link>
      </div>
    </div>
  );
}