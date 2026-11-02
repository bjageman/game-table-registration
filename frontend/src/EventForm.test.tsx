import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import EventForm from "./EventForm";

vi.mock("@mui/x-date-pickers/DateTimePicker", () => ({
  DateTimePicker: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: Dayjs | null;
    onChange: (value: Dayjs | null) => void;
  }) =>
    createElement("input", {
      "aria-label": label,
      value: value?.format("MMMM D, YYYY h:mm A") ?? "",
      onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
        onChange(dayjs(event.currentTarget.value)),
    }),
}));

const props = {
  csrf: "csrf",
  onCreated: vi.fn(),
  onCancel: vi.fn(),
  onAccessError: vi.fn(() => false),
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
function renderForm() {
  return render(
    <LocalizationProvider dateAdapter={AdapterDayjs}>
      <EventForm {...props} />
    </LocalizationProvider>,
  );
}
function fill() {
  fireEvent.change(screen.getByLabelText(/^Event title/), {
    target: { value: "Friday games" },
  });
  fireEvent.change(screen.getByLabelText(/^Event starts/), {
    target: { value: "June 14, 2090 7:00 PM" },
  });
  fireEvent.change(screen.getByLabelText(/^Table 1 name/), {
    target: { value: "Clocktower" },
  });
}
it("creates a draft with an offset, capacities, and CSRF protection", async () => {
  const result = { id: "saved", title: "Friday games" };
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify(result), { status: 201 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fill();
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  await screen.findByRole("button", { name: "Save draft" });
  expect(props.onCreated).toHaveBeenCalledWith(result);
  const options = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(options[0]).toBe("/api/events");
  expect(options[1].headers).toMatchObject({ "X-CSRF-Token": "csrf" });
  expect(JSON.parse(options[1].body as string)).toEqual({
    title: "Friday games",
    starts_at: new Date("2090-06-14T19:00").toISOString(),
    duration_hours: 24,
    tables: [{ name: "Clocktower", capacity: 15 }],
  });
});
it("rejects duplicate table names before making a request", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Add table" }));
  fireEvent.change(screen.getByLabelText(/^Table 2 name/), {
    target: { value: "clocktower" },
  });
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Table names must be unique",
  );
  expect(fetchMock).not.toHaveBeenCalled();
});
it("retains the form when saving fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Please check the event" }), {
          status: 422,
        }),
    ),
  );
  renderForm();
  fill();
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Please check the event",
  );
  expect(screen.getByLabelText(/^Event title/)).toHaveValue("Friday games");
  expect(props.onCreated).not.toHaveBeenCalled();
});

it("limits the editor to ten tables and preserves remaining rows after removal", () => {
  renderForm();
  fill();
  for (let i = 1; i < 10; i++)
    fireEvent.click(screen.getByRole("button", { name: "Add table" }));
  expect(screen.getByRole("button", { name: "Add table" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Remove table 2" }),
  );
  expect(screen.getByRole("button", { name: "Add table" })).not.toBeDisabled();
  expect(screen.getByLabelText(/^Table 1 name/)).toHaveValue("Clocktower");
});

it.each(["name", "capacity"])("Enter in a table %s adds and focuses a row without submitting, including at the limit", (field) => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fill();
  for (let i = 1; i < 10; i++) {
    const name = screen.getByLabelText(new RegExp(`^Table ${i} ${field}`));
    expect(fireEvent.keyDown(name, { key: "Enter", code: "Enter" })).toBe(false);
    expect(screen.getByLabelText(new RegExp(`^Table ${i + 1} name`))).toHaveFocus();
  }
  expect(fireEvent.keyDown(screen.getByLabelText(new RegExp(`^Table 10 ${field}`)), { key: "Enter" })).toBe(false);
  expect(screen.getAllByRole("textbox", { name: /^Table .* name/ })).toHaveLength(10);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(props.onCreated).not.toHaveBeenCalled();
});
