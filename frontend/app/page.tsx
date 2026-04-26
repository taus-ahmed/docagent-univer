"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(authApi.isAuthenticated() ? "/extract" : "/login");
  }, [router]);
  return null;
}
