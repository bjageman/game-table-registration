import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import EventForm from "./EventForm";

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
function fill() {
  fireEvent.change(screen.getByLabelText("Event title"), {
    target: { value: "Friday games" },
  });
  fireEvent.change(screen.getByLabelText("Event date and time"), {
    target: { value: "2090-06-14T19:00" },
  });
  fireEvent.change(screen.getByLabelText("Table 1 name"), {
    target: { value: "Clocktower" },
  });
}
it("creates a draft with an offset, capacities, and CSRF protection", async () => {
  const result = { id: "saved", title: "Friday games" };
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify(result), { status: 201 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<EventForm {...props} />);
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
  render(<EventForm {...props} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Add table" }));
  fireEvent.change(screen.getByLabelText("Table 2 name"), {
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
  render(<EventForm {...props} />);
  fill();
  fireEvent.submit(screen.getByRole("form", { name: "Create event" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Please check the event",
  );
  expect(screen.getByLabelText("Event title")).toHaveValue("Friday games");
  expect(props.onCreated).not.toHaveBeenCalled();
});
