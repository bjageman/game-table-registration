import type { ReactNode } from "react";

export default function DiscordLink({ url, label, className, children }: {
  url: string; label: string; className?: string; children: ReactNode;
}) {
  return <a href={url} className={className} title={label}
    aria-label={`${label} (opens in a new tab)`}
    target="_blank" rel="noreferrer">
    {children}
  </a>;
}
