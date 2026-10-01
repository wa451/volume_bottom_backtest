"use client";
import { useEffect, useState, useCallback } from "react";
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api/" + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : body?.detail
          ? JSON.stringify(body.detail)
          : "APIに接続できません（" + response.status + "）",
    );
  }
  return response.json();
}
export function useApi<T>(path: string | null, poll = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((v) => v + 1), []);
  useEffect(() => {
    if (!path) {
      setData(undefined);
      setLoading(false);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true);
    setData(undefined);
    const read = async () => {
      let terminal = false;
      try {
        const value = await api<T>(path);
        terminal =
          !!value &&
          typeof value === "object" &&
          "status" in value &&
          ["completed", "failed"].includes(String(value.status));
        if (alive) {
          setData(value);
          setError("");
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        if (alive) {
          setLoading(false);
          if (poll && !terminal) timer = setTimeout(read, poll);
        }
      }
    };
    void read();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [path, poll, revision]);
  return { data, error, loading, refresh };
}
export function query(
  values: Record<string, string | number | null | undefined>,
): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values))
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
}
