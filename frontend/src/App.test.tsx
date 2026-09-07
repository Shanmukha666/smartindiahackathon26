import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { postApi } from "./api/client";

vi.mock("./api/client", () => ({ postApi: vi.fn() }));
const mockedPostApi = vi.mocked(postApi);

const classification = {
  complete: false, question: "Is the formulation traditional knowledge?", options: ["Yes", "No"], trail: [], result: null,
};

describe("App", () => {
  beforeEach(() => {
    mockedPostApi.mockReset();
    mockedPostApi.mockImplementation(async (path: string) => {
      if (path === "/auth/dev-session") throw new Error("disabled outside local demo");
      if (path === "/classify/next") return classification;
      if (path === "/ask") return {
        mode: "single", answer: "Traditional knowledge is excluded. [demo-patents-act-section-3-p-1]", sections: null,
        citations: ["demo-patents-act-section-3-p-1"], confidence: "medium", abstain: false, reason: null,
        disclaimer: "Information only, not legal advice.",
        evidence: [{ chunk_id: "demo-patents-act-section-3-p-1", instrument: "Patents Act", section: "3(p)", jurisdiction: "IN", chunk_text: "Traditional knowledge exclusion", score: 0.9 }],
      };
      throw new Error(`Unexpected route ${path}`);
    });
  });

  it("loads classification and renders a cited grounded answer", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Is the formulation traditional knowledge?")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "What does Section 3(p) exclude?");
    await user.click(screen.getByRole("button", { name: /ask sahayak/i }));
    expect(await screen.findByText(/Traditional knowledge is excluded/)).toBeInTheDocument();
    expect(screen.getAllByText("demo-patents-act-section-3-p-1").length).toBeGreaterThan(0);
  });
});
