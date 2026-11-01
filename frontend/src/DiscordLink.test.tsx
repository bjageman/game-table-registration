import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import DiscordLink from "./DiscordLink";

it("uses the original HTTPS Discord destination", () => {
  const url = "https://discord.com/channels/123/456/789";
  render(<DiscordLink url={url} label="View poll">Poll</DiscordLink>);
  const link = screen.getByRole("link", { name: "View poll (opens in a new tab)" });
  expect(link).toHaveAttribute("href", url);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noreferrer");
  expect(screen.getAllByRole("link")).toHaveLength(1);
});
