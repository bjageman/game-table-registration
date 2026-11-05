import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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
beforeEach(() => { vi.stubGlobal("fetch", vi.fn(async () => new Response("[]"))); });
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
it.each([24, null])("creates a draft with closing offset %s, capacities, and CSRF protection", async (offset) => {
  const result = { id: "saved", title: "Friday games" };
  const fetchMock = vi.fn(
    async (path: string) => path === "/api/templates"
      ? new Response("[]") : new Response(JSON.stringify(result), { status: 201 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fill();
  expect(screen.getByLabelText("Signups Close Before Event (hours)")).toHaveValue(24);
  if (offset === null) fireEvent.change(screen.getByLabelText("Signups Close Before Event (hours)"), { target: { value: "" } });
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  await screen.findByRole("button", { name: "Save draft" });
  expect(props.onCreated).toHaveBeenCalledWith(result);
  const options = fetchMock.mock.calls.find(([path]) => path === "/api/events") as unknown as [string, RequestInit];
  expect(options[0]).toBe("/api/events");
  expect(options[1].headers).toMatchObject({ "X-CSRF-Token": "csrf" });
  expect(JSON.parse(options[1].body as string)).toEqual({
    title: "Friday games",
    description: "",
    location: "",
    starts_at: new Date("2090-06-14T19:00").toISOString(),
    duration_hours: 0,
    closes_before_hours: offset,
    tables: [{ name: "Clocktower", capacity: 15 }],
  });
});

it.each([null, 24])("edits a zero-duration event with closing offset %s", async (offset) => {
  const starts_at = new Date("2090-06-14T19:00").getTime() / 1000;
  const draft = { id: "existing", title: "Friday games", starts_at, duration_hours: 0,
    closes_at: offset === null ? null : starts_at - offset * 3600,
    tables: [{ name: "Clocktower", capacity: 15 }], status: "draft", discord_url: null };
  const fetchMock = vi.fn(async (path: string) => path === "/api/templates" ? new Response("[]") : new Response(JSON.stringify(draft)));
  vi.stubGlobal("fetch", fetchMock);
  render(<LocalizationProvider dateAdapter={AdapterDayjs}><EventForm {...props} event={draft} /></LocalizationProvider>);
  fireEvent.submit(screen.getByRole("form", { name: "Edit event" }));
  await waitFor(() => expect(props.onCreated).toHaveBeenCalledWith(draft));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  const request = fetchMock.mock.calls.find(([path]) => path === "/api/events/existing") as unknown as [string, RequestInit];
  expect(JSON.parse(request[1].body as string)).toMatchObject({ duration_hours: 0, closes_before_hours: offset });
});

it("can save a zero-duration event as a template", async () => {
  const starts_at = new Date("2090-06-14T19:00").getTime() / 1000;
  const draft = { id: "existing", title: "Friday games", starts_at, duration_hours: 0,
    closes_at: null, tables: [{ name: "Clocktower", capacity: 15 }], status: "draft", discord_url: null };
  const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => init?.method === "POST"
    ? new Response(JSON.stringify({ id: "template", title: "Friday games", duration_hours: 24, tables: draft.tables }), { status: 201 })
    : new Response("[]"));
  vi.stubGlobal("fetch", fetchMock);
  render(<LocalizationProvider dateAdapter={AdapterDayjs}><EventForm {...props} event={draft} /></LocalizationProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Save as Template" }));
  await screen.findByRole("status");
  const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST") as unknown as [string, RequestInit];
  expect(request).toBeDefined();
  expect(JSON.parse(request[1].body as string)).toMatchObject({ duration_hours: 24 });
});

it("creates a weekly schedule with signup offsets", async () => {
  const scheduled = vi.fn();
  const fetchMock = vi.fn(async (path: string) => path === "/api/templates"
    ? new Response("[]")
    : new Response(JSON.stringify({ id: "series", title: "Friday games" }), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<LocalizationProvider dateAdapter={AdapterDayjs}><EventForm {...props} onScheduled={scheduled} /></LocalizationProvider>);
  fill();
  fireEvent.click(screen.getByLabelText("Scheduled Event"));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Repeat" }));
  fireEvent.click(screen.getByRole("option", { name: "Weekly" }));
  fireEvent.change(screen.getByRole("spinbutton", { name: /^Open before event/ }), { target: { value: "78" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: /^Close before event/ }), { target: { value: "24" } });
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  await waitFor(() => expect(scheduled).toHaveBeenCalledWith("Friday games"));
  const request = fetchMock.mock.calls.find(([path]) => path === "/api/recurring-series") as unknown as [string, RequestInit];
  expect(JSON.parse(request[1].body as string)).toMatchObject({ frequency: "weekly", opens_before_hours: 78, closes_before_hours: 24 });
  expect(props.onCreated).not.toHaveBeenCalled();
});
it("rejects duplicate table names before making a request", async () => {
  const fetchMock = vi.fn(async (path: string) => { void path; return new Response("[]"); });
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
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/events")).toBe(false);
});
it("retains the form when saving fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (path: string) => path === "/api/templates" ? new Response("[]") :
        new Response(JSON.stringify({ detail: "Please check the event" }), { status: 422 }),
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
  const fetchMock = vi.fn(async (path: string) => { void path; return new Response("[]"); });
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
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/events")).toBe(false);
  expect(props.onCreated).not.toHaveBeenCalled();
});

it("saves a template without an event date and keeps the draft open", async () => {
  const template = { id: "template", title: "Friday games", duration_hours: 24,
    tables: [{ name: "Clocktower", capacity: 15 }] };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) =>
    path === "/api/templates" && options?.method === "POST"
      ? new Response(JSON.stringify(template), { status: 201 })
      : new Response("[]"));
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fireEvent.change(screen.getByLabelText(/^Event title/), { target: { value: "Friday games" } });
  fireEvent.change(screen.getByLabelText(/^Table 1 name/), { target: { value: "Clocktower" } });
  fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Bring friends" } });
  fireEvent.change(screen.getByLabelText("Location"), { target: { value: "Queen & Rook" } });
  fireEvent.click(screen.getByRole("button", { name: "Save as Template" }));
  await waitFor(() => expect(screen.getByText("Template saved: Friday games.")).toBeVisible());
  const call = fetchMock.mock.calls.find(([path, options]) => path === "/api/templates" && options?.method === "POST");
  expect(JSON.parse(call?.[1]?.body as string)).toEqual({ title: "Friday games", description: "Bring friends", location: "Queen & Rook", duration_hours: 24, tables: [{ name: "Clocktower", capacity: 15 }] });
  expect(props.onCreated).not.toHaveBeenCalled();
  expect(screen.getByRole("form", { name: "Create event" })).toBeVisible();
});

it("loads a template while preserving the selected event date", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  const template = { id: "template", title: "Friday games", description: "Bring friends", location: "Queen & Rook", duration_hours: 48,
    tables: [{ name: "Clocktower", capacity: 15 }, { name: "Root", capacity: 8 }] };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([template]))));
  renderForm();
  fireEvent.change(screen.getByLabelText(/^Event starts/), { target: { value: "June 14, 2090 7:00 PM" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Load From Template" })).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "Load From Template" }));
  fireEvent.click(screen.getByRole("button", { name: /Friday games.*48 hours/ }));
  expect(screen.getByLabelText(/^Event starts/)).toHaveValue("June 14, 2090 7:00 PM");
  expect(screen.getByLabelText(/^Event title/)).toHaveValue("Friday games");
  expect(screen.getByLabelText("Description")).toHaveValue("Bring friends");
  expect(screen.getByLabelText("Location")).toHaveValue("Queen & Rook");
  fireEvent.click(screen.getByLabelText("Scheduled Event"));
  expect(screen.getByRole("spinbutton", { name: /^Close before event/ })).toHaveValue(48);
  expect(screen.getByLabelText(/^Table 2 name/)).toHaveValue("Root");
});
