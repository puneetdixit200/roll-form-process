import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

test("opens the complete generator directly without legacy application sections", async () => {
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Visual Flower Generator" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Generate Flower Sequence" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Validate Profile" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Load Example" })).toBeInTheDocument();
  for (const name of ["Dashboard", "New Project / Upload", "Processing Progress", "Project Summary", "Flower Viewer", "Physical Roller Inventory", "Roller Recognition", "Validation & Usage Search"]) {
    expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
  }
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/inventory"))).toBe(false);
});

test("retains authentication before allowing access to the generator", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url === "/api/auth/status" ? { auth_enabled: true, authenticated: false } : {},
  ), { status: 200 })));
  render(<App />);
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Generate Flower Sequence" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "demo" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-only" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("button", { name: "Generate Flower Sequence" })).toBeInTheDocument();
});
