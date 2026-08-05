import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react';

export interface PlatformBranding {
  platform_name: string;
  platform_subtitle: string;
  updated_by?: string | null;
  updated_at?: string | null;
}

const DEFAULT_BRANDING: PlatformBranding = {
  platform_name: 'Geospatial Data Agent',
  platform_subtitle: 'AI-Native Geospatial Data Platform',
};

interface PlatformBrandingContextValue {
  branding: PlatformBranding;
  loading: boolean;
  refreshBranding: () => Promise<void>;
  saveBranding: (values: Pick<PlatformBranding, 'platform_name' | 'platform_subtitle'>) => Promise<PlatformBranding>;
}

const PlatformBrandingContext = createContext<PlatformBrandingContextValue | null>(null);

async function parseResponse(response: Response): Promise<PlatformBranding> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload as PlatformBranding;
}

export function PlatformBrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState(DEFAULT_BRANDING);
  const [loading, setLoading] = useState(true);

  const refreshBranding = useCallback(async () => {
    try {
      const response = await fetch('/api/platform/branding', { credentials: 'include' });
      setBranding(await parseResponse(response));
    } catch {
      setBranding(current => current || DEFAULT_BRANDING);
    } finally {
      setLoading(false);
    }
  }, []);

  const saveBranding = useCallback(async (
    values: Pick<PlatformBranding, 'platform_name' | 'platform_subtitle'>,
  ) => {
    const response = await fetch('/api/admin/platform-branding', {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    const saved = await parseResponse(response);
    setBranding(saved);
    return saved;
  }, []);

  useEffect(() => { refreshBranding(); }, [refreshBranding]);
  useEffect(() => { document.title = branding.platform_name; }, [branding.platform_name]);

  const value = useMemo(() => ({ branding, loading, refreshBranding, saveBranding }), [
    branding, loading, refreshBranding, saveBranding,
  ]);
  return <PlatformBrandingContext.Provider value={value}>{children}</PlatformBrandingContext.Provider>;
}

export function usePlatformBranding() {
  const context = useContext(PlatformBrandingContext);
  if (!context) throw new Error('usePlatformBranding must be used inside PlatformBrandingProvider');
  return context;
}
