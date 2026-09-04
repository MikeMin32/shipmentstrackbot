import type { ReactNode } from "react";

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Banner({
  kind = "error",
  children,
}: {
  kind?: "error" | "info";
  children: ReactNode;
}) {
  return <div className={`banner ${kind}`}>{children}</div>;
}
