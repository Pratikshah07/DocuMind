import { type ComponentType, type ReactNode, useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import {
  ArrowDown, ArrowRight, ArrowLeft, BarChart3, Check, CircleAlert, CloudUpload, FileCheck2, FileText, Github,
  LayoutDashboard, LockKeyhole, Menu, MessageSquareText, Plus, ScanText, Settings, ShieldCheck, TriangleAlert, X,
} from 'lucide-react';
import { Link, Route, Switch, useLocation } from 'wouter';
import { ErrorBoundary } from '@/components/error-boundary';
import { TooltipProvider } from '@/components/ui/tooltip';
import { buttonBase } from '@/lib/ui';
import AnalyticsPage from '@/pages/analytics';
import ChatPage from '@/pages/chat';
import DashboardPage from '@/pages/dashboard';
import DocumentDetailPage from '@/pages/document-detail';
import DocumentsPage from '@/pages/documents';
import SettingsPage from '@/pages/settings';
import UploadPage from '@/pages/upload';
import { api, queryKeys } from '@/services/api';

const REPO_URL = 'https://github.com/Pratikshah07/DocuMind';
const SAMPLES_URL = `${REPO_URL}/tree/main/backend/samples`;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // Don't retry client errors (404/409/422); retry transient ones once.
      retry: (count, error) => count < 1 && !(error && 'status' in error && Number((error as { status: number }).status) >= 400 && Number((error as { status: number }).status) < 500),
    },
  },
});

function ToastViewport() {
  const [items, setItems] = useState<{ id: number; message: string; kind: string }[]>([]);
  useEffect(() => {
    const listener = (event: Event) => {
      const { message, kind } = (event as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setItems((old) => [...old, { id, message, kind }]);
      window.setTimeout(() => setItems((old) => old.filter((item) => item.id !== id)), 4000);
    };
    window.addEventListener('documind-toast', listener);
    return () => window.removeEventListener('documind-toast', listener);
  }, []);
  return (
    <div className="fixed bottom-5 right-5 z-[100] flex w-[min(360px,calc(100vw-40px))] flex-col gap-2" aria-live="polite">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-3 rounded-md border border-border bg-card px-4 py-3 text-sm shadow-lg">
          <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full ${item.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-accent text-primary'}`}>{item.kind === 'error' ? <CircleAlert size={15} /> : <Check size={15} />}</span>
          <span data-testid="status-toast">{item.message}</span>
        </div>
      ))}
    </div>
  );
}

function Wordmark({ large = false }: { large?: boolean }) {
  return <span className={`inline-flex items-center gap-2.5 font-semibold tracking-tight ${large ? 'text-[19px]' : 'text-[16px]'}`}><span className={`grid place-items-center rounded-md bg-primary text-primary-foreground ${large ? 'h-9 w-9' : 'h-8 w-8'}`}><ScanText size={large ? 20 : 18} /></span>documind</span>;
}

// --- Landing --------------------------------------------------------------------------

