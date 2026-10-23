import { useQuery } from "@tanstack/react-query";
import { BarChart3, FileCheck2, ReceiptText, Store } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/services/api";

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

const chartColors = ["#316c65", "#c28c49", "#728b9c", "#bc796d", "#76977d"];

function Metric({
  label,
  value,
  caption,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  caption: string;
  icon: typeof ReceiptText;
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

function ChartPanel({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card">
      <div className="px-5 pt-5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-1 text-[11px] text-muted-foreground">{description}</p>
      </div>
      <div className="h-[280px] p-4">{children}</div>
    </section>
  );
}

export default function AnalyticsPage() {
  const analyticsQuery = useQuery({
    queryKey: ["analytics"],
    queryFn: api.analytics,
  });
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
  });
  const analytics = analyticsQuery.data;
  const documents = documentsQuery.data ?? [];
  const invoiceDocuments = documents.filter(
    (document) => document.type === "Invoice" && document.amount > 0,
  );
  const averageInvoice = invoiceDocuments.length
    ? invoiceDocuments.reduce((sum, document) => sum + document.amount, 0) /
      invoiceDocuments.length
    : 0;
  const processedCount = documents.filter(
    (document) =>
      document.status === "Ready" || document.status === "Review needed",
  ).length;
  const vendorCount = new Set(documents.map((document) => document.vendor)).size;
  const noAnalytics =
    !analyticsQuery.isLoading &&
    !analyticsQuery.isError &&
    (analytics?.documentCount ?? 0) === 0;

  return (
    <div className="page-enter">
      <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[.14em] text-primary">
            Workspace intelligence
          </p>
          <h1
            className="text-[27px] font-semibold tracking-[-.035em] sm:text-[31px]"
            data-testid="heading-page"
          >
            Analytics
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Spending patterns calculated from the saved sample documents.
          </p>
        </div>
        <span className="w-fit rounded-sm border border-border bg-card px-2.5 py-1.5 text-[10px] text-muted-foreground">
          Demo data · USD
        </span>
      </div>

      {analyticsQuery.isError && (
        <div
          className="mb-4 flex items-center justify-between rounded-sm border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
          data-testid="status-analytics-error"
        >
          <span>Your demo analytics could not be loaded.</span>
          <button
            onClick={() => {
              void analyticsQuery.refetch();
              void documentsQuery.refetch();
            }}
            className="font-semibold underline"
            data-testid="button-analytics-retry"
          >
            Try again
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Total spending"
          value={
            analyticsQuery.isLoading || !analytics
              ? "—"
              : formatCurrency(analytics.totalSpend)
          }
          caption="Captured across sample documents"
          icon={ReceiptText}
        />
        <Metric
          label="Average invoice"
          value={
            analyticsQuery.isLoading || documentsQuery.isLoading || !analytics
              ? "—"
              : formatCurrency(averageInvoice)
          }
          caption="Average value per invoice"
          icon={BarChart3}
        />
        <Metric
          label="Documents processed"
          value={documentsQuery.isLoading ? "—" : processedCount}
          caption="Ready or waiting for review"
          icon={FileCheck2}
        />
        <Metric
          label="Vendors"
          value={documentsQuery.isLoading ? "—" : vendorCount}
          caption="Distinct vendors in the workspace"
          icon={Store}
        />
      </div>

      {noAnalytics ? (
        <div className="mt-5 rounded-md border border-dashed border-border bg-card p-10 text-center">
          <BarChart3 className="mx-auto text-muted-foreground" size={24} />
          <h2 className="mt-3 text-sm font-semibold">No analytics yet</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Add demo documents to see spending and vendor patterns here.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <ChartPanel
              title="Monthly spending"
              description="Total document value across the last six sample months"
            >
              {analyticsQuery.isLoading ? (
                <div className="h-full animate-pulse rounded-sm bg-muted" />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={analytics?.monthly ?? []}
                    margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                  >
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
                      tickFormatter={(value) =>
                        `$${Math.round(value / 1000)}k`
                      }
                    />
                    <Tooltip
                      formatter={(value) => formatCurrency(Number(value))}
                      contentStyle={{
                        borderRadius: 4,
                        border: "1px solid #dedfd9",
                        fontSize: 12,
                      }}
                    />
                    <Bar
                      dataKey="amount"
                      fill="#316c65"
                      radius={[3, 3, 0, 0]}
                      maxBarSize={38}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel
              title="Spending by vendor"
              description="Highest-value vendors in the sample workspace"
            >
              {analyticsQuery.isLoading ? (
                <div className="h-full animate-pulse rounded-sm bg-muted" />
              ) : !analytics?.vendors.length ? (
                <div className="grid h-full place-items-center text-xs text-muted-foreground">
                  No vendor values yet.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={analytics.vendors}
                    layout="vertical"
                    margin={{ top: 0, right: 20, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      horizontal={false}
                      stroke="#e8e9e4"
                    />
                    <XAxis
                      type="number"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 9, fill: "#8a9090" }}
                      tickFormatter={(value) => `$${Math.round(value / 1000)}k`}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={112}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 9, fill: "#737c7d" }}
                    />
                    <Tooltip
                      formatter={(value) => formatCurrency(Number(value))}
                      contentStyle={{
                        borderRadius: 4,
                        border: "1px solid #dedfd9",
                        fontSize: 12,
                      }}
                    />
                    <Bar
                      dataKey="amount"
                      fill="#316c65"
                      radius={[0, 3, 3, 0]}
                      maxBarSize={22}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel
              title="Spending by category"
              description="Document totals grouped by assigned category"
            >
              {analyticsQuery.isLoading ? (
                <div className="h-full animate-pulse rounded-sm bg-muted" />
              ) : !analytics?.categories.length ? (
                <div className="grid h-full place-items-center text-xs text-muted-foreground">
                  No category values yet.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={analytics.categories}
                    layout="vertical"
                    margin={{ top: 0, right: 20, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      horizontal={false}
                      stroke="#e8e9e4"
                    />
                    <XAxis
                      type="number"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 9, fill: "#8a9090" }}
                      tickFormatter={(value) => `$${Math.round(value / 1000)}k`}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={112}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 9, fill: "#737c7d" }}
                    />
                    <Tooltip
                      formatter={(value) => formatCurrency(Number(value))}
                      contentStyle={{
                        borderRadius: 4,
                        border: "1px solid #dedfd9",
                        fontSize: 12,
                      }}
                    />
                    <Bar
                      dataKey="amount"
                      radius={[0, 3, 3, 0]}
                      maxBarSize={22}
                    >
                      {(analytics.categories ?? []).map((category, index) => (
                        <Cell
                          key={category.name}
                          fill={chartColors[index % chartColors.length]}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel
              title="Document type distribution"
              description="Invoice and receipt count in the workspace"
            >
              {analyticsQuery.isLoading ? (
                <div className="mx-auto mt-10 h-40 w-40 animate-pulse rounded-full bg-muted" />
              ) : !analytics?.types.length ? (
                <div className="grid h-full place-items-center text-xs text-muted-foreground">
                  No document types yet.
                </div>
              ) : (
                <div className="relative h-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={analytics.types}
                        dataKey="count"
                        nameKey="name"
                        innerRadius={56}
                        outerRadius={82}
                        paddingAngle={4}
                        stroke="none"
                      >
                        {analytics.types.map((type, index) => (
                          <Cell
                            key={type.name}
                            fill={chartColors[index % chartColors.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
                    <div className="text-xl font-semibold">
                      {analytics.documentCount}
                    </div>
                    <div className="text-[9px] text-muted-foreground">
                      documents
                    </div>
                  </div>
                  <div className="absolute bottom-1 left-0 right-0 flex justify-center gap-5">
                    {analytics.types.map((type, index) => (
                      <div
                        key={type.name}
                        className="flex items-center gap-1.5 text-[10px] text-muted-foreground"
                      >
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{
                            background: chartColors[index % chartColors.length],
                          }}
                        />
                        {type.name} <b className="text-foreground">{type.count}</b>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </ChartPanel>
          </div>
        </>
      )}

      <p className="mt-5 text-[10px] text-muted-foreground">
        Charts use local sample data and are not live financial reporting.
      </p>
    </div>
  );
}