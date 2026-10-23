import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleAlert,
  CloudUpload,
  FileText,
  LoaderCircle,
  RotateCcw,
  X,
} from "lucide-react";
import { Link } from "wouter";
import { api } from "@/services/api";

const acceptedExtensions = /\.(pdf|png|jpe?g)$/i;
const stages = [
  { label: "Uploading", percent: 12 },
  { label: "Processing", percent: 28 },
  { label: "OCR", percent: 46 },
  { label: "Extracting", percent: 68 },
  { label: "Validating", percent: 88 },
  { label: "Completed", percent: 100 },
] as const;

type QueueItem = {
  id: string;
  name: string;
  stage: string;
  percent: number;
  state: "working" | "done" | "failed";
};

function pause(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function notify(message: string, kind: "success" | "error" = "success") {
  window.dispatchEvent(
    new CustomEvent("documind-toast", { detail: { message, kind } }),
  );
}

export default function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [error, setError] = useState("");

  const updateQueueItem = (id: string, patch: Partial<QueueItem>) => {
    setQueue((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  };

  const startUploads = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;
    const supported = files.filter((file) => acceptedExtensions.test(file.name));
    const rejected = files.length - supported.length;
    if (rejected > 0) {
      setError(
        `${rejected} file${rejected === 1 ? "" : "s"} skipped. Choose PDF, PNG or JPG files.`,
      );
    } else {
      setError("");
    }
    if (supported.length === 0) return;

    setBusy(true);
    try {
      const documents = await api.addDocuments(supported);
      const newItems = documents.map((document) => ({
        id: document.id,
        name: document.name,
        stage: "Queued",
        percent: 0,
        state: "working" as const,
      }));
      setQueue((current) => [...newItems, ...current]);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });

      for (const document of documents) {
        try {
          for (const stage of stages) {
            updateQueueItem(document.id, {
              stage: stage.label,
              percent: stage.percent,
              state: "working",
            });
            await pause(280);
            if (stage.label === "Completed") {
              await api.finishDemoProcessing(document.id);
              updateQueueItem(document.id, { state: "done" });
            }
          }
        } catch {
          updateQueueItem(document.id, {
            stage: "Failed",
            state: "failed",
          });
        }
      }

      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });
      if (rejected < files.length) {
        notify(
          `${supported.length} file${supported.length === 1 ? "" : "s"} added to the local demo.`,
        );
      }
    } catch {
      setError("The demo could not add those filenames to browser storage.");
      notify("Upload could not be simulated. Try again.", "error");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event: React.DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!busy) void startUploads(event.dataTransfer.files);
  };

  return (
    <div className="page-enter">
      <div className="mb-7">
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[.14em] text-primary">
          Bring in a file
        </p>
        <h1
          className="text-[27px] font-semibold tracking-[-.035em] sm:text-[31px]"
          data-testid="heading-page"
        >
          Upload documents
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Add invoices and receipts to explore the document review workflow.
        </p>
      </div>

      <section className="rounded-md border border-border bg-card p-4 sm:p-6">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          multiple
          className="sr-only"
          onChange={(event) => {
            if (event.target.files) void startUploads(event.target.files);
            event.target.value = "";
          }}
          data-testid="input-upload-files"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (event.currentTarget === event.target) setDragging(false);
          }}
          onDrop={onDrop}
          disabled={busy}
          className={`flex min-h-[280px] w-full flex-col items-center justify-center rounded-sm border border-dashed px-5 py-9 text-center transition-colors disabled:cursor-wait disabled:opacity-70 ${dragging ? "border-primary bg-accent/60" : "border-border bg-background hover:border-primary/60 hover:bg-muted/30"}`}
          aria-label="Choose or drop invoice and receipt files"
          data-testid="dropzone-upload"
        >
          <span className="grid h-12 w-12 place-items-center rounded-full bg-accent text-primary">
            {busy ? (
              <LoaderCircle size={22} className="animate-spin" />
            ) : (
              <CloudUpload size={22} />
            )}
          </span>
          <span className="mt-4 text-sm font-semibold">
            {dragging ? "Drop files to add them" : "Drop files here or browse"}
          </span>
          <span className="mt-2 text-xs text-muted-foreground">
            Upload multiple documents at once
          </span>
          <span className="mt-4 flex flex-wrap justify-center gap-2">
            {["PDF", "PNG", "JPG", "JPEG"].map((format) => (
              <span
                key={format}
                className="rounded-sm border border-border bg-card px-2 py-1 text-[9px] font-semibold text-muted-foreground"
              >
                {format}
              </span>
            ))}
          </span>
        </button>

        <div className="mt-4 flex items-start gap-2 rounded-sm border border-[#e6dfce] bg-[#faf8f1] p-3 text-[10px] leading-5 text-muted-foreground">
          <CircleAlert size={14} className="mt-0.5 shrink-0 text-[#927342]" />
          <span>
            This is a local demo. Files are not uploaded to a server or read by
            OCR; only their filenames are saved in this browser, and extracted
            values are illustrative.
          </span>
        </div>

        {error && (
          <div
            className="mt-4 flex items-start gap-2 rounded-sm border border-red-200 bg-red-50 p-3 text-xs text-red-800"
            role="alert"
            data-testid="status-upload-error"
          >
            <CircleAlert size={14} className="mt-0.5 shrink-0" />
            {error}
            <button
              type="button"
              onClick={() => setError("")}
              className="ml-auto"
              aria-label="Dismiss upload error"
              data-testid="button-dismiss-upload-error"
            >
              <X size={14} />
            </button>
          </div>
        )}
      </section>

      <section className="mt-5 rounded-md border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-5">
          <div>
            <h2 className="text-sm font-semibold">Upload queue</h2>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {queue.length > 0
                ? "Illustrative processing status for this browser session."
                : "Your selected files will appear here."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {queue.some((item) => item.state === "done") && (
              <button
                type="button"
                onClick={() =>
                  setQueue((current) =>
                    current.filter((item) => item.state !== "done"),
                  )
                }
                className="text-[10px] font-semibold text-muted-foreground hover:text-foreground"
                data-testid="button-clear-completed"
              >
                Clear completed
              </button>
            )}
            <span className="rounded-sm border border-border px-2 py-1 text-[9px] text-muted-foreground">
              {queue.length} files
            </span>
          </div>
        </div>

        {queue.length === 0 ? (
          <div className="p-7 text-center">
            <FileText className="mx-auto text-muted-foreground" size={21} />
            <p className="mt-2 text-xs font-medium">No uploads in this session</p>
            <p className="mt-1 text-[10px] text-muted-foreground">
              Choose supported files to see each demo processing stage.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {queue.map((item) => (
              <div
                key={item.id}
                className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5"
                data-testid={`upload-item-${item.id}`}
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm border border-border bg-background text-primary">
                  {item.state === "done" ? (
                    <Check size={16} />
                  ) : item.state === "failed" ? (
                    <CircleAlert size={16} className="text-red-700" />
                  ) : (
                    <FileText size={16} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-semibold">{item.name}</div>
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span>{item.stage}</span>
                    <span>·</span>
                    <span>{item.percent}%</span>
                  </div>
                  <div
                    className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-label={`${item.name} progress`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={item.percent}
                  >
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${item.state === "failed" ? "bg-red-600" : "bg-primary"}`}
                      style={{ width: `${item.percent}%` }}
                    />
                  </div>
                </div>
                <span
                  className={`shrink-0 text-[10px] font-semibold ${item.state === "done" ? "text-[#386f58]" : item.state === "failed" ? "text-red-700" : "text-muted-foreground"}`}
                  data-testid={`status-upload-${item.id}`}
                >
                  {item.state === "done"
                    ? "Completed"
                    : item.state === "failed"
                      ? "Needs retry"
                      : "In progress"}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="mt-5 flex justify-end">
        <Link
          href="/app/documents"
          className="inline-flex items-center gap-2 text-xs font-semibold text-primary hover:underline"
          data-testid="link-upload-documents"
        >
          View documents <RotateCcw size={13} />
        </Link>
      </div>
    </div>
  );
}