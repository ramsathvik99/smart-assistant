import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

// The main navigation sits directly under the sidebar header, above the voice
// library, so its position never depends on how tall the library is.

const route = vi.hoisted(() => ({ pathname: '/clone' }));
const sidebar = vi.hoisted(() => ({ compact: false, setOpen: vi.fn() }));
vi.mock('@tanstack/react-router', () => ({
  useRouterState: ({ select }: any) => select({ location: route }),
  Link: ({ to, children, ...props }: any) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: { version?: string }) =>
      key === 'app.version_dev'
        ? `v${values?.version} · Dev`
        : key === 'app.version'
          ? `v${values?.version}`
          : key,
  }),
}));
vi.mock('@/lib/store/workspace', () => ({
  useWorkspace: () => ({ libraryOpen: true, libraryTab: 'voices' }),
  setWorkspace: vi.fn(),
}));
const platform = vi.hoisted(() => ({ mac: false }));
vi.mock('@/components/bridge', () => ({ appVersion: () => '0.5.7', isMac: () => platform.mac }));
vi.mock('@/hooks/use-window-fullscreen', () => ({ useWindowFullscreen: () => false }));
vi.mock('@/lib/brand', () => ({ brandIcon: 'icon.png', brandArtwork: 'art.png' }));
vi.mock('@/hooks/use-pane-resize', () => ({
  usePaneResize: () => ({ host: { current: null }, width: 280, separatorProps: {} }),
}));
vi.mock('@/hooks/use-backend-status', () => ({ useBackendStatus: () => ({ stage: 'ready' }) }));
vi.mock('@/features/clone/voices-sidebar', () => ({
  VoicesSidebar: () => <div data-testid="library" />,
}));
vi.mock('./workspace-menu', () => ({
  WorkspaceNavigation: () => <nav data-testid="navigation" />,
}));
vi.mock('./status-bar', () => ({
  StatusBar: ({ footerLeading }: { footerLeading?: React.ReactNode }) => (
    <div data-testid="status">{footerLeading}</div>
  ),
}));
vi.mock('./system-notifications', () => ({ SystemNotifications: () => null }));

vi.mock('./use-workspace-sidebar', () => ({
  useWorkspaceSidebarState: () => ({
    compact: sidebar.compact,
    compactViewport: false,
    forceExpanded: false,
    secondaryWorkspace: false,
    setOpen: sidebar.setOpen,
  }),
}));
import { MAC_TRAFFIC_LIGHTS_BAND } from '@shared/utils/windowChrome';
import { versionTranslationKey, WorkspaceSidebar } from './workspace-sidebar';

beforeEach(() => {
  sidebar.compact = false;
  sidebar.setOpen.mockClear();
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
});

it('expands the compact rail on double-click without changing single-click navigation', () => {
  sidebar.compact = true;
  render(<WorkspaceSidebar />);
  const rail = screen.getByRole('complementary', { name: 'clone.saved_profiles' });
  fireEvent.click(rail);
  expect(sidebar.setOpen).not.toHaveBeenCalled();
  fireEvent.doubleClick(rail);
  expect(sidebar.setOpen).toHaveBeenCalledWith(true);
});

it('sizes the rail to the row above the bottom player, never the whole viewport', () => {
  // A viewport-tall rail ran under the now-playing dock and hid its last items.
  sidebar.compact = true;
  render(<WorkspaceSidebar />);
  const rail = screen.getByRole('complementary', { name: 'clone.saved_profiles' });
  expect(rail).toHaveClass('h-full');
  expect(rail.className).not.toMatch(/\bh-(?:dvh|screen|svh)\b/);
});

it('keeps only navigation and status in the slim expanded sidebar', () => {
  render(<WorkspaceSidebar />);
  const navigation = screen.getByTestId('navigation');
  const status = screen.getByTestId('status');
  expect(
    navigation.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  // The saved voices and takes live in the section's own secondary sidebar.
  expect(screen.queryByTestId('library')).toBeNull();
});

it('shows the app version beneath the brand name in the expanded sidebar', () => {
  render(<WorkspaceSidebar />);
  const brand = screen.getByRole('link', { name: 'app.name v0.5.7 · Dev' });
  expect(brand).toHaveTextContent('app.name');
  expect(brand).toHaveTextContent('v0.5.7 · Dev');
});

it('uses the plain version label outside development builds', () => {
  expect(versionTranslationKey(true)).toBe('app.version_dev');
  expect(versionTranslationKey(false)).toBe('app.version');
});

it('starts the brand row below the macOS traffic lights, never beside them', () => {
  platform.mac = true;
  try {
    const { container } = render(<WorkspaceSidebar />);
    const row = container.querySelector('[data-slot="titlebar-row"]') as HTMLElement;
    expect(row.style.paddingTop).toBe(`${MAC_TRAFFIC_LIGHTS_BAND}px`);
  } finally {
    platform.mac = false;
  }
});

it('labels Settings in the expanded macOS footer instead of a bare icon', () => {
  platform.mac = true;
  try {
    render(<WorkspaceSidebar />);
    expect(screen.getByTestId('status')).toHaveTextContent('nav.settings');
  } finally {
    platform.mac = false;
  }
});

it('shows the brand mark on the compact rail on macOS too, with the expand icon behind it', () => {
  platform.mac = true;
  sidebar.compact = true;
  try {
    const { container } = render(<WorkspaceSidebar />);
    const toggle = screen.getByRole('button', { name: 'clone.toggle_sidebar' });
    expect(toggle.querySelector('[data-slot="rail-brand"]')).not.toBeNull();
    expect(toggle.querySelector('svg')).not.toBeNull();
    fireEvent.click(toggle);
    expect(sidebar.setOpen).toHaveBeenCalledWith(true);
    expect(container).toBeTruthy();
  } finally {
    platform.mac = false;
  }
});
