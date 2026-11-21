"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { useState } from "react";
import {
  TOAST_CONTAINER_STYLE, TOAST_DURATION_MS, TOAST_ERROR_DURATION_MS, TOAST_POSITION,
} from "@/lib/toastConfig";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({
      defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
    })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position={TOAST_POSITION}
        containerStyle={TOAST_CONTAINER_STYLE}
        toastOptions={{
          duration: TOAST_DURATION_MS,
          style: {
            fontFamily: "var(--font-sans)",
            fontSize: "13px",
            borderRadius: "8px",
            border: "1px solid var(--border2)",
            background: "var(--surface2)",
            color: "var(--text1)",
          },
          success: { iconTheme: { primary: "var(--green)", secondary: "var(--surface)" } },
          error:   { duration: TOAST_ERROR_DURATION_MS,
                     iconTheme: { primary: "var(--red)",   secondary: "var(--surface)" } },
        }}
      />
    </QueryClientProvider>
  );
}
