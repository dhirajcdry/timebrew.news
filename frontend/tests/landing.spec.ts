import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Public UI QA must never sign in, trigger generation, or contact production.
  // Font requests are also blocked to exercise the offline/system font fallback.
  await page.route("**/*", (route) => {
    const hostname = new URL(route.request().url()).hostname;
    return hostname === "127.0.0.1" ? route.continue() : route.abort();
  });
  await page.goto("/");
});

test("landing is immediately readable, source-backed and fits the viewport", async ({ page }, testInfo) => {
  await expect(page.getByRole("heading", { level: 1 })).toContainText("A lot less scroll.");
  await expect(page.getByText("2024 archive sample", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Read the original.*NASA/ })).toHaveAttribute("href", /^https:\/\/www\.nasa\.gov\//);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator('a[href="#"], a[href="/settings"]')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("landing.png"), fullPage: true });
});

test("sample is keyboard-contained, dismisses repeatedly, and returns focus", async ({ page }, testInfo) => {
  const opener = page.getByRole("button", { name: "Read a sample", exact: true });
  const dialog = page.getByRole("dialog");
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await opener.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Close sample digest" })).toBeFocused();
    await expect(dialog).toContainText("historical example");
    await expect(dialog.locator('a[target="_blank"]')).toHaveCount(3);
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => !!document.querySelector("dialog")?.contains(document.activeElement))).toBe(true);
    if (attempt === 0) await page.screenshot({ path: testInfo.outputPath("sample.png") });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(opener).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
  }
});

test("sample CTA closes cleanly and Back returns to a usable landing", async ({ page }) => {
  await page.getByRole("button", { name: "Read a sample", exact: true }).click();
  await page.getByRole("dialog").getByRole("link", { name: "Create your own brew" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("A lot less scroll.");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Read a sample", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
});

test("navigation reaches actual sections and mobile menu is dismissible", async ({ page }, testInfo) => {
  if (testInfo.project.name === "mobile") {
    const button = page.getByRole("button", { name: "Open navigation" });
    await button.click();
    await expect(page.getByRole("button", { name: "Close navigation" })).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(button).toBeFocused();
    await button.click();
    await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "How it works" }).click();
    await expect(page.getByRole("navigation", { name: "Mobile navigation" })).not.toBeVisible();
  } else {
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "How it works" }).click();
  }
  await expect(page).toHaveURL(/#how-it-works$/);
  await expect(page.locator("#how-it-works")).toBeFocused();
  await page.getByRole("navigation", { name: "Footer navigation" }).getByRole("link", { name: "Questions" }).click();
  await expect(page).toHaveURL(/#faq$/);
  await page.getByText("How is the news put together?", { exact: true }).click();
  await expect(page.getByText(/AI summaries can make mistakes/)).toBeVisible();
});

test("narrow and reduced-motion layout remains usable", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Read a sample", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box?.width).toBeLessThanOrEqual(320);
  await dialog.getByRole("button", { name: "Close sample digest" }).click();
  await expect(dialog).not.toBeVisible();
});
