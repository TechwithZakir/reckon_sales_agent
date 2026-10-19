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
		this.$body = $('<div style="padding: 12px 0"></div>').appendTo(page.main);
	}

	load() {
		frappe.call("reckon_sales_agent.api.campaign_analytics").then((r) => this.render(r.message || []));
	}

	render(rows) {
		const e = frappe.utils.escape_html;
		const pct = (v) => `${e(String(v ?? 0))}%`;
		if (!rows.length) {
			this.$body.html(`<div class="text-muted">${__("No campaigns yet.")}</div>`);
			return;
		}
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
					const insight = c.insight
						? `<div class="small"><b>${__("AI insight")}</b> (${e(frappe.datetime.str_to_user(c.insight.generated_on))}):
							${e(c.insight.summary || "")}<pre style="white-space:pre-wrap">${e(c.insight.recommendations || "")}</pre></div>`
						: `<div class="small text-muted">${__("No analysis yet.")}</div>`;
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
		this.$body.find("button.analyze").on("click", (ev) => {
			frappe
				.call({ method: "reckon_sales_agent.api.analyze_campaign", args: { campaign: ev.currentTarget.dataset.name }, freeze: true })
				.then(() => this.load());
		});
	}
}
