import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SignupDownload from "./SignupDownload";
import { download } from "../../../lib/download";

vi.mock("../../../lib/download", () => ({ download: vi.fn(async () => undefined) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("downloads the PDF in the browser timezone", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  render(<SignupDownload event={{
    id: "event", title: "Monday Tables", starts_at: 1794265200,
    duration_hours: 4, tables: [], status: "assigned", closes_at: null,
    discord_url: null,
  }} onAccessError={() => false} />);
  fireEvent.click(screen.getByRole("button", { name: "Download event signups" }));
  fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  await waitFor(() => expect(download).toHaveBeenCalledWith(
    `/events/event/signups.pdf?timezone=${encodeURIComponent(timezone)}`,
    "signups-event.pdf",
  ));
});
