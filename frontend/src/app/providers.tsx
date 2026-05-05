"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ToastProvider } from "@/components/ui/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 15 min: backend is on Vercel Python, every cold start costs
            // 3-7s. Wider stale window means most navigations between
            // dashboard pages serve cached data and don't pay that penalty.
            staleTime: 15 * 60 * 1000,
            gcTime: 30 * 60 * 1000,
            refetchOnWindowFocus: false,
            refetchOnMount: false,
            retry: (failureCount, error: any) => {
              // Don't retry on auth errors
              if (error?.message?.includes("401") || error?.message?.includes("Unauthorized")) {
                return false;
              }
              return failureCount < 2;
            },
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
