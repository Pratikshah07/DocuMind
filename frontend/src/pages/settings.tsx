import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BriefcaseBusiness,
  Check,
  CircleAlert,
  HardDrive,
  LockKeyhole,
  Settings2,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { api, type User } from "@/services/api";

function Section({
  title,
  caption,
  icon: Icon,
  children,
}: {
  title: string;
  caption: string;
  icon: typeof Settings2;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex items-start gap-3 border-b border-border px-4 py-4 sm:px-5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sm bg-accent text-primary">
          <Icon size={16} />
        </span>
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="mt-1 text-[10px] text-muted-foreground">{caption}</p>
        </div>
      </div>
      <div className="space-y-4 p-4 sm:p-5">{children}</div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  testId,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  testId: string;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[10px] font-semibold text-muted-foreground">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-sm border border-border bg-background px-3 text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
        data-testid={testId}
      />
    </label>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
  testId,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  testId: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <div className="text-xs font-medium">{label}</div>
        <div className="mt-1 text-[10px] text-muted-foreground">
          {description}
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? "bg-primary" : "bg-muted"}`}
        data-testid={testId}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-card shadow transition-transform ${checked ? "translate-x-[22px]" : "translate-x-0.5"}`}
        />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: api.profile,
  });
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [compactRows, setCompactRows] = useState(
    () => localStorage.getItem("documind-demo-compact") === "true",
  );
  const [processingNotifications, setProcessingNotifications] = useState(
    () => localStorage.getItem("documind-demo-notifications") !== "false",
  );

  useEffect(() => {
    if (profileQuery.data) setUser({ ...profileQuery.data });
  }, [profileQuery.data]);

  const saveProfile = useMutation({
    mutationFn: api.saveProfile,
    onSuccess: (savedUser) => {
      queryClient.setQueryData(["profile"], savedUser);
      window.dispatchEvent(
        new CustomEvent("documind-toast", {
          detail: {
            message: "Profile preferences saved locally.",
            kind: "success",
          },
        }),
      );
    },
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", user?.theme === "dark");
  }, [user?.theme]);

  const updateUser = (key: keyof User, value: string) => {
    setUser((current) => (current ? { ...current, [key]: value } : current));
  };
  const updateCompact = (value: boolean) => {
    setCompactRows(value);
    localStorage.setItem("documind-demo-compact", String(value));
  };
  const updateNotifications = (value: boolean) => {
    setProcessingNotifications(value);
    localStorage.setItem("documind-demo-notifications", String(value));
  };

  if (profileQuery.isError) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-5 text-sm text-red-800">
        Settings could not be loaded from this browser.
        <button
          onClick={() => void profileQuery.refetch()}
          className="ml-2 font-semibold underline"
          data-testid="button-settings-retry"
        >
          Try again
        </button>
      </div>
    );
  }

  if (profileQuery.isLoading || !user) {
    return (
      <div className="space-y-4" aria-label="Loading settings">
        <div className="h-10 w-48 animate-pulse rounded-sm bg-muted" />
        <div className="h-48 animate-pulse rounded-md bg-muted" />
      </div>
    );
  }

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
            Settings
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Manage your profile and local demo preferences.
          </p>
        </div>
        <button
          type="button"
          onClick={() => saveProfile.mutate(user)}
          disabled={saveProfile.isPending}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50"
          data-testid="button-save-settings"
        >
          <Check size={15} />
          {saveProfile.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-5">
          <Section
            title="Profile"
            caption="Personal details used in your workspace."
            icon={BriefcaseBusiness}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Full name"
                value={user.name}
                onChange={(value) => updateUser("name", value)}
                testId="input-profile-name"
              />
              <Field
                label="Email address"
                type="email"
                value={user.email}
                onChange={(value) => updateUser("email", value)}
                testId="input-profile-email"
              />
              <Field
                label="Workspace name"
                value={user.workspace}
                onChange={(value) => updateUser("workspace", value)}
                testId="input-workspace-name"
              />
              <label className="block">
                <span className="mb-1.5 block text-[10px] font-semibold text-muted-foreground">
                  Default currency
                </span>
                <select
                  value={user.currency}
                  onChange={(event) =>
                    updateUser("currency", event.target.value)
                  }
                  className="h-10 w-full rounded-sm border border-border bg-background px-3 text-xs outline-none focus:border-primary"
                  data-testid="select-currency"
                >
                  <option value="USD">USD · US Dollar</option>
                  <option value="EUR">EUR · Euro</option>
                  <option value="GBP">GBP · British Pound</option>
                  <option value="CAD">CAD · Canadian Dollar</option>
                </select>
              </label>
            </div>
          </Section>

          <Section
            title="Preferences"
            caption="Tune how information is shown in this browser."
            icon={SlidersHorizontal}
          >
            <Toggle
              label="Compact document rows"
              description="Show more records in the document list."
              checked={compactRows}
              onChange={updateCompact}
              testId="toggle-compact"
            />
            <Toggle
              label="Processing notifications"
              description="Show a notice when demo upload stages complete."
              checked={processingNotifications}
              onChange={updateNotifications}
              testId="toggle-notifications"
            />
          </Section>

          <Section
            title="AI settings"
            caption="Current capabilities and processing behavior."
            icon={Sparkles}
          >
            <div className="rounded-sm border border-[#e6dfce] bg-[#faf8f1] p-4">
              <div className="flex items-center gap-2 text-xs font-semibold">
                <CircleAlert size={14} className="text-[#927342]" />
                Demo extraction is simulated
              </div>
              <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
                No AI provider is connected. Uploads use illustrative sample
                values so you can explore the review workflow.
              </p>
              <div className="mt-3 border-t border-[#e9e4d8] pt-3 text-[10px] text-muted-foreground">
                Processing mode:{" "}
                <span className="font-semibold text-[#806637]">
                  local demo
                </span>
              </div>
            </div>
          </Section>

          <Section
            title="API settings"
            caption="Connection details for a future FastAPI backend."
            icon={LockKeyhole}
          >
            <div className="rounded-sm border border-border bg-background p-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium">Connection status</span>
                <span className="inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-1 text-[10px] text-muted-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#c49a50]" />
                  Not connected
                </span>
              </div>
              <div className="mt-3 border-t border-border pt-3">
                <div className="text-[10px] font-semibold text-muted-foreground">
                  Backend endpoint
                </div>
                <div className="mt-1 text-xs">Not configured</div>
              </div>
              <p className="mt-3 text-[10px] leading-5 text-muted-foreground">
                This demo does not accept or store API credentials. Configure
                backend credentials through secure environment settings when
                connecting a service.
              </p>
            </div>
          </Section>
        </div>

        <div className="space-y-5">
          <section className="rounded-md border border-border bg-card p-5">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-sm bg-accent font-semibold text-primary">
                {user.name
                  .split(" ")
                  .map((part) => part[0])
                  .join("")
                  .slice(0, 2)
                  .toUpperCase()}
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{user.name}</div>
                <div className="mt-1 truncate text-[10px] text-muted-foreground">
                  {user.email}
                </div>
              </div>
            </div>
            <div className="mt-5 border-t border-border pt-4">
              <div className="text-[9px] font-bold uppercase tracking-[.13em] text-muted-foreground">
                Workspace
              </div>
              <div className="mt-2 text-xs font-medium">{user.workspace}</div>
              <div className="mt-1 text-[10px] text-muted-foreground">
                Demo · saved in this browser
              </div>
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-5">
            <div className="flex items-start gap-3">
              <Settings2 size={16} className="mt-0.5 text-primary" />
              <div>
                <h2 className="text-sm font-semibold">Appearance</h2>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Choose the workspace theme.
                </p>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              {(["light", "dark"] as const).map((theme) => (
                <button
                  key={theme}
                  type="button"
                  onClick={() => updateUser("theme", theme)}
                  aria-pressed={user.theme === theme}
                  className={`flex-1 rounded-sm border p-2 text-[10px] capitalize ${user.theme === theme ? "border-primary bg-accent text-primary" : "border-border text-muted-foreground"}`}
                  data-testid={`button-theme-${theme}`}
                >
                  {theme}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-sm border border-border bg-card p-4">
            <div className="flex items-center gap-2 text-xs font-semibold">
              <HardDrive size={14} className="text-primary" />
              Browser storage
            </div>
            <p className="mt-2 text-[10px] leading-5 text-muted-foreground">
              Sample documents and preferences are stored in localStorage on
              this device only.
            </p>
            <button
              type="button"
              onClick={() => {
                if (
                  window.confirm(
                    "Reset all DocuMind demo data saved in this browser?",
                  )
                ) {
                  localStorage.removeItem("documind-demo-documents-v1");
                  localStorage.removeItem("documind-demo-user");
                  localStorage.removeItem("documind-demo-chat");
                  localStorage.removeItem("documind-demo-compact");
                  localStorage.removeItem("documind-demo-notifications");
                  window.location.reload();
                }
              }}
              className="mt-3 text-[10px] font-semibold text-red-700 hover:underline"
              data-testid="button-reset-demo"
            >
              Reset demo data
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}