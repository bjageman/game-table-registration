import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DiscordLink, { discordAppUrl } from "./DiscordLink";

describe("Discord links", () => {
  it("converts Discord channel and message links to desktop links", () => {
    expect(discordAppUrl("https://discord.com/channels/123/456/789")).toBe("discord://-/channels/123/456/789");
    expect(discordAppUrl("https://discord.com/channels/123/456")).toBe("discord://-/channels/123/456");
    expect(discordAppUrl("https://example.com/channels/123/456")).toBeNull();
    expect(discordAppUrl("https://discord.com/oauth2/authorize")).toBeNull();
  });
  it("provides a browser fallback after attempting to open the app", () => {
    const url = "https://discord.com/channels/123/456/789";
    render(<DiscordLink url={url} label="View poll">Poll</DiscordLink>);
    const link = screen.getByRole("link", { name: "View poll (opens Discord app)" });
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(link).toHaveAttribute("href", "discord://-/channels/123/456/789");
    expect(screen.getByRole("link", { name: /Open in Browser/ })).toHaveAttribute("href", url);
  });
});
