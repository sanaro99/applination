import { create } from "zustand";

const SIDEBAR_KEY = "sidebar-collapsed";

interface UIState {
  activeRunId: number | null;
  setActiveRunId: (id: number | null) => void;
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
}

export const useUI = create<UIState>((set) => ({
  activeRunId: null,
  setActiveRunId: (id) => set({ activeRunId: id }),
  commandOpen: false,
  setCommandOpen: (open) => set({ commandOpen: open }),
  // Default expanded; the real value is hydrated from localStorage after mount
  // (see AppShell) so SSR and the first client render agree (avoids a mismatch).
  sidebarCollapsed: false,
  setSidebarCollapsed: (collapsed) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    }
    set({ sidebarCollapsed: collapsed });
  },
  toggleSidebar: () =>
    set((s) => {
      const next = !s.sidebarCollapsed;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      }
      return { sidebarCollapsed: next };
    }),
}));

export function readStoredSidebarCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(SIDEBAR_KEY) === "1";
}
