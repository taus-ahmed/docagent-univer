"use client";
import { create } from "zustand";
import { authApi, type User } from "./api";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** True once the stored session has been read (lib/session-gate.ts). */
  initialized: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  initializeFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  isLoading: false,
  isAuthenticated: false,
  initialized: false,

  initializeFromStorage: async () => {
    if (!authApi.isAuthenticated()) {
      set({ isAuthenticated: false, user: null, isLoading: false, initialized: true });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await authApi.me();
      set({ user, isAuthenticated: true, isLoading: false, initialized: true });
    } catch {
      authApi.logout();
      set({ user: null, isAuthenticated: false, isLoading: false, initialized: true });
    }
  },

  login: async (username, password) => {
    set({ isLoading: true });
    try {
      const response = await authApi.login(username, password);
      set({ user: response.user, isAuthenticated: true, isLoading: false, initialized: true });
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  logout: () => {
    authApi.logout();
    set({ user: null, isAuthenticated: false });
  },

  refreshUser: async () => {
    if (!authApi.isAuthenticated()) {
      set({ isAuthenticated: false, user: null });
      return;
    }
    try {
      const user = await authApi.me();
      set({ user, isAuthenticated: true });
    } catch {
      authApi.logout();
      set({ user: null, isAuthenticated: false });
    }
  },
}));