import { FileSearch, MessageSquareText, ScanText, Sparkles } from 'lucide-react';
import { Link } from 'wouter';
import { PageHeader } from '@/components/documind';

/** Document Q&A is planned (RAG over extracted page text) but not built yet; say so plainly. */
export default function ChatPage() {
  return (
    <div className="page-enter">
      <PageHeader eyebrow="Coming soon" title="Ask your documents" description="Question answering over your documents is planned but not available yet." />
      <section className="rounded-md border border-dashed border-border bg-card p-8 text-center" data-testid="chat-coming-soon">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-accent text-primary"><MessageSquareText size={21} /></span>
        <h2 className="mt-4 text-base font-semibold">Not available in this version</h2>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
          The plan is retrieval-augmented answers over the page text DocuMind already extracts, with every answer citing its source document and page, and totals answered from the database rather than guessed by a model. Until that is built, this page does not answer questions.
        </p>
        <div className="mx-auto mt-6 grid max-w-2xl gap-3 text-left sm:grid-cols-3">
          {[
            [ScanText, 'Already working', 'Text, fields and line items are extracted from every document.'],
            [FileSearch, 'Next', 'Embed page text and retrieve relevant passages per question.'],
            [Sparkles, 'Then', 'Answer with a local LLM, citing document and page.'],
          ].map(([Icon, title, body]: any) => (
            <div key={title} className="rounded-sm border border-border p-3"><Icon size={15} className="text-primary" /><div className="mt-2 text-xs font-semibold">{title}</div><p className="mt-1 text-[11px] leading-5 text-muted-foreground">{body}</p></div>
          ))}
        </div>
        <Link href="/app/documents" className="mt-6 inline-flex items-center gap-2 rounded-sm bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground">Review your documents</Link>
      </section>
    </div>
  );
}
