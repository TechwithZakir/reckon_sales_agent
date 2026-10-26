frappe.pages["sales-analytics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Campaign Analytics"),
		single_column: true,
	});
	page.set_primary_action(__("Refresh"), () => wrapper.analytics.load());
	wrapper.analytics = new CampaignAnalytics(page);
};

frappe.pages["sales-analytics"].on_page_show = function (wrapper) {
	wrapper.analytics && wrapper.analytics.load();
};

class CampaignAnalytics {
	constructor(page) {
		this.page = page;
		this.$overview = $('<div style="padding: 12px 0 0"></div>').appendTo(page.main);
		this.$body = $('<div style="padding: 12px 0"></div>').appendTo(page.main);
	}

	load() {
		frappe.call("reckon_sales_agent.api.analytics_overview").then((r) => this.render_overview(r.message || {}));
		frappe.call("reckon_sales_agent.api.campaign_analytics").then((r) => this.render(r.message || []));
	}

	// Attribution: which segments and sources turn into deals and revenue.
	render_overview(o) {
		const e = frappe.utils.escape_html;
		const t = o.totals;
		if (!t) {
			this.$overview.html(`<div class="text-muted">${__("No prospects in the last {0} days yet.", [o.days || 180])}</div>`);
			return;
		}
		const money = (v) => format_currency(v || 0);
		const table = (title, rows) => `<div class="col-md-6"><h6>${e(title)}</h6>
			<table class="table table-sm"><thead><tr><th></th><th>${__("Prospects")}</th><th>${__("Contacted")}</th>
			<th>${__("Replied")}</th><th>${__("Deals")}</th><th>${__("Won")}</th><th>${__("Won value")}</th></tr></thead><tbody>
			${rows.slice(0, 8).map((g) => `<tr><td>${e(__(g.label))}</td><td>${g.prospects}</td><td>${g.contacted}</td>
				<td>${g.replied} <span class="text-muted small">(${g.reply_rate}%)</span></td>
				<td>${g.deals} <span class="text-muted small">(${g.deal_rate}%)</span></td><td>${g.won}</td>
				<td>${money(g.won_value)}</td></tr>`).join("")}</tbody></table></div>`;
		const stats = [[__("Prospects"), t.prospects], [__("Approved"), t.approved], [__("In CRM"), t.in_crm],
			[__("Contacted"), t.contacted], [__("Replied"), t.replied], [__("Meetings"), t.meetings],
			[__("Deals"), t.deals], [__("Won"), t.won]];
		this.$overview.html(`<div class="frappe-card" style="padding:16px; margin-bottom:12px">
			<h5 style="margin:0 0 12px">${__("From discovery to revenue (last {0} days)", [o.days])}
				<span class="text-muted small" style="margin-left:8px">${__("Won value")}: ${money(t.won_value)}</span></h5>
			<div class="row">${stats.map(([k, v]) => `<div class="col-sm-3 col-xs-6" style="margin-bottom:8px">
				<div class="text-muted small">${e(k)}</div><div style="font-size:18px;font-weight:600">${v}</div></div>`).join("")}</div>
			<div class="row" style="margin-top:8px">${table(__("By segment"), o.by_segment || [])}${table(__("By source"), o.by_source || [])}</div>
			<div class="small"><b>${__("Recommendations")}</b><ul style="margin:6px 0 0">${(o.recommendations || [])
				.map((r) => `<li>${e(r)}</li>`).join("")}</ul></div></div>`);
	}

	render(rows) {
		const e = frappe.utils.escape_html;
		const pct = (v) => `${e(String(v ?? 0))}%`;
		if (!rows.length) {
			this.$body.html(`<div class="text-muted">${__("No campaigns yet.")}</div>`);
			return;
		}
		const verdicts = { too_early: __("Too early"), iterate: __("Iterate"), scale: __("Ready to scale"), stop: __("Stop") };
		this.$body.html(
			rows
				.map((c) => {
					const m = c.metrics || {};
					const t = m.totals || {};
					const channels = Object.entries(m.by_channel || {})
						.map(([name, b]) => `<tr><td>${e(__(name))}</td><td>${e(String(b.outreach))}</td>
							<td>${pct(b.reply_rate)}</td><td>${pct(b.positive_rate)}</td></tr>`)
						.join("");
					const steps = Object.entries(m.by_step || {})
						.map(([step, b]) => `<tr><td>${__("Step")} ${e(step)}</td><td>${e(String(b.outreach))}</td>
							<td>${pct(b.reply_rate)}</td><td>${pct(b.positive_rate)}</td></tr>`)
						.join("");
					const insight = (c.insight
						? `<div class="small"><b>${__("AI insight")}</b> (${e(frappe.datetime.str_to_user(c.insight.generated_on))}):
							${e(c.insight.summary || "")}<pre style="white-space:pre-wrap">${e(c.insight.recommendations || "")}</pre></div>`
						: `<div class="small text-muted">${__("No analysis yet.")}</div>`)
						+ (c.pilot_mode ? `<div class="small" style="margin-top:6px"><b>${__("Pilot")}</b>
							<span class="indicator-pill ${c.pilot_verdict === "scale" ? "green" : c.pilot_verdict === "stop" ? "red" : "orange"}">
							${e(verdicts[c.pilot_verdict] || __("Not measured"))}</span> ${e(c.pilot_summary || "")}
							<button class="btn btn-xs btn-default pilot" data-name="${e(c.name)}" style="margin-left:6px">${__("Measure now")}</button></div>` : "");
					return `<div class="frappe-card" style="padding:16px; margin-bottom:12px">
						<div style="display:flex; justify-content:space-between; align-items:center">
							<h5 style="margin:0"><a href="/app/sales-campaign/${encodeURIComponent(c.name)}">${e(c.campaign_name)}</a>
								<span class="indicator-pill gray">${e(__(c.status))}</span></h5>
							<button class="btn btn-xs btn-default analyze" data-name="${e(c.name)}">${__("Analyze with AI")}</button>
						</div>
						<div class="row" style="margin:12px 0">
							${[[__("Members"), m.members], [__("Sent"), t.outreach], [__("Reply rate"), pct(m.reply_rate)],
							   [__("Positive"), pct(m.positive_reply_rate)], [__("Meetings"), t.meetings], [__("Deals"), m.deals],
							   [__("Conversion"), pct(m.conversion_rate)], [__("Unsubscribe"), pct(m.unsubscribe_rate)]]
								.map(([label, value]) => `<div class="col-sm-3 col-xs-6"><div class="text-muted small">${e(label)}</div>
									<div style="font-size:18px; font-weight:600">${typeof value === "string" ? value : e(String(value ?? 0))}</div></div>`)
								.join("")}
						</div>
						<table class="table table-sm"><thead><tr><th>${__("Channel / step")}</th><th>${__("Sent")}</th>
							<th>${__("Reply rate")}</th><th>${__("Positive")}</th></tr></thead><tbody>${channels}${steps}</tbody></table>
						${insight}
					</div>`;
				})
				.join("")
		);
		this.$body.find("button.pilot").on("click", (ev) => {
			frappe
				.call({ method: "reckon_sales_agent.api.pilot_report", args: { campaign: ev.currentTarget.dataset.name }, freeze: true })
				.then(() => this.load());
		});
		this.$body.find("button.analyze").on("click", (ev) => {
			frappe
				.call({ method: "reckon_sales_agent.api.analyze_campaign", args: { campaign: ev.currentTarget.dataset.name }, freeze: true })
				.then(() => this.load());
		});
	}
}
