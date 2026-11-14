import { expect, it } from "vitest";
import { matchesPlayer } from "./players";

const player = { discord_id: "12345", discord_name: "Alice_Games", real_name: "Alice Smith" };
it.each([" alice_ ", "SMITH", "234", "", "  alice smith  "])("matches names and IDs for query %j", (query) => {
  expect(matchesPlayer(player, query)).toBe(true);
});
it("rejects unrelated names and handles missing display names", () => {
  expect(matchesPlayer(player, "Bob")).toBe(false);
  expect(matchesPlayer({ ...player, real_name: "" }, "alice_games")).toBe(true);
});
