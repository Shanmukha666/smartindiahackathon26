import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InlineCitations, PanelHeading, ResultField } from "./atoms";

describe("shared display components", () => {
  it("renders citation IDs as separate citation chips", () => {
    const { container } = render(<InlineCitations text="See [chunk-a] and [chunk-b]." />);
    expect(container.querySelectorAll(".citation-chip")).toHaveLength(2);
    expect(screen.getByText("chunk-a")).toBeInTheDocument();
    expect(screen.getByText("chunk-b")).toBeInTheDocument();
  });

  it("renders a panel heading and result field accessibly", () => {
    render(<><PanelHeading eyebrow="Decision tree" title="Classification" index="01" /><ResultField label="IP posture" value="Review required" /></>);
    expect(screen.getByRole("heading", { name: "Classification" })).toBeInTheDocument();
    expect(screen.getByText("Review required")).toBeInTheDocument();
  });
});
