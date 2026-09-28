import { create } from "zustand";
import type { Alert } from "@/lib/types";

export interface ToastItem {
  id: number;
  kind: "success" | "error" | "alert";
  title: string;
  body?: string;
  alert?: Alert;
}

interface ToastState {
  items: ToastItem[];
  push: (item: Omit<ToastItem, "id">) => void;
  dismiss: (id: number) => void;
}

let seq = 0;
const LIFETIME: Record<ToastItem["kind"], number> = { success: 4000, error: 7000, alert: 9000 };

export const useToasts = create<ToastState>((set) => ({
  items: [],
  push: (item) => {
    const id = ++seq;
    set((s) => ({ items: [...s.items, { ...item, id }].slice(-4) }));
    window.setTimeout(() => set((s) => ({ items: s.items.filter((t) => t.id !== id) })), LIFETIME[item.kind]);
  },
  dismiss: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (title: string, body?: string) => useToasts.getState().push({ kind: "success", title, body }),
  error: (title: string, body?: string) => useToasts.getState().push({ kind: "error", title, body }),
  alert: (alert: Alert) => {
    // One toast per anomaly: an escalation replaces the earlier one.
    const state = useToasts.getState();
    for (const t of state.items) if (t.alert?.incident_id === alert.incident_id) state.dismiss(t.id);
    state.push({ kind: "alert", title: alert.explanation, alert });
  },
};
