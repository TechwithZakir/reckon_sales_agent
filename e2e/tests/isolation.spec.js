// @ts-check
// Company A's CRM and Sales Agent data must be invisible and unchangeable for Company B.
const { test, expect } = require("@playwright/test");
const { login, xcall, xcallError } = require("./helpers");

const stamp = Date.now();

test("Sales Agent and CRM records are separated by Company", async ({ browser }) => {
	const alpha = await (await browser.newContext()).newPage();
	await login(alpha, "alpha");
	const prospect = await xcall(alpha, "frappe.client.insert", {
		doc: { doctype: "Sales Prospect", business_name: `E2E Isolation ${stamp}`, website: "https://isolation.example" },
	});
	const lead = await xcall(alpha, "frappe.client.insert", {
		doc: { doctype: "CRM Lead", first_name: `E2E Lead ${stamp}`, status: "New" },
	});
	expect(prospect.company).toBeTruthy();
	expect(prospect.review_status).toBe("Pending"); // server-managed, not client-set
	expect(lead.rsa_company).toBe(prospect.company);

	const beta = await (await browser.newContext()).newPage();
	await login(beta, "beta");
	expect(await xcall(beta, "frappe.client.get_list", { doctype: "Sales Prospect", filters: { name: prospect.name } })).toEqual([]);
	expect(await xcall(beta, "frappe.client.get_list", { doctype: "CRM Lead", filters: { name: lead.name } })).toEqual([]);
	expect(await xcallError(beta, "frappe.client.get", { doctype: "CRM Lead", name: lead.name })).not.toBeNull();
	expect(await xcallError(beta, "reckon_sales_agent.api.review_prospects", { prospects: [prospect.name], action: "approve" })).not.toBeNull();

	// B cannot create a record for A's Company or attach a task to A's lead.
	expect(
		await xcallError(beta, "frappe.client.insert", {
			doc: { doctype: "Sales Prospect", business_name: "Forged", company: prospect.company },
		})
	).not.toBeNull();
	expect(
		await xcallError(beta, "frappe.client.insert", {
			doc: { doctype: "CRM Task", title: "Forged", reference_doctype: "CRM Lead", reference_docname: lead.name },
		})
	).not.toBeNull();

	// B's own CRM lead list in the CRM app does not show A's lead.
	await beta.goto("/crm/leads");
	await expect(beta.getByText(`E2E Lead ${stamp}`)).toHaveCount(0);
});

test("Tenants cannot change site-wide CRM settings or their own plan limits", async ({ page }) => {
	await login(page, "alpha");
	const company = (await xcall(page, "reckon_sales_agent.api.dashboard")).company;
	expect(
		await xcallError(page, "frappe.client.set_value", { doctype: "FCRM Settings", name: "FCRM Settings", fieldname: "brand_name", value: "x" })
	).not.toBeNull();
	await xcallError(page, "frappe.client.set_value", {
		doctype: "Sales Agent Settings", name: company, fieldname: "monthly_discovery_limit", value: 999999,
	});
	const settings = await xcall(page, "frappe.client.get", { doctype: "Sales Agent Settings", name: company });
	expect(settings.monthly_discovery_limit || 0).not.toBe(999999);
});

test("Desk routes outside the module redirect to the Sales Agent home", async ({ page }) => {
	await login(page, "alpha");
	await page.goto("/app/user");
	await expect(page).toHaveURL(/sales-agent/);
});
