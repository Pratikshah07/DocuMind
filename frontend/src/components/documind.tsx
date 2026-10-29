/** Shared DocuMind UI pieces (status badges, states, page header). Styled like the original pages. */
import type { ReactNode } from 'react';
import { CircleAlert, FolderOpen, LoaderCircle } from 'lucide-react';
import { STATUS_LABEL } from '@/lib/format';
import type { DocumentStatus, FieldStatus } from '@/services/api';
import { isInProgress } from '@/services/api';

const STATUS_STYLE: Record<'ready' | 'review' | 'progress' | 'failed', string> = {
  ready: 'bg-[#eaf3ee] text-[#386f58] dark:bg-[#1d3329] dark:text-[#8fd0ad]',
  review: 'bg-[#f8f1e3] text-[#947037] dark:bg-[#3a2f1a] dark:text-[#e2bd7a]',
  progress: 'bg-[#edf2f5] text-[#526e7d] dark:bg-[#1e2a31] dark:text-[#9ab8c8]',
  failed: 'bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300',
};

export function statusTone(status: DocumentStatus): keyof typeof STATUS_STYLE {
  if (status === 'COMPLETED') return 'ready';
  if (status === 'NEEDS_REVIEW') return 'review';
  if (status === 'FAILED') return 'failed';
  return 'progress';
}

export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-1 text-[10px] font-semibold ${STATUS_STYLE[statusTone(status)]}`}
      data-testid={`status-${status.toLowerCase()}`}
    >
      {isInProgress(status) ? <LoaderCircle size={10} className="animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

const FIELD_STATUS_STYLE: Record<FieldStatus, string> = {
  ok: 'bg-[#eaf3ee] text-[#386f58] dark:bg-[#1d3329] dark:text-[#8fd0ad]',
  uncertain: 'bg-[#f8f1e3] text-[#947037] dark:bg-[#3a2f1a] dark:text-[#e2bd7a]',
  invalid: 'bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300',
  missing: 'bg-muted text-muted-foreground',
};
const FIELD_STATUS_LABEL: Record<FieldStatus, string> = { ok: 'OK', uncertain: 'Check', invalid: 'Invalid', missing: 'Missing' };

export function FieldStatusBadge({ status }: { status: FieldStatus }) {
  return <span className={`rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${FIELD_STATUS_STYLE[status]}`}>{FIELD_STATUS_LABEL[status]}</span>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <p className="mb-2 text-[11px] font-bold uppercase tracking-[.14em] text-primary">{eyebrow}</p>}
        <h1 className="text-[27px] font-semibold tracking-[-.035em] text-foreground sm:text-[31px]" data-testid="heading-page">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry, testid = 'status-error' }: { message: string; onRetry?: () => void; testid?: string }) {
  return (
    <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-sm border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200" data-testid={testid}>
      <span className="flex items-start gap-2"><CircleAlert size={16} className="mt-0.5 shrink-0" />{message}</span>
      {onRetry && <button onClick={onRetry} className="shrink-0 font-semibold underline" data-testid="button-retry">Try again</button>}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid min-h-[260px] place-items-center rounded-md border border-dashed border-border bg-card/50 p-8 text-center" data-testid="state-empty">
      <div className="max-w-sm">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-accent text-primary"><FolderOpen size={21} /></span>
        <h3 className="mt-4 text-base font-semibold">{title}</h3>
        <div className="mt-1.5 text-sm leading-6 text-muted-foreground">{body}</div>
        {action && <div className="mt-5">{action}</div>}
      </div>
    </div>
  );
}

export function LoadingRows({ rows = 4, height = 'h-12' }: { rows?: number; height?: string }) {
  return <div className="space-y-3" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className={`${height} animate-pulse rounded-sm bg-muted`} />)}</div>;
}

export function Metric({ label, value, caption, icon: Icon }: { label: string; value: ReactNode; caption: ReactNode; icon: typeof FolderOpen }) {
  return (
    <section className="rounded-md border border-border bg-card p-4 sm:p-5" data-testid={`metric-${label.toLowerCase().replaceAll(' ', '-')}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className="grid h-8 w-8 place-items-center rounded-sm bg-accent text-primary"><Icon size={16} /></span>
      </div>
      <div className="mt-3 text-[25px] font-semibold tracking-[-.04em]">{value}</div>
      <div className="mt-1 text-[11px] text-muted-foreground">{caption}</div>
    </section>
  );
}
