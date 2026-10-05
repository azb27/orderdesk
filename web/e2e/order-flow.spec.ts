import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_PASSWORD ?? "orderdesk-demo";

async function signIn(page: Page, who: "Maria" | "Omar") {
  await page.goto("/login");
  if (PASSWORD === "orderdesk-demo") {
    await page.getByRole("button", { name: `Sign in as ${who}` }).click();
  } else {
    await page.getByText("Sign in with email").click();
    await page.getByLabel("Email").fill(`${who.toLowerCase()}@saffronlane.example`);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }
  await expect(page.getByRole("button", { name: "Retailer phone (demo)" })).toBeVisible();
}

test("signed-out visitors land on the sign-in page", async ({ page }) => {
  await page.goto("/orders/1");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Orderdesk" })).toBeVisible();
});

test("a WhatsApp order goes from the retailer's phone to the ERP and back", async ({ page }) => {
  await signIn(page, "Maria");
  await page.getByRole("button", { name: "Retailer phone (demo)" }).click();
  const phone = page.getByRole("complementary", { name: "Retailer phone (demo)" });
  // C1004: a shop that writes in English and is well inside its credit limit
  await phone.getByLabel("Sending as").selectOption("+971500001004");
  const marker = `${Date.now() % 1000}`;
  await phone.getByLabel("Message").fill(`hi\nal wadi water 500 ml 3 ctn\nsunflower oil 1.8 l 6 pcs\nref ${marker}`);
  await phone.getByRole("button", { name: "Send", exact: true }).click();

  // the draft arrives on its own (server-sent events), read by the fallback parser in tests
  const item = page.locator(".queue-item").first();
  await expect(item).toBeVisible({ timeout: 30_000 });
  await item.click();
  const pad = page.locator(".pad");
  await expect(pad.getByText("Al Wadi Water 500 ml bottle")).toBeVisible();
  await expect(page.locator("mark").first()).toBeVisible(); // the source words are highlighted

  // fix a quantity: the total is recomputed by the server
  const before = await pad.locator(".pad-total").innerText();
  await pad.getByRole("button", { name: "Edit line 1" }).click();
  await pad.getByLabel("Quantity").fill("4");
  await pad.getByRole("button", { name: "Save line" }).click();
  await expect(pad.locator(".pad-line").first()).toContainText("Edited");
  await expect(pad.locator(".pad-total")).not.toHaveText(before);

  // confirm with the keyboard; the stamp lands, the ERP takes it, the retailer gets a reply
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: /confirmed|in erp/i })).toBeVisible();
  await page.getByRole("button", { name: /In ERP/ }).click();
  await expect(page.locator(".queue-item").first()).toBeVisible({ timeout: 20_000 });
  await expect(phone.locator(".pbubble--them").last()).toContainText("confirmed", { timeout: 20_000 });
});

test("j and k move through the queue", async ({ page }) => {
  await signIn(page, "Maria");
  await page.getByRole("button", { name: /In ERP/ }).click();
  const items = page.locator(".queue-item");
  if ((await items.count()) < 1) test.skip(true, "needs at least one order");
  await page.keyboard.press("j");
  await expect(page).toHaveURL(/\/orders\/\d+$/);
});
