import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { DataSourceReport } from '../types/timeline';

export type SourcesState = 'checking' | 'ready' | 'unavailable';

/**
 * Source status, with a distinct "checking" state.
 *
 * Probing an MCP-backed source signs in to it, which can take seconds on a cold
 * start. Showing the failure text during that wait would call a healthy setup
 * broken, so the two are reported separately.
 */
export function useDataSources(refreshToken: unknown): {
  report: DataSourceReport | null;
  state: SourcesState;
} {
  const [report, setReport] = useState<DataSourceReport | null>(null);
  const [state, setState] = useState<SourcesState>('checking');

  const load = useCallback(async (isFirst: boolean) => {
    if (isFirst) setState('checking');
    try {
      const next = await api.dataSources();
      setReport(next);
      setState('ready');
    } catch {
      // Keep the last good report rather than blanking a populated panel.
      setState((current) => (report ? current : 'unavailable'));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load(report === null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  return { report, state };
}
