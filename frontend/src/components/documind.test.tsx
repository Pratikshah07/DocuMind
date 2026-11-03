import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, formatMoney, formatPercent } from '@/lib/format';
import { readingDiffers } from '@/pages/document-detail';
import { ErrorState, FieldStatusBadge, StatusBadge } from './documind';

afterEach(cleanup);

describe('status display', () => {
  it('labels every processing state for people, with a stable test id', () => {
    render(<StatusBadge status="NEEDS_REVIEW" />);
    expect(screen.getByTestId('status-needs_review').textContent).toContain('Review needed');
  });

  it('shows field states', () => {
    render(<FieldStatusBadge status="uncertain" />);
    expect(screen.getByText('Check')).toBeTruthy();
  });

  it('error state is announced and offers a retry', () => {
    const retry = vi.fn();
    render(<ErrorState message="Cannot reach the server." onRetry={retry} />);
    expect(screen.getByRole('alert').textContent).toContain('Cannot reach the server.');
    fireEvent.click(screen.getByTestId('button-retry'));
    expect(retry).toHaveBeenCalledOnce();
  });
});

describe('formatting', () => {
  it('never guesses a currency symbol', () => {
    expect(formatMoney(1234.5, null)).toMatch(/1,234\.50|1\.234,50|1 234,50/);
    expect(formatMoney(1234.5, null)).not.toMatch(/[$€£]/);
    expect(formatMoney(null, 'USD')).toBe('—');
    expect(formatMoney(5, 'ZZZ')).toMatch(/^ZZZ\s5/); // unknown code: shown as written, not converted
  });

  it('formats sizes and heuristic scores', () => {
    expect([formatBytes(512), formatBytes(2048), formatBytes(3 * 1024 * 1024)]).toEqual(['512 B', '2 KB', '3.0 MB']);
    expect([formatPercent(0.876), formatPercent(null)]).toEqual(['88%', '—']);
  });
});

describe('"Read as" hint on the review page', () => {
  it('appears only when the reading is not obvious from the raw text', () => {
    expect(readingDiffers('total', '4,820.00', 4820)).toBe(false);
    expect(readingDiffers('total', '1.249,50', 1249.5)).toBe(true); // European decimals
    expect(readingDiffers('discount', '-13.50', 13.5)).toBe(true); // sign dropped on purpose
    expect(readingDiffers('invoice_date', '18/03/2025', '2025-03-18')).toBe(true);
    expect(readingDiffers('vendor_name', 'Acme', 'Acme')).toBe(false);
  });
});
