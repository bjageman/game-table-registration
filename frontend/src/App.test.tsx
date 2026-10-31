import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "./App";

it("shows Register and Login placeholders", () => {
  render(<App />);
  expect(screen.getByRole("button", { name: "Register" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
  expect(screen.getAllByRole("button")).toHaveLength(2);
});
