import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AllocationReadout } from "./PolicySummary";
import { useApiData } from "../hooks";
import { isAndroid } from "./native";
vi.mock("../hooks", () => ({useApiData:vi.fn()}));
vi.mock("./native", () => ({isAndroid:vi.fn()}));
afterEach(() => {cleanup();vi.resetAllMocks();});
test.each([true,false])("allocation uses the correct ledger source on Android=%s", android => {
  vi.mocked(isAndroid).mockReturnValue(android);
  vi.mocked(useApiData).mockReturnValue({data:{portfolio:{equityValue:"1234",cashValue:"5678"}},error:null,loading:false,savedAt:null,reload:vi.fn()});
  render(<AllocationReadout />);
  expect(useApiData).toHaveBeenCalledWith(android ? "/api/v1/home/ledger" : "/api/v1/home");
  expect(screen.getByText("¥1,234")).toBeVisible();
  expect(screen.getByText("¥5,678")).toBeVisible();
});
