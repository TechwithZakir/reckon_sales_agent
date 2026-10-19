// @ts-check
// Discovery (Demo data) -> review -> CRM lead -> campaign -> approval -> dry run -> unsubscribe.
// Needs the bench's background workers and scheduler running.
const { test, expect } = require("@playwright/test");
const { login, xcall, pollUntil } = require("./helpers");

const stamp = Date.now();

test("full sales pipeline with the demo connector", async ({ page }) => {
	await login(page, "alpha");
	await expect(page.getByText("This month's plan usage")).toBeVisible();

	// 1. Discovery campaign through the form buttons.
	const connector = await xcall(page, "frappe.client.get_value", {
		doctype: "Sales Source Connector", filters: { connector_type: "fixture" }, fieldname: "name",
	});
	const campaign = await xcall(page, "frappe.client.insert", {
		doc: {
			doctype: "Sales Discovery Campaign", campaign_name: `E2E Discovery ${stamp}`,
			source_connector: connector.name, keywords: "pharmacy", locations: "Dhaka",
			target_count: 6, per_query_limit: 6, auto_research: 1,
		},
	});
	await page.goto(`/app/sales-discovery-campaign/${campaign.name}`);
	await page.getByRole("button", { name: "Preview Plan" }).click();
	await expect(page.getByRole("button", { name: "Start Discovery" })).toBeVisible();
	await page.getByRole("button", { name: "Start Discovery" }).click();
	await page.getByRole("button", { name: "Yes" }).click();

	const job = await pollUntil(
		async () => (await xcall(page, "frappe.client.get_value", {
			doctype: "Sales Discovery Campaign", filters: { name: campaign.name }, fieldname: ["last_job", "status"],
		})),
		(v) => v && v.status === "Completed",
	);
	expect(job.last_job).toBeTruthy();
	const prospects = await xcall(page, "frappe.client.get_list", {
		doctype: "Sales Prospect", filters: { discovery_campaign: campaign.name },
		fields: ["name", "email", "provenance_json"], limit_page_length: 50,
	});
	expect(prospects.length).toBeGreaterThan(0);
	expect(prospects.length).toBeLessThan(6); // the demo source repeats records; duplicates merge
	expect(JSON.parse(prospects[0].provenance_json).business_name.source).toBe("fixture");

	// 2. Review, qualify (human override: demo websites cannot be researched) and sync to the CRM.
	const target = prospects.find((p) => p.email) || prospects[0];
	await pollUntil(
		async () => (await xcall(page, "frappe.client.get_value", {
			doctype: "Sales Prospect", filters: { name: target.name }, fieldname: "latest_qualification",
		})).latest_qualification,
		Boolean,
	);
	const prospectDoc = await xcall(page, "frappe.client.get", { doctype: "Sales Prospect", name: target.name });
	await xcall(page, "reckon_sales_agent.api.override_qualification", {
		qualification: prospectDoc.latest_qualification, result: "Qualified", reason: "E2E",
	});
	await page.goto("/desk/sales-review");
	await page.locator(`input.review-select[data-name="${target.name}"]`).check();
	await page.getByRole("button", { name: "Selected" }).click();
	await page.locator(".dropdown-menu.show").getByText("Approve", { exact: true }).click();
	const synced = await pollUntil(
		async () => xcall(page, "frappe.client.get", { doctype: "Sales Prospect", name: target.name }),
		(p) => p.review_status === "Approved" && p.crm_lead,
		{ timeout: 30_000 },
	);
	const lead = await xcall(page, "frappe.client.get", { doctype: "CRM Lead", name: synced.crm_lead });
	expect(lead.rsa_company).toBe(synced.company);

	// 3. Campaign: submit, approve, draft, approve message, send (dry run: outbound is off).
	const outreach = await xcall(page, "frappe.client.insert", {
		doc: {
			doctype: "Sales Campaign", campaign_name: `E2E Outreach ${stamp}`, discovery_campaign: campaign.name,
			minimum_fit_score: 0, daily_limit: 10, offer: "a test offer",
			steps: [{ step_no: 1, delay_days: 0, subject_template: "Hello {{business_name}}", body_template: "Hi {{business_name}}" },
			        { step_no: 2, delay_days: 3, subject_template: "Again", body_template: "Again" }],
		},
	});
	await xcall(page, "reckon_sales_agent.api.submit_campaign", { campaign: outreach.name });
	const added = await xcall(page, "reckon_sales_agent.api.approve_campaign", { campaign: outreach.name });
	expect(added).toBeGreaterThan(0);
	expect(await xcall(page, "reckon_sales_agent.api.draft_now", { campaign: outreach.name })).toBeGreaterThan(0);
	const drafts = await xcall(page, "frappe.client.get_list", {
		doctype: "Sales Outreach Message", filters: { campaign: outreach.name, status: "Draft" }, fields: ["name", "body"],
	});
	expect(drafts[0].body).toContain("Unsubscribe");
	await xcall(page, "reckon_sales_agent.api.approve_messages", { messages: drafts.map((d) => d.name) });
	await xcall(page, "reckon_sales_agent.api.send_approved");
	const sent = await xcall(page, "frappe.client.get", { doctype: "Sales Outreach Message", name: drafts[0].name });
	expect(sent.status).toBe("Dry Run");

	// 4. Unsubscribe: GET only shows a confirmation; POST suppresses and stops the member.
	const member = await xcall(page, "frappe.client.get", { doctype: "Sales Campaign Member", name: sent.member });
	const url = `/api/method/reckon_sales_agent.api.unsubscribe?token=${member.unsubscribe_token}`;
	const anonymous = await (await page.context().browser().newContext()).newPage();
	await anonymous.goto(url);
	await expect(anonymous.getByRole("button", { name: "Unsubscribe" })).toBeVisible();
	let still = await xcall(page, "frappe.client.get", { doctype: "Sales Campaign Member", name: member.name });
	expect(still.status).toBe("Active");
	await anonymous.getByRole("button", { name: "Unsubscribe" }).click();
	await expect(anonymous.getByText("You will not receive further emails")).toBeVisible();
	still = await xcall(page, "frappe.client.get", { doctype: "Sales Campaign Member", name: member.name });
	expect(still.status).toBe("Stopped");
	const suppressed = await xcall(page, "frappe.client.get_count", {
		doctype: "Sales Suppression Entry", filters: { reason: "Unsubscribed", active: 1 },
	});
	expect(suppressed).toBeGreaterThan(0);
});
