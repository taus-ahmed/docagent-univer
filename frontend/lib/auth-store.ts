"use client";
import { create } from "zustand";
import { authApi, type User } from "./api";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  initializeFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  isLoading: false,
  isAuthenticated: false,

  initializeFromStorage: async () => {
    if (!authApi.isAuthenticated()) {
      set({ isAuthenticated: false, user: null, isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await authApi.me();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      authApi.logout();
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  login: async (username, password) => {
    set({ isLoading: true });
    try {
      const response = await authApi.login(username, password);
      set({ user: response.user, isAuthenticated: true, isLoading: false });
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