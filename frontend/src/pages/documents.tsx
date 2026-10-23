import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FileText, ReceiptText, Search, Upload } from "lucide-react";
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
    year: "numeric",
  });

const statuses: ProcessingStatus[] = [
  "Ready",
  "Processing",
  "Failed",
  "Review needed",
];

function confidenceFor(document: Document) {
  const values = document.fields
    .map((field) => field.confidence)
    .filter((value) => Number.isFinite(value) && value > 0);
  if (values.length === 0) return null;
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function Status({ status }: { status: ProcessingStatus }) {
  const styles = {
    Ready: "bg-[#eaf3ee] text-[#386f58]",
    "Review needed": "bg-[#f8f1e3] text-[#947037]",
    Processing: "bg-[#edf2f5] text-[#526e7d]",
    Failed: "bg-red-50 text-red-700",
  }[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] font-semibold ${styles}`}
      data-testid={`document-status-${status.toLowerCase().replaceAll(" ", "-")}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function Confidence({ document }: { document: Document }) {
  const score = confidenceFor(document);
  if (score === null) {
    return <span className="text-[10px] text-muted-foreground">Not available</span>;
  }
  return (
    <span className="inline-flex min-w-[76px] items-center gap-2 text-[10px]">
      <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted">
        <span
          className={`block h-full rounded-full ${score < 85 ? "bg-[#c49a50]" : "bg-primary"}`}
          style={{ width: `${score}%` }}
        />
      </span>
      <span className={score < 85 ? "text-[#947037]" : "text-muted-foreground"}>
        {score}%
      </span>
    </span>
  );
}

function DocumentCard({ document }: { document: Document }) {
  return (
    <article
      className="rounded-md border border-border bg-card p-4"
      data-testid={`card-document-${document.id}`}
    >
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">
          {document.type === "Receipt" ? (
            <ReceiptText size={16} />
          ) : (
            <FileText size={16} />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold">{document.name}</div>
          <div className="mt-1 truncate text-[10px] text-muted-foreground">
            {document.vendor} · {document.type}
          </div>
        </div>
        <Status status={document.status} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3 text-[10px]">
        <div>
          <div className="text-muted-foreground">Date</div>
          <div className="mt-1 font-medium">{formatDate(document.date)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Amount</div>
          <div className="mt-1 font-mono font-medium">
            {formatCurrency(document.amount)}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Confidence</div>
          <div className="mt-1">
            <Confidence document={document} />
          </div>
        </div>
        <Link
          href={`/app/documents/${document.id}`}
          className="inline-flex items-end justify-end gap-1 font-semibold text-primary"
          data-testid={`link-document-action-${document.id}`}
        >
          Review <ArrowUpRight size={13} />
        </Link>
      </div>
    </article>
  );
}

export default function DocumentsPage() {
  const query = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
  });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("All statuses");
  const [type, setType] = useState("All types");
  const [sort, setSort] = useState("Newest first");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const documents = useMemo(() => {
    const filtered = (query.data ?? []).filter((document) => {
      const matchesSearch = `${document.name} ${document.vendor} ${document.category}`
        .toLowerCase()
        .includes(search.trim().toLowerCase());
      const matchesStatus =
        status === "All statuses" || document.status === status;
      const matchesType = type === "All types" || document.type === type;
      const matchesFrom = !fromDate || document.date >= fromDate;
      const matchesTo = !toDate || document.date <= toDate;
      return (
        matchesSearch &&
        matchesStatus &&
        matchesType &&
        matchesFrom &&
        matchesTo
      );
    });

    return filtered.sort((left, right) => {
      switch (sort) {
        case "Oldest first":
          return left.date.localeCompare(right.date);
        case "Amount high to low":
          return right.amount - left.amount;
        case "Amount low to high":
          return left.amount - right.amount;
        case "Vendor A to Z":
          return left.vendor.localeCompare(right.vendor);
        case "Confidence high to low":
          return (confidenceFor(right) ?? -1) - (confidenceFor(left) ?? -1);
        default:
          return right.date.localeCompare(left.date);
      }
    });
  }, [query.data, search, status, type, sort, fromDate, toDate]);

  const clearFilters = () => {
    setSearch("");
    setStatus("All statuses");
    setType("All types");
    setSort("Newest first");
    setFromDate("");
    setToDate("");
  };

  return (
    <div className="page-enter">
      <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[.14em] text-primary">
            Your workspace
          </p>
          <h1
            className="text-[27px] font-semibold tracking-[-.035em] sm:text-[31px]"
            data-testid="heading-page"
          >
            Documents
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Search, review and organize every invoice and receipt.
          </p>
        </div>
        <Link
          href="/app/upload"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          data-testid="button-add-document"
        >
          <Upload size={15} />
          Upload documents
        </Link>
      </div>

      <section className="rounded-md border border-border bg-card">
        <div className="space-y-3 border-b border-border p-4">
          <label className="relative block">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search documents, vendors or categories…"
              aria-label="Search documents"
              className="h-10 w-full rounded-sm border border-border bg-background pl-9 pr-3 text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 sm:max-w-sm"
              data-testid="input-search-documents"
            />
          </label>

          <div className="flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                Status
              </span>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="h-9 min-w-32 rounded-sm border border-border bg-background px-2.5 text-[11px]"
                data-testid="select-filter-status"
              >
                <option>All statuses</option>
                {statuses.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                Type
              </span>
              <select
                value={type}
                onChange={(event) => setType(event.target.value)}
                className="h-9 min-w-28 rounded-sm border border-border bg-background px-2.5 text-[11px]"
                data-testid="select-filter-type"
              >
                <option>All types</option>
                <option>Invoice</option>
                <option>Receipt</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                From
              </span>
              <input
                type="date"
                value={fromDate}
                onChange={(event) => setFromDate(event.target.value)}
                className="h-9 rounded-sm border border-border bg-background px-2 text-[10px]"
                data-testid="input-filter-from-date"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                To
              </span>
              <input
                type="date"
                value={toDate}
                onChange={(event) => setToDate(event.target.value)}
                className="h-9 rounded-sm border border-border bg-background px-2 text-[10px]"
                data-testid="input-filter-to-date"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                Sort by
              </span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
                className="h-9 min-w-36 rounded-sm border border-border bg-background px-2.5 text-[11px]"
                data-testid="select-sort-documents"
              >
                <option>Newest first</option>
                <option>Oldest first</option>
                <option>Amount high to low</option>
                <option>Amount low to high</option>
                <option>Vendor A to Z</option>
                <option>Confidence high to low</option>
              </select>
            </label>
            <button
              type="button"
              onClick={clearFilters}
              className="h-9 px-2 text-[11px] font-semibold text-primary hover:underline"
              data-testid="button-clear-filters"
            >
              Clear filters
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between px-4 py-3 text-[10px] text-muted-foreground">
          <span data-testid="text-document-count">
            {query.isLoading ? "Loading documents…" : `${documents.length} documents`}
          </span>
          <span>Local demo data</span>
        </div>

        {query.isError ? (
          <div
            role="alert"
            className="m-4 flex items-center justify-between rounded-sm border border-red-200 bg-red-50 p-4 text-xs text-red-800"
            data-testid="status-documents-error"
          >
            <span>Documents could not be loaded from this browser.</span>
            <button
              onClick={() => void query.refetch()}
              className="font-semibold underline"
              data-testid="button-retry-documents"
            >
              Try again
            </button>
          </div>
        ) : query.isLoading ? (
          <div className="space-y-3 p-4">
            {[0, 1, 2, 3].map((row) => (
              <div
                key={row}
                className="h-14 animate-pulse rounded-sm bg-muted"
              />
            ))}
          </div>
        ) : documents.length === 0 ? (
          <div className="grid min-h-64 place-items-center px-5 py-10 text-center">
            <div>
              <FileText className="mx-auto text-muted-foreground" size={22} />
              <h2 className="mt-3 text-sm font-semibold">
                {(query.data ?? []).length === 0
                  ? "No documents yet"
                  : "No matching documents"}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {(query.data ?? []).length === 0
                  ? "Upload an invoice or receipt to start exploring the workflow."
                  : "Try changing your search or filters."}
              </p>
              {(query.data ?? []).length === 0 ? (
                <Link
                  href="/app/upload"
                  className="mt-4 inline-flex items-center gap-2 rounded-sm bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground"
                  data-testid="link-empty-upload"
                >
                  <Upload size={14} /> Upload documents
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="mt-4 text-xs font-semibold text-primary"
                  data-testid="button-empty-clear-filters"
                >
                  Clear filters
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[960px] border-collapse text-left">
                <thead className="border-y border-border bg-muted/35 text-[9px] font-semibold uppercase tracking-[.1em] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Document</th>
                    <th className="px-3 py-3 font-semibold">Type</th>
                    <th className="px-3 py-3 font-semibold">Vendor</th>
                    <th className="px-3 py-3 font-semibold">Date</th>
                    <th className="px-3 py-3 text-right font-semibold">Amount</th>
                    <th className="px-3 py-3 font-semibold">Status</th>
                    <th className="px-3 py-3 font-semibold">Confidence</th>
                    <th className="px-4 py-3 text-right font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {documents.map((document) => (
                    <tr
                      key={document.id}
                      className="transition-colors hover:bg-muted/30"
                      data-testid={`row-document-${document.id}`}
                    >
                      <td className="max-w-[250px] px-4 py-3">
                        <Link
                          href={`/app/documents/${document.id}`}
                          className="block truncate text-[11px] font-semibold hover:text-primary"
                          data-testid={`link-document-${document.id}`}
                        >
                          {document.name}
                        </Link>
                        <div className="mt-1 truncate text-[9px] text-muted-foreground">
                          {document.category}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-[10px]">{document.type}</td>
                      <td className="max-w-[150px] truncate px-3 py-3 text-[10px]">
                        {document.vendor}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-[10px]">
                        {formatDate(document.date)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[10px]">
                        {formatCurrency(document.amount)}
                      </td>
                      <td className="px-3 py-3">
                        <Status status={document.status} />
                      </td>
                      <td className="px-3 py-3">
                        <Confidence document={document} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/app/documents/${document.id}`}
                          className="inline-flex items-center gap-1 rounded-sm border border-border px-2 py-1.5 text-[10px] font-semibold hover:border-primary hover:text-primary"
                          aria-label={`Review ${document.name}`}
                          data-testid={`button-review-document-${document.id}`}
                        >
                          Review <ArrowUpRight size={12} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid gap-3 p-3 md:hidden">
              {documents.map((document) => (
                <DocumentCard key={document.id} document={document} />
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}