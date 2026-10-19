// @ts-check
const { expect } = require("@playwright/test");

const USERS = {
	alpha: process.env.E2E_ALPHA_USER || "sa-e2e-alpha@example.com",
	beta: process.env.E2E_BETA_USER || "sa-e2e-beta@example.com",
};

/** Log in through Frappe's login API and open the Sales Agent home. */
async function login(page, who) {
	const response = await page.request.post("/api/method/login", {
		form: { usr: USERS[who], pwd: process.env.E2E_PASSWORD || "" },
	});
	expect(response.ok(), `login as ${who}`).toBeTruthy();
	await page.goto("/desk/sales-agent");
	await page.waitForFunction(() => window.frappe && window.frappe.boot && window.frappe.xcall);
}

/** Call a whitelisted method from inside the page (carries the CSRF token). */
async function xcall(page, method, args = {}) {
	return page.evaluate(([m, a]) => frappe.xcall(m, a), [method, args]);
}

/** Like xcall, but returns the server's error text instead of throwing. */
async function xcallError(page, method, args = {}) {
	return page.evaluate(
		([m, a]) =>
			frappe
				.xcall(m, a)
				.then(() => null)
				.catch((e) => String((e && (e.message || e.exc_type)) || e || "error")),
		[method, args]
	);
}

async function pollUntil(fn, predicate, { timeout = 150_000, interval = 3_000 } = {}) {
	const deadline = Date.now() + timeout;
	let value;
	while (Date.now() < deadline) {
		value = await fn();
		if (predicate(value)) return value;
		await new Promise((r) => setTimeout(r, interval));
	}
	throw new Error(`Timed out; last value ${JSON.stringify(value)}`);
}

module.exports = { USERS, login, xcall, xcallError, pollUntil };
