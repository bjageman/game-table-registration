import { useState, type ReactNode } from "react";

export function discordAppUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || parsed.hostname !== "discord.com" ||
      !/^\/channels\/(?:[0-9]+|@me)\/[0-9]+(?:\/[0-9]+)?$/.test(parsed.pathname)) return null;
    return `discord://-${parsed.pathname}`;
  } catch { return null; }
}

export default function DiscordLink({ url, label, className, children }: {
  url: string; label: string; className?: string; children: ReactNode;
}) {
  const appUrl = discordAppUrl(url);
  const [showFallback, setShowFallback] = useState(false);
  return <span className="discord-link-group">
    <a href={appUrl ?? url} className={className} title={label}
      aria-label={`${label}${appUrl ? " (opens Discord app)" : " (opens in a new tab)"}`}
      target={appUrl ? undefined : "_blank"} rel="noreferrer"
      onClick={() => { if (appUrl) setShowFallback(true); }}>
      {children}
    </a>
    {showFallback && <a className="discord-browser-fallback" href={url} target="_blank" rel="noreferrer">Open in Browser<span className="sr-only"> — {label} (opens in a new tab)</span></a>}
  </span>;
}