function Landing() {
  const workflow = [
    { n: '01', title: 'Upload', body: 'Drop in a PDF, a scanned invoice or a phone photo of a receipt. Type and size are checked from the file content.', icon: CloudUpload },
    { n: '02', title: 'Extract', body: 'Text comes from the PDF or Tesseract OCR; vendor, dates, totals, tax and line items become structured fields.', icon: ScanText },
    { n: '03', title: 'Review', body: 'Every value shows its confidence and where it came from. Fix anything that needs it and save.', icon: FileCheck2 },
    { n: '04', title: 'Analyze', body: 'Search your documents and see spending by month and vendor, calculated from the extracted values.', icon: BarChart3 },
  ];
  const features = [
    ['Reliable extraction', 'Deterministic rules read invoices and receipts in common US, EU and Indian formats, with no invented values.'],
    ['Confidence you can inspect', 'Each field says whether it is OK, uncertain, invalid or missing, and how it was found.'],
    ['Problems are flagged, not hidden', 'Totals that don’t add up, ambiguous dates and conflicting values are marked for review instead of silently corrected.'],
  ];
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-[68px] max-w-[1220px] items-center justify-between px-5 lg:px-8">
          <Link href="/" className="text-foreground"><Wordmark large /></Link>
          <nav className="hidden items-center gap-8 text-[13px] font-medium text-muted-foreground md:flex"><a href="#how-it-works" className="hover:text-foreground">How it works</a><a href="#features" className="hover:text-foreground">Features</a><a href="#technology" className="hover:text-foreground">Technology</a></nav>
          <div className="flex items-center gap-2">
            <a href={REPO_URL} target="_blank" rel="noreferrer" className={`${buttonBase} hidden text-muted-foreground hover:bg-muted hover:text-foreground sm:inline-flex`} data-testid="link-github"><Github size={16} />GitHub</a>
            <Link href="/app/dashboard" className={`${buttonBase} bg-primary text-primary-foreground hover:bg-primary/90`} data-testid="link-try-demo">Open the app <ArrowRight size={16} /></Link>
          </div>
        </div>
      </header>
      <main>
        <section className="relative overflow-hidden">
          <div className="subtle-grid absolute inset-0 opacity-50" />
          <div className="relative mx-auto grid max-w-[1220px] items-center gap-12 px-5 pb-20 pt-14 lg:grid-cols-[.86fr_1.14fr] lg:gap-10 lg:px-8 lg:pb-24 lg:pt-20">
            <div className="page-enter max-w-[500px]">
              <div className="mb-6 inline-flex items-center gap-2 rounded-sm border border-border bg-card/85 px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-[.11em] text-muted-foreground"><span className="h-1.5 w-1.5 rounded-full bg-primary" /><span>Document intelligence workspace</span></div>
              <h1 className="max-w-[540px] text-[45px] font-semibold leading-[1.04] tracking-[-.052em] sm:text-[58px]">Turn Documents<br className="hidden sm:block" /> Into Data</h1>
              <p className="mt-6 max-w-[465px] text-[16px] leading-7 text-muted-foreground">Upload invoices and receipts. DocuMind reads them, with OCR for scans and photos, extracts structured fields and line items, checks the arithmetic and tells you exactly what needs a second look.</p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link href="/app/upload" className={`${buttonBase} bg-primary px-5 py-3 text-primary-foreground hover:bg-primary/90`} data-testid="link-hero-demo">Try it with a document <ArrowRight size={16} /></Link>
                <a href="#how-it-works" className={`${buttonBase} border border-border bg-card/80 px-5 py-3 text-foreground hover:bg-muted`}>See how it works <ArrowDown size={15} /></a>
              </div>
              <div className="mt-8 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><ShieldCheck size={15} className="text-primary" /> Uploads are private to your browser <span className="text-border">·</span> <a href={SAMPLES_URL} target="_blank" rel="noreferrer" className="underline hover:text-foreground">Synthetic sample documents</a></div>
            </div>
            <div className="page-enter relative mx-auto w-full max-w-[635px] [animation-delay:120ms]" aria-hidden="true">
              <div className="absolute -inset-4 rounded-xl bg-[hsl(var(--primary)/.08)] blur-2xl" />
              <div className="relative overflow-hidden rounded-lg border border-border bg-card shadow-[0_18px_50px_rgba(38,54,64,.12)]">
                <div className="flex h-12 items-center justify-between border-b border-border px-4"><div className="flex items-center gap-2"><Wordmark /><span className="ml-2 border-l border-border pl-3 text-[11px] text-muted-foreground">Workspace</span></div><div className="flex gap-1.5"><span className="h-2 w-2 rounded-full bg-[#d3d5ce]" /><span className="h-2 w-2 rounded-full bg-[#d3d5ce]" /><span className="h-2 w-2 rounded-full bg-[#d3d5ce]" /></div></div>
                <div className="grid min-h-[350px] grid-cols-[150px_1fr] sm:grid-cols-[178px_1fr]">
                  <aside className="border-r border-border bg-[#fafaf7] p-3 dark:bg-muted/30"><div className="mb-4 rounded-sm bg-primary px-3 py-2.5 text-xs font-semibold text-white"><LayoutDashboard size={14} className="mr-2 inline" />Overview</div>{([['Documents', FileText], ['Analytics', BarChart3], ['Upload', CloudUpload]] as const).map(([label, Icon]) => <div key={label} className="mb-1 flex items-center gap-2.5 rounded-sm px-3 py-2 text-[11px] text-muted-foreground"><Icon size={14} />{label}</div>)}</aside>
                  <div className="p-4 sm:p-5">
                    <div className="text-[9px] font-bold uppercase tracking-[.13em] text-primary">Overview</div>
                    <div className="mt-1 text-[18px] font-semibold tracking-tight">Your documents at a glance</div>
                    <div className="mt-5 grid grid-cols-3 gap-2"><PreviewMetric label="Documents" value="3" note="Synthetic samples" /><PreviewMetric label="Ready" value="2" note="All checks passed" /><PreviewMetric label="Need review" value="1" note="Totals don’t add up" /></div>
                    <div className="mt-3 rounded border border-border p-3"><div className="flex justify-between text-[10px] font-semibold"><span>Recent documents</span><span className="text-primary">View all</span></div>{[['Northstar Studio LLC', 'Invoice · Ready', '$4,820.00'], ['Fieldnotes Coffee', 'Receipt · Ready', '$17.86'], ['Harbor Freight Logistics', 'Invoice · Review needed', '$2,295.00']].map((r, i) => <div key={r[0]} className="flex items-center border-b border-border/70 py-2.5 last:border-0"><span className="mr-2.5 grid h-6 w-6 place-items-center rounded-sm bg-muted text-primary"><FileText size={12} /></span><span className="min-w-0 flex-1"><b className="block truncate text-[9px] font-semibold">{r[0]}</b><small className="text-[8px] text-muted-foreground">{r[1]}</small></span><span className="text-[9px] font-medium">{r[2]}</span><span className={`ml-2 h-1.5 w-1.5 rounded-full ${i === 2 ? 'bg-[#d49a44]' : 'bg-primary'}`} /></div>)}</div>
                    <div className="mt-3 flex items-center gap-2 rounded border border-[#e7d9b8] bg-[#fbf6ea] p-2.5 text-[9px] text-[#7d5d27] dark:border-border dark:bg-muted/40"><TriangleAlert size={13} /><span>Totals don’t add up: subtotal 2,035.00 + tax 160.00 = 2,195.00, but the total is 2,295.00.</span></div>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-center gap-2 text-[10px] text-muted-foreground"><span className="h-1.5 w-1.5 rounded-full bg-primary" /> Illustration using the synthetic sample documents</div>
            </div>
          </div>
        </section>
        <section className="border-y border-border bg-[#f2f2ed] dark:bg-muted/30"><div className="mx-auto grid max-w-[1220px] gap-6 px-5 py-7 sm:grid-cols-3 lg:px-8"><Proof label="BUILT FOR" value="Invoices & receipts" /><Proof label="READS" value="PDF text layers + Tesseract OCR" /><Proof label="WORKFLOW" value="Upload · Review · Analyze" /></div></section>
        <section id="how-it-works" className="mx-auto max-w-[1220px] scroll-mt-20 px-5 py-20 lg:px-8 lg:py-24"><SectionLead eyebrow="A dependable workflow" title="From scattered files to clear records." body="The document stays next to its data, so you can move quickly without losing the details that matter." /><div className="mt-12 grid gap-0 md:grid-cols-4">{workflow.map((item, i) => <div key={item.title} className={`relative border-t border-border pt-5 md:mr-8 ${i === 3 ? 'md:mr-0' : ''}`}><span className="font-mono text-[11px] text-primary">{item.n}</span><item.icon className="absolute right-0 top-5 text-primary" size={18} /><h3 className="mt-7 text-[19px] font-semibold tracking-tight">{item.title}</h3><p className="mt-2 max-w-[240px] text-sm leading-6 text-muted-foreground">{item.body}</p></div>)}</div></section>
        <section id="features" className="scroll-mt-20 border-y border-border bg-[#f3f4f0] dark:bg-muted/30"><div className="mx-auto grid max-w-[1220px] gap-10 px-5 py-20 lg:grid-cols-[.75fr_1.25fr] lg:px-8 lg:py-24"><SectionLead eyebrow="Designed for the details" title="Structured enough to trust. Simple enough to use." body="DocuMind keeps the source page and the extracted values together, so a review is quick." /><div className="divide-y divide-border">{features.map((feature, i) => <div key={feature[0]} className="flex gap-5 py-5 first:pt-0 last:pb-0"><span className="font-mono text-[11px] text-primary">0{i + 1}</span><div><h3 className="text-[16px] font-semibold">{feature[0]}</h3><p className="mt-1.5 max-w-lg text-sm leading-6 text-muted-foreground">{feature[1]}</p></div></div>)}</div></div></section>
        <section className="mx-auto grid max-w-[1220px] gap-12 px-5 py-20 lg:grid-cols-2 lg:items-center lg:px-8 lg:py-24">
          <div className="relative rounded-lg border border-border bg-[#f2f0e9] p-7 dark:bg-muted/30 sm:p-9" aria-hidden="true"><div className="absolute right-6 top-6 rounded-sm border border-border bg-card px-2.5 py-1.5 text-[10px] font-semibold text-primary">EXAMPLE</div><div className="mt-4 max-w-[300px] bg-white p-5 shadow-sm"><div className="h-2 w-24 bg-[#d8d9d4]" /><div className="mt-2 h-1.5 w-32 bg-[#ecece8]" /><div className="mt-7 flex justify-between"><div className="h-1.5 w-16 bg-[#e6e6e1]" /><div className="h-1.5 w-10 bg-[#e6e6e1]" /></div><div className="mt-3 h-1.5 w-full bg-[#eeefeb]" /><div className="mt-2 h-1.5 w-full bg-[#eeefeb]" /><div className="mt-7 flex justify-between rounded-sm border-l-2 border-primary bg-[#f3f8f6] p-2.5 text-[#1e332f]"><span className="text-[10px] font-medium">Total due</span><span className="font-mono text-[11px] font-semibold">$4,820.00</span></div></div><div className="absolute bottom-8 right-6 w-[47%] rounded-md border border-border bg-card p-3.5 shadow-md sm:right-12"><div className="mb-2 flex items-center justify-between text-[10px] font-semibold">Total <span className="rounded-sm bg-accent px-1.5 py-1 text-[9px] text-primary">95% high</span></div><div className="rounded-sm border border-border px-2.5 py-2 text-[12px]">4,820.00 USD</div><div className="mt-1.5 text-[9px] text-muted-foreground">Found next to a label · page 1</div></div></div>
          <div><SectionLead eyebrow="Human review, where it counts" title="Confidence belongs beside the value." body="Each field shows a confidence score (a transparent heuristic, not a promise of accuracy) and where it came from. Edit anything that’s wrong; validation re-runs when you save." /><div className="mt-7"><Link href="/app/documents" className="inline-flex items-center gap-2 text-sm font-semibold text-primary hover:gap-3" data-testid="link-features-documents">Go to your documents <ArrowRight size={16} /></Link></div></div>
        </section>
        <section className="border-y border-border bg-[#f3f4f0] dark:bg-muted/30">
          <div className="mx-auto grid max-w-[1220px] gap-12 px-5 py-20 lg:grid-cols-2 lg:items-center lg:px-8 lg:py-24">
            <div><SectionLead eyebrow="Validation" title="Numbers are checked, not trusted." body="Subtotal + tax − discount must equal the total, line items must add up, dates must exist and be in order. Anything ambiguous, such as 03/04/2025, is flagged for review instead of guessed silently." /></div>
            <div className="space-y-2 rounded-md border border-border bg-card p-4 text-xs shadow-sm" aria-hidden="true">
              {[['Totals don’t add up: subtotal 2,035.00 + tax 160.00 = 2,195.00, but the total is 2,295.00.', 'totals_mismatch'], ['Invoice date ‘03/04/2025’ is ambiguous: read as 2025-04-03, but it could also be 2025-03-04.', 'ambiguous_date'], ['No invoice number was found.', 'missing_required_field']].map(([message, code]) => (
                <div key={code} className="flex items-start gap-2 rounded-sm border border-[#e7d9b8] bg-[#fbf6ea] p-3 text-[#6f5426] dark:border-border dark:bg-muted/40 dark:text-foreground"><TriangleAlert size={14} className="mt-0.5 shrink-0" /><div><div>{message}</div><div className="mt-1 font-mono text-[10px] opacity-70">{code}</div></div></div>
              ))}
              <p className="pt-1 text-[10px] text-muted-foreground">Real warning messages from the sample documents.</p>
            </div>
          </div>
        </section>
        <section id="technology" className="mx-auto max-w-[1220px] scroll-mt-20 px-5 py-16 lg:px-8"><div className="flex flex-col justify-between gap-8 md:flex-row md:items-center"><SectionLead eyebrow="Under the hood" title="A real pipeline, end to end." body="Content-checked uploads, background processing with observable status, OCR with image preprocessing, deterministic extraction and validation, all in PostgreSQL. Document Q&A with retrieval and an LLM is on the roadmap." /><div className="grid grid-cols-2 gap-x-8 gap-y-5 text-sm">{[['Interface', 'React + TypeScript'], ['API', 'FastAPI + PostgreSQL'], ['Reading', 'PyMuPDF + Tesseract'], ['Images', 'OpenCV preprocessing']].map((x) => <div key={x[0]}><div className="text-[10px] uppercase tracking-[.13em] text-muted-foreground">{x[0]}</div><div className="mt-1 font-medium">{x[1]}</div></div>)}</div></div></section>
        <section className="mx-auto max-w-[1220px] px-5 pb-20 lg:px-8 lg:pb-24"><div className="flex flex-col items-start justify-between gap-8 rounded-md border border-border bg-card p-7 sm:p-10 md:flex-row md:items-center"><div><p className="text-[11px] font-bold uppercase tracking-[.14em] text-primary">Try it now</p><h2 className="mt-3 text-3xl font-semibold tracking-[-.04em]">Upload a sample invoice.</h2><p className="mt-3 max-w-lg text-sm leading-6 text-muted-foreground">Download one of the <a href={SAMPLES_URL} target="_blank" rel="noreferrer" className="font-semibold text-primary underline">synthetic sample documents</a> and watch it being processed. Please don’t upload real personal or financial documents to this public demo.</p></div><Link href="/app/upload" className={`${buttonBase} shrink-0 bg-primary px-5 py-3 text-primary-foreground hover:bg-primary/90`} data-testid="link-final-demo">Open the uploader <ArrowRight size={16} /></Link></div></section>
      </main>
      <footer className="border-t border-border"><div className="mx-auto flex max-w-[1220px] flex-col gap-4 px-5 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between lg:px-8"><Link href="/" className="text-foreground"><Wordmark /></Link><span>DocuMind · portfolio project · use synthetic documents</span><a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 hover:text-foreground" data-testid="link-footer-github"><Github size={14} /> Source code</a></div></footer>
    </div>
  );
}
function PreviewMetric({ label, value, note }: { label: string; value: string; note: string }) { return <div className="rounded border border-border p-2.5"><div className="text-[8px] text-muted-foreground">{label}</div><div className="mt-1 text-[15px] font-semibold tracking-tight">{value}</div><div className="mt-1 text-[8px] text-primary">{note}</div></div>; }
function Proof({ label, value }: { label: string; value: string }) { return <div className="flex items-center gap-4 sm:block"><span className="text-[9px] font-bold tracking-[.15em] text-muted-foreground">{label}</span><span className="text-[13px] font-semibold sm:mt-1.5 sm:block">{value}</span></div>; }
function SectionLead({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) { return <div className="max-w-[490px]"><p className="mb-3 text-[11px] font-bold uppercase tracking-[.14em] text-primary">{eyebrow}</p><h2 className="text-[28px] font-semibold leading-[1.12] tracking-[-.04em] sm:text-[34px]">{title}</h2><p className="mt-4 text-sm leading-6 text-muted-foreground">{body}</p></div>; }

// --- App shell -----------------------------------------------------------------------

const navItems = [
  { href: '/app/dashboard', label: 'Overview', icon: LayoutDashboard },
  { href: '/app/documents', label: 'Documents', icon: FileText },
  { href: '/app/upload', label: 'Upload', icon: CloudUpload },
  { href: '/app/analytics', label: 'Analytics', icon: BarChart3 },
  { href: '/app/chat', label: 'Ask your data', icon: MessageSquareText, soon: true },
];
const TITLES: Record<string, string> = { '/app/dashboard': 'Overview', '/app/documents': 'Documents', '/app/upload': 'Upload documents', '/app/analytics': 'Analytics', '/app/chat': 'Ask your documents', '/app/settings': 'Settings' };

function ServerIndicator() {
  const health = useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 60_000 });
  const ok = health.data?.status === 'ok';
  const label = health.isLoading ? 'Connecting…' : health.isError ? 'Server unavailable' : ok ? 'Connected' : 'Partially available';
  return <span className="hidden items-center gap-1.5 text-[11px] text-muted-foreground sm:flex" data-testid="status-server" title={health.isError ? 'The DocuMind API is not reachable' : undefined}><span className={`h-1.5 w-1.5 rounded-full ${health.isError ? 'bg-red-600' : ok ? 'bg-primary' : 'bg-[#c49a50]'}`} />{label}</span>;
}

