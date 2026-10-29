import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HardDrive, LockKeyhole, Server, Settings2, Trash2 } from 'lucide-react';
import { ErrorState, PageHeader } from '@/components/documind';
import { errorMessage } from '@/lib/api-client';
import { formatBytes } from '@/lib/format';
import { applyTheme, notify, readTheme, type Theme } from '@/lib/ui';
import { api, queryKeys } from '@/services/api';

function Section({ title, caption, icon: Icon, children }: { title: string; caption: string; icon: typeof Settings2; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex items-start gap-3 border-b border-border px-4 py-4 sm:px-5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sm bg-accent text-primary"><Icon size={16} /></span>
        <div><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-[10px] text-muted-foreground">{caption}</p></div>
      </div>
      <div className="space-y-3 p-4 text-xs leading-5 sm:p-5">{children}</div>
    </section>
  );
}

const Row = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex items-center justify-between gap-4 border-b border-border pb-2 last:border-0 last:pb-0"><span className="text-muted-foreground">{label}</span><span className="text-right font-medium">{value}</span></div>
);

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [confirming, setConfirming] = useState(false);
  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, staleTime: Infinity });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 30_000 });

  const clearAll = useMutation({
    mutationFn: api.deleteAllDocuments,
    onSuccess: (result) => {
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics'] });
      notify(`Deleted ${result.deleted} document${result.deleted === 1 ? '' : 's'}.`);
    },
    onError: (error) => notify(errorMessage(error), 'error'),
  });

  const chooseTheme = (value: Theme) => { setTheme(value); applyTheme(value); };
  const m = meta.data;

  return (
    <div className="page-enter">
      <PageHeader eyebrow="Your workspace" title="Settings" description="How your private workspace works, server status, and display preferences." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-5">
          <Section title="Your workspace" caption="Private to this browser. There are no user accounts." icon={LockKeyhole}>
            <p>This browser holds a random workspace key. The server only shows your documents to requests carrying that key, so other visitors cannot see your uploads. Clearing site data or using another browser starts a new, empty workspace.</p>
            <p className="text-muted-foreground">This is anonymous isolation for a demo, not account security. Please upload sample or synthetic documents only.</p>
            {meta.isError ? <ErrorState message={errorMessage(meta.error)} /> : m && (
              <div className="space-y-2 pt-1">
                <Row label="Automatic deletion" value={m.retention_hours ? `After ${m.retention_hours} hours` : 'Off (kept until you delete them)'} />
                <Row label="Max file size" value={formatBytes(m.max_upload_bytes)} />
                <Row label="Max pages per document" value={m.max_pages} />
                <Row label="Documents per workspace" value={m.max_documents_per_workspace || 'Unlimited'} />
                <Row label="Uploads per hour (per network)" value={m.upload_rate_limit_per_hour || 'Unlimited'} />
                <Row label="Ambiguous dates read as" value={m.date_order === 'DMY' ? 'Day first (03/04 = 3 April)' : 'Month first (03/04 = 4 March)'} />
              </div>
            )}
          </Section>

          <Section title="Delete your data" caption="Removes every document, extracted value and stored file in this workspace." icon={Trash2}>
            {!confirming ? (
              <button type="button" onClick={() => setConfirming(true)} className="rounded-sm border border-red-200 px-3 py-2 text-[11px] font-semibold text-red-700 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/40" data-testid="button-delete-all">Delete all my documents…</button>
            ) : (
              <div className="flex flex-wrap items-center gap-2" role="alert">
                <span className="text-red-700 dark:text-red-300">This cannot be undone.</span>
                <button type="button" disabled={clearAll.isPending} onClick={() => clearAll.mutate()} className="rounded-sm bg-red-700 px-3 py-2 text-[11px] font-semibold text-white hover:bg-red-800 disabled:opacity-50" data-testid="button-confirm-delete-all">{clearAll.isPending ? 'Deleting…' : 'Delete everything'}</button>
                <button type="button" onClick={() => setConfirming(false)} className="px-2 text-[11px] font-semibold text-muted-foreground">Cancel</button>
              </div>
            )}
          </Section>
        </div>

        <div className="space-y-5">
          <section className="rounded-md border border-border bg-card p-5">
            <div className="flex items-start gap-3"><Settings2 size={16} className="mt-0.5 text-primary" /><div><h2 className="text-sm font-semibold">Appearance</h2><p className="mt-1 text-[10px] text-muted-foreground">Saved in this browser.</p></div></div>
            <div className="mt-4 flex gap-2">
              {(['light', 'dark'] as const).map((t) => (
                <button key={t} type="button" onClick={() => chooseTheme(t)} aria-pressed={theme === t} className={`flex-1 rounded-sm border p-2 text-[10px] capitalize ${theme === t ? 'border-primary bg-accent text-primary' : 'border-border text-muted-foreground'}`} data-testid={`button-theme-${t}`}>{t}</button>
              ))}
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-5" data-testid="section-server-status">
            <div className="flex items-center gap-2 text-sm font-semibold"><Server size={15} className="text-primary" />Server status</div>
            {health.isError ? <p className="mt-3 text-xs text-red-700">Cannot reach the server.</p> : !health.data ? <div className="mt-3 h-16 animate-pulse rounded-sm bg-muted" /> : (
              <div className="mt-3 space-y-2 text-xs">
                {Object.entries(health.data.components).map(([name, c]) => (
                  <div key={name} className="flex items-center justify-between"><span className="capitalize text-muted-foreground">{name === 'ocr' ? 'OCR engine' : name}</span><span className={`inline-flex items-center gap-1.5 font-medium ${c.status === 'ok' ? 'text-[#386f58]' : 'text-red-700'}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{c.status === 'ok' ? 'Operational' : 'Unavailable'}</span></div>
                ))}
                <div className="flex items-center justify-between border-t border-border pt-2 text-[10px] text-muted-foreground"><span>API version</span><span>{health.data.version}</span></div>
              </div>
            )}
          </section>

          <section className="rounded-sm border border-border bg-card p-4 text-[10px] leading-5 text-muted-foreground">
            <div className="flex items-center gap-2 text-xs font-semibold text-foreground"><HardDrive size={14} className="text-primary" />Where data lives</div>
            <p className="mt-2">Documents, extracted values and page previews are stored on the DocuMind server. Only your theme choice and workspace key are stored in this browser.</p>
          </section>
        </div>
      </div>
    </div>
  );
}
