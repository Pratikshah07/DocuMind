/** Small UI utilities shared by pages. */

export type ToastKind = 'success' | 'error' | 'info';

/** Show a toast (rendered by ToastViewport in the app shell). */
export function notify(message: string, kind: ToastKind = 'success'): void {
  window.dispatchEvent(new CustomEvent('documind-toast', { detail: { message, kind } }));
}

/** Save a Blob to the user's device. */
export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export const buttonBase =
  'inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2.5 text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50';

// --- Theme (a harmless per-browser preference) ---------------------------------------

const THEME_KEY = 'documind-theme';
export type Theme = 'light' | 'dark';

export function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* preference just isn't remembered */
  }
}