function NavLinks({ location, onNavigate, count }: { location: string; onNavigate?: () => void; count?: number }) {
  return (
    <>
      {navItems.map(({ href, label, icon: Icon, soon }) => (
        <Link key={href} href={href} onClick={onNavigate} className={`mb-1 flex h-10 items-center gap-3 rounded-sm px-3 text-[13px] font-medium transition-colors ${location === href ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`} data-testid={`nav-${label.toLowerCase().replaceAll(' ', '-')}`}>
          <Icon size={17} strokeWidth={1.8} />{label}
          {label === 'Documents' && count !== undefined && <span className="ml-auto text-[10px] text-muted-foreground">{String(count).padStart(2, '0')}</span>}
          {soon && <span className="ml-auto rounded-sm border border-border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">Soon</span>}
        </Link>
      ))}
    </>
  );
}

function AppShell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const overview = useQuery({ queryKey: queryKeys.analytics('overview'), queryFn: api.analyticsOverview });
  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, staleTime: Infinity });
  const title = TITLES[location] ?? 'Document review';
  const privacyNote = meta.data?.demo_mode
    ? `Only this browser can see your uploads. They are deleted after ${meta.data.retention_hours} h.`
    : 'Documents are stored on this DocuMind server.';
  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[236px] flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:flex">
        <div className="flex h-[68px] items-center border-b border-sidebar-border px-5"><Link href="/" className="text-foreground"><Wordmark large /></Link></div>
        <div className="px-3 pt-6"><div className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[.14em] text-muted-foreground">Workspace</div><NavLinks location={location} count={overview.data?.total_documents} /></div>
        <div className="mt-auto p-3">
          <div className="mb-3 rounded-sm border border-border/80 bg-card/50 p-3" data-testid="card-workspace-privacy"><div className="flex items-center gap-2 text-[11px] font-semibold"><LockKeyhole size={12} className="text-primary" />Private workspace</div><p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">{privacyNote}</p></div>
          <Link href="/app/settings" className={`flex h-10 items-center gap-3 rounded-sm px-3 text-[13px] font-medium ${location === '/app/settings' ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-muted'}`} data-testid="nav-settings"><Settings size={17} />Settings</Link>
          <Link href="/" className="mt-1 flex h-10 items-center gap-3 rounded-sm px-3 text-[13px] font-medium text-muted-foreground hover:bg-muted" data-testid="nav-home"><ArrowLeft size={16} />Back to home</Link>
        </div>
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 bg-foreground/25 lg:hidden" onClick={() => setMobileOpen(false)}>
          <div className="h-full w-[min(280px,85vw)] bg-sidebar p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between"><Link href="/app/dashboard" onClick={() => setMobileOpen(false)}><Wordmark large /></Link><button onClick={() => setMobileOpen(false)} aria-label="Close navigation" data-testid="button-close-menu"><X size={18} /></button></div>
            <div className="mt-8"><NavLinks location={location} onNavigate={() => setMobileOpen(false)} count={overview.data?.total_documents} /><Link href="/app/settings" onClick={() => setMobileOpen(false)} className="flex h-11 items-center gap-3 px-3 text-sm text-muted-foreground"><Settings size={17} />Settings</Link></div>
            <p className="mt-6 px-3 text-[10px] leading-4 text-muted-foreground">{privacyNote}</p>
          </div>
        </div>
      )}
      <div className="min-h-[100dvh] lg:pl-[236px]">
        <header className="sticky top-0 z-30 flex h-[61px] items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur sm:px-7">
          <div className="flex items-center gap-3"><button className="grid h-9 w-9 place-items-center rounded-sm text-muted-foreground hover:bg-muted lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation" data-testid="button-open-menu"><Menu size={19} /></button><div className="text-[13px] font-semibold">{title}</div><span className="hidden h-4 border-l border-border sm:block" /><ServerIndicator /></div>
          <div className="flex items-center gap-2">
            <Link href="/app/upload" className="inline-flex h-9 items-center gap-2 rounded-sm bg-primary px-3 text-[12px] font-semibold text-primary-foreground hover:bg-primary/90" data-testid="button-header-upload"><Plus size={15} /> <span className="hidden sm:inline">Upload documents</span><span className="sm:hidden">Upload</span></Link>
            <Link href="/app/settings" className="grid h-9 w-9 place-items-center rounded-sm border border-border bg-card text-primary" aria-label="Settings" data-testid="button-settings"><Settings size={15} /></Link>
          </div>
        </header>
        <main className="mx-auto max-w-[1360px] px-4 py-7 sm:px-7 sm:py-9">{children}</main>
      </div>
      <ToastViewport />
    </div>
  );
}

