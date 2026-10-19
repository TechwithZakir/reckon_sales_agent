// @ts-check
const { defineConfig } = require("@playwright/test");

if (!process.env.SITE_URL) {
	throw new Error("Set SITE_URL (e.g. http://sales-agent-test.localhost:8000) and E2E_PASSWORD.");
}

module.exports = defineConfig({
	testDir: "./tests",
	timeout: 180_000,
	expect: { timeout: 15_000 },
	workers: 1, // tests share the two fixture tenants
	fullyParallel: false,
	retries: 0,
	reporter: [["list"], ["html", { open: "never" }]],
	use: {
		baseURL: process.env.SITE_URL,
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
	},
});
