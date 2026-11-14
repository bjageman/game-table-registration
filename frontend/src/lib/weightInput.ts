export const MIN_WEIGHT = 0.1;
export const MAX_WEIGHT = 10;

type WeightInput = { value: number; notice: string } | null;

export function parseWeightInput(input: string): WeightInput {
  const entered = Number(input);
  if (!input.trim() || !Number.isFinite(entered)) return null;
  const value = Math.min(MAX_WEIGHT, Math.max(MIN_WEIGHT, entered));
  const notice = entered > MAX_WEIGHT
    ? `The maximum weight is ${MAX_WEIGHT}. Weight set to ${MAX_WEIGHT}.`
    : entered < MIN_WEIGHT
      ? `The minimum weight is ${MIN_WEIGHT}. Weight set to ${MIN_WEIGHT}.`
      : "";
  return { value, notice };
}