function NotFoundPage() {
  return <div className="grid min-h-[100dvh] place-items-center bg-background p-5"><div className="max-w-md text-center"><span className="font-mono text-xs text-primary">404 · Not found</span><h1 className="mt-3 text-3xl font-semibold tracking-tight">This page isn't in the workspace.</h1><p className="mt-3 text-sm leading-6 text-muted-foreground">The link may be out of date, or the document may have been removed.</p><Link href="/app/dashboard" className={`${buttonBase} mt-6 bg-primary text-primary-foreground`} data-testid="link-not-found-home">Back to workspace</Link></div></div>;
}
function RoutedErrorBoundary({ children }: { children: ReactNode }) { const [location] = useLocation(); return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>; }
const inShell = (Page: ComponentType) => () => <RoutedErrorBoundary><AppShell><Page /></AppShell></RoutedErrorBoundary>;

function Router() {
  return (
    <Switch>
      <Route path="/" component={Landing} />
      <Route path="/app" component={inShell(DashboardPage)} />
      <Route path="/app/dashboard" component={inShell(DashboardPage)} />
      <Route path="/app/documents" component={inShell(DocumentsPage)} />
      <Route path="/app/documents/:id" component={inShell(DocumentDetailPage)} />
      <Route path="/app/upload" component={inShell(UploadPage)} />
      <Route path="/app/analytics" component={inShell(AnalyticsPage)} />
      <Route path="/app/chat" component={inShell(ChatPage)} />
      <Route path="/app/settings" component={inShell(SettingsPage)} />
      <Route component={NotFoundPage} />
    </Switch>
  );
}

export default function App() {
  return <QueryClientProvider client={queryClient}><TooltipProvider><Router /></TooltipProvider></QueryClientProvider>;
}

