import { expect, test } from "@playwright/test";

test.describe("LabelLens core flows", () => {
  test("document selection, ask with citations, and version compare", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/Label\s*Lens/i).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("Indexed drugs")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: "Explorer" }).click();
    await expect(page.getByRole("heading", { name: "Document Explorer" })).toBeVisible();
    await page.getByRole("button", { name: /Lipitor|LIPITOR|atorvastatin/i }).first().click();
    await expect(page.getByText(/SET ID:/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/a60cc18b-0631-4cf0-b021-9f52224ece65/).first()).toBeVisible();

    await page.getByRole("link", { name: "Ask", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Ask LabelLens" })).toBeVisible();
    await page.getByRole("button", { name: "Ask LabelLens" }).click();
    await expect(page.getByText(/Evidence|Abstained|evidence/i).first()).toBeVisible({
      timeout: 60_000,
    });
    // Citations panel should show at least one passage id when evidence is returned.
    const evidence = page.locator("text=/a60cc18b-0631-4cf0-b021-9f52224ece65:v8:/");
    await expect(evidence.first()).toBeVisible({ timeout: 30_000 });

    await page.getByRole("link", { name: "Compare" }).click();
    await expect(page.getByRole("heading", { name: "Version Comparison" })).toBeVisible();
    await page.getByRole("button", { name: "Compare versions" }).click();
    await expect(page.getByText("Deterministic comparison for set_id=")).toBeVisible({
      timeout: 30_000,
    });
  });
});
