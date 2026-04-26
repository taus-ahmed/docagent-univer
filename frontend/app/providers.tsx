"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { useState } from "react";

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
        position="top-right"
        toastOptions={{
          style: {
            fontFamily: "var(--font-sans)",
            fontSize: "13px",
            borderRadius: "8px",
            border: "1px solid var(--border2)",
            background: "var(--surface2)",
            color: "var(--text1)",
          },
          success: { iconTheme: { primary: "var(--green)", secondary: "var(--surface)" } },
          error:   { iconTheme: { primary: "var(--red)",   secondary: "var(--surface)" } },
        }}
      />
    </QueryClientProvider>
  );
}
