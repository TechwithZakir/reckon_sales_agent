frappe.pages["sales-agent"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Sales Agent"),
		single_column: true,
	});
	page.set_primary_action(__("New Discovery Campaign"), () =>
		frappe.new_doc("Sales Discovery Campaign")
	);
	page.add_inner_button(__("Review Prospects"), () => frappe.set_route("sales-review"));
	page.add_inner_button(__("Campaigns"), () => frappe.set_route("List", "Sales Campaign"));
	page.add_inner_button(__("Open CRM"), () => (window.location.href = "/crm"));
	wrapper.sales_agent = new SalesAgentHome(page);
};

frappe.pages["sales-agent"].on_page_show = function (wrapper) {
	wrapper.sales_agent && wrapper.sales_agent.refresh();
};

class SalesAgentHome {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="sales-agent-home" style="padding: 12px 0"></div>').appendTo(page.main);
	}

	refresh() {
		frappe.call("reckon_sales_agent.api.dashboard").then((r) => this.render(r.message || {}));
	}

	render(data) {
		const e = frappe.utils.escape_html;
		const tile = (label, value, route) => `
			<div class="col-sm-3" style="margin-bottom: 12px">
				<a class="frappe-card" style="display:block; padding:16px; text-decoration:none" href="${route}">
					<div class="text-muted small">${e(label)}</div>
					<div style="font-size:24px; font-weight:600">${e(String(value ?? 0))}</div>
				</a>
			</div>`;
		const warnings = [];
		if (data.kill_switch) warnings.push(__("All outbound activity is paused (kill switch)."));
		if (!data.outbound_enabled)
			warnings.push(__("Outbound sending is off: approved messages are logged as dry runs."));
		const usage = Object.entries(data.usage || {})
			.map(([type, u]) => {
				const pct = u.limit ? Math.min(100, Math.round((100 * u.used) / u.limit)) : 0;
				return `<div style="margin-bottom:8px">
					<div class="small">${e(__(type))}: ${e(String(u.used))} / ${e(String(u.limit))}</div>
					<div class="progress" style="height:6px"><div class="progress-bar" style="width:${pct}%"></div></div>
				</div>`;
			})
			.join("");
		const jobs = (data.recent_jobs || [])
			.map(
				(j) => `<tr>
					<td><a href="/app/sales-discovery-job/${encodeURIComponent(j.name)}">${e(j.name)}</a></td>
					<td>${e(j.discovery_campaign || "")}</td>
					<td>${e(__(j.status))}</td>
					<td>${e(String(j.progress_done || 0))}/${e(String(j.progress_total || 0))}</td>
					<td>${e(String(j.created_count || 0))}</td>
				</tr>`
			)
			.join("");
		this.$body.html(`
			${warnings.map((w) => `<div class="alert alert-warning">${e(w)}</div>`).join("")}
			<div class="row">
				${tile(__("Prospects"), data.prospects, "/app/sales-prospect")}
				${tile(__("Waiting for review"), data.pending_review, "/desk/sales-review")}
				${tile(__("Qualified"), data.qualified, "/app/sales-prospect?qualification_status=Qualified")}
				${tile(__("In CRM"), data.in_crm, "/crm/leads")}
				${tile(__("Running jobs"), data.running_jobs, "/app/sales-discovery-job")}
				${tile(__("Active campaigns"), data.active_campaigns, "/app/sales-campaign?status=Active")}
				${tile(__("Drafts to approve"), data.drafts_waiting, "/app/sales-outreach-message?status=Draft")}
				${tile(__("Replies"), data.replies, "/app/sales-communication-event?event_type=replied")}
			</div>
			<div class="row">
				<div class="col-sm-6"><div class="frappe-card" style="padding:16px">
					<h5>${__("This month's plan usage")}</h5>${usage}
				</div></div>
				<div class="col-sm-6"><div class="frappe-card" style="padding:16px">
					<h5>${__("Recent discovery jobs")}</h5>
					<table class="table table-sm"><thead><tr>
						<th>${__("Job")}</th><th>${__("Campaign")}</th><th>${__("Status")}</th>
						<th>${__("Searches")}</th><th>${__("New")}</th>
					</tr></thead><tbody>${jobs || `<tr><td colspan="5" class="text-muted">${__("No jobs yet")}</td></tr>`}</tbody></table>
				</div></div>
			</div>
			<div class="frappe-card" style="padding:16px; margin-top:12px">
				<h5>${__("How it works")}</h5>
				<ol class="small">
					<li>${__("Create a discovery campaign, preview the planned searches and start it.")}</li>
					<li>${__("The agent researches each prospect's public website and scores the fit with evidence.")}</li>
					<li>${__("Approve the good ones in Prospect Review: they become CRM Leads.")}</li>
					<li>${__("Build an email campaign; a manager approves it and each message before anything is sent.")}</li>
				</ol>
			</div>`);
	}
}
