import { expect, it } from "vitest";
import { parseWeightInput } from "./weightInput";

it.each(["", " ", "NaN", "Infinity", "not a number"])("rejects invalid weight %j", (input) => {
  expect(parseWeightInput(input)).toBeNull();
});

it.each(["0.1", "2.5", "10", " 5 "])("preserves valid weight %j without a notice", (input) => {
  expect(parseWeightInput(input)).toEqual({ value: Number(input), notice: "" });
});

it("clamps out-of-range values and explains the limit", () => {
  expect(parseWeightInput("11")).toEqual({ value: 10, notice: "The maximum weight is 10. Weight set to 10." });
  expect(parseWeightInput("0")).toEqual({ value: 0.1, notice: "The minimum weight is 0.1. Weight set to 0.1." });
});
