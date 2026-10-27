// Campaign Analytics: a dashboard from discovery to revenue, with the agents' work and the pilots.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-analytics"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Campaign Analytics"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.dashboard = new Dashboard(page);
	};
	frappe.pages["sales-analytics"].on_page_show = (wrapper) => wrapper.dashboard && wrapper.dashboard.load();

	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v) => (v == null ? "0" : Number(v).toLocaleString());
	const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5"];
	// The new agents are drawn in their family's colour (five series stay readable).
	const AGENTS = { Research: __("Research & data"), Content: __("Content & social"), Governance: __("Governance"),
		Engagement: __("Engagement & conversations"), Analytics: __("Analytics & forecast") };
	const SOURCES = { brave_place_search: __("Brave Places"), brave_llm_context: __("Brave LLM Context"),
		brave_web_search: __("Brave Web Search"), multi_source: __("Smart Sources"), fixture: __("Demo data"),
		scrapingdog_google_maps: __("Google Maps · Scrapingdog"), scrapingbee_google_maps: __("Google Maps · ScrapingBee"),
		serpapi_google_maps: __("Google Maps · SerpAPI"), google_places_api: __("Google Places API"),
		google_maps_browser_experimental: __("Maps Browser Bot"), manual_import: __("Manual import") };
	const VERDICTS = { too_early: [__("Too early"), "warning"], iterate: [__("Iterate"), "warning"],
		scale: [__("Ready to scale"), "good"], stop: [__("Stop"), "critical"] };

	class Dashboard {
		constructor(page) {
			this.page = page;
			this.days = 30;
			this.campaign = "";
			this.$root = $('<div class="sad"></div>').appendTo(page.main);
			this.$tip = $('<div class="sad-tip"></div>').appendTo(document.body);
			$(window).on("resize.sad", frappe.utils.debounce(() => this.data && this.render(), 200));
		}

		color(v) {
			return getComputedStyle(this.$root[0]).getPropertyValue(v).trim();
		}

		load() {
			this.$root.css("opacity", 0.6);
			return frappe.xcall("reckon_sales_agent.api.analytics_dashboard", { days: this.days, campaign: this.campaign })
				.then((d) => { this.data = d; this.render(); })
				.finally(() => this.$root.css("opacity", 1));
		}

		render() {
			const d = this.data;
			const label = { 7: __("7 days"), 30: __("30 days"), 90: __("90 days"), 180: __("180 days") };
			this.$root.html(`
				<div class="sad-bar"><div><h2>${__("From discovery to revenue")}</h2>
					<p>${__("Last {0}, compared with the {0} before.", [label[this.days] || this.days])}</p></div>
					<div class="sad-filters">
						<div class="sad-seg" role="group" aria-label="${__("Period")}">${[7, 30, 90, 180].map((n) =>
							`<button data-days="${n}" class="${n === this.days ? "on" : ""}">${e(label[n])}</button>`).join("")}</div>
						<select class="form-control sad-campaign"><option value="">${__("All campaigns")}</option>
							${(d.campaign_options || []).map((c) => `<option value="${e(c.name)}" ${c.name === this.campaign ? "selected" : ""}>${e(c.campaign_name)}</option>`).join("")}</select>
					</div></div>
				<div class="sad-kpis"></div>
				<div class="sad-grid"><div class="sad-card sad-trend"></div><div class="sad-card sad-funnel"></div></div>
				<div class="sad-grid even"><div class="sad-card sad-activity"></div><div class="sad-card sad-calls"></div></div>
				<div class="sad-card sad-channels" style="margin-bottom:12px"></div>
				<div class="sad-grid even"><div class="sad-card sad-segments"></div><div class="sad-card sad-sources"></div></div>
				<div class="sad-card sad-camp" style="margin-bottom:12px"></div>
				<div class="sad-card sad-advice"></div>`);
			this.$root.find(".sad-seg button").on("click", (ev) => { this.days = Number(ev.currentTarget.dataset.days); this.load(); });
			this.$root.find(".sad-campaign").on("change", (ev) => { this.campaign = ev.target.value; this.load(); });
			this.render_kpis(d.kpis);
			this.render_trend(this.$root.find(".sad-trend"), d.trend);
			this.render_funnel(this.$root.find(".sad-funnel"), d.funnel);
			this.render_activity(this.$root.find(".sad-activity"), d.activity, d.trend);
			this.render_calls(this.$root.find(".sad-calls"), d.calls, d.call_outcomes, d.triage);
			this.render_channels(this.$root.find(".sad-channels"), d.channels);
			this.render_table(this.$root.find(".sad-segments"), __("Segments"), __("Which customer segments turn into replies and deals"), d.by_segment);
			this.render_table(this.$root.find(".sad-sources"), __("Lead sources"), __("Which sources find leads that convert"), d.by_source);
			this.render_campaigns(this.$root.find(".sad-camp"), d.campaigns);
			this.$root.find(".sad-advice").html(`<h3>${__("Recommendations")}</h3>
				<ul class="sad-recs">${(d.recommendations || []).map((r) => `<li>${e(r)}</li>`).join("")}</ul>`);
		}

		// ------------------------------------------------------------ stat tiles
		render_kpis(k) {
			const tiles = [
				["leads", __("Leads found")], ["qualified", __("Qualified")], ["in_crm", __("Added to CRM")],
				["contacted", __("Outreach (messages and answered calls)")], ["reply_rate", __("Reply rate"), "%"],
				["positive", __("Positive replies")],
				["deals", __("Deals")], ["won_value", __("Won value"), "money"],
			];
			this.$root.find(".sad-kpis").html(tiles.map(([key, name, unit]) => {
				const t = k[key] || {};
				const value = unit === "money" ? format_currency(t.value || 0) : unit === "%" ? `${t.value || 0}%` : num(t.value);
				let delta = `<span class="delta flat">${__("No earlier data")}</span>`;
				if (t.delta_pct != null) {
					const dir = t.delta_pct > 0 ? "up" : t.delta_pct < 0 ? "down" : "flat";
					const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "■";
					delta = `<span class="delta ${dir}"><span aria-hidden="true">${arrow}</span>${Math.abs(t.delta_pct)}% ${__("vs previous")}</span>`;
				}
				return `<div class="sad-kpi"><div class="label">${e(name)}</div><div class="value">${value}</div>${delta}</div>`;
			}).join(""));
		}

		// ------------------------------------------------------------ line chart with crosshair
		render_trend(el, t) {
			const series = [
				{ key: "leads", label: __("Leads found"), color: this.color("--s1") },
				{ key: "contacted", label: __("Contacted"), color: this.color("--s2") },
				{ key: "replies", label: __("Replies"), color: this.color("--s3") },
				{ key: "positive", label: __("Positive"), color: this.color("--s4") },
			];
			const dates = Array.from({ length: t.days }, (_, i) => frappe.datetime.add_days(t.start, i));
			el.html(`<h3>${__("Daily activity")}</h3><div class="sub">${__("Leads the agents found, and the outreach that followed")}</div>
				<div class="sad-legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${e(s.label)}</span>`).join("")}</div>
				<div class="plot"></div>${this.table_details([__("Day"), ...series.map((s) => s.label)],
					dates.map((day, i) => [frappe.datetime.str_to_user(day), ...series.map((s) => t[s.key][i])]))}`);
			const plot = el.find(".plot");
			const W = Math.max(280, plot.width()), H = 220, L = 34, R = 76, T = 10, B = 24;
			const max = Math.max(1, ...series.flatMap((s) => t[s.key]));
			const nice = Math.max(1, Math.ceil(max / 4)) * 4;
			const x = (i) => L + (t.days === 1 ? 0 : (i * (W - L - R)) / (t.days - 1));
			const y = (v) => T + (H - T - B) * (1 - v / nice);
			const ticks = [0, nice / 4, nice / 2, (3 * nice) / 4, nice];
			const every = Math.ceil(t.days / 6);
			let svg = ticks.map((v) => `<line class="${v ? "gridline" : "baseline"}" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
				<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${num(Math.round(v))}</text>`).join("");
			svg += dates.map((day, i) => (i % every === 0 || i === t.days - 1)
				? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${e(frappe.datetime.str_to_user(day).slice(0, 5))}</text>` : "").join("");
			// Direct labels at the line ends, nudged apart so they never collide.
			// Preview: labels near zero piled onto the axis, so after spacing them they are lifted back inside the plot.
			const ends = series.map((s) => ({ s, y: y(t[s.key][t.days - 1]) })).sort((a, b) => a.y - b.y);
			ends.forEach((end, i) => { if (i && end.y - ends[i - 1].y < 13) end.y = ends[i - 1].y + 13; });
			const overflow = ends.length ? ends[ends.length - 1].y - (H - B - 6) : 0;
			if (overflow > 0) ends.forEach((end) => { end.y -= overflow; });
			svg += series.map((s) => {
				const pts = t[s.key].map((v, i) => `${x(i)},${y(v)}`).join(" ");
				return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
			}).join("");
			svg += ends.map((end) => `<text class="lbl" x="${W - R + 8}" y="${end.y + 4}">${e(end.s.label)}</text>`).join("");
			svg += `<line class="cross" y1="${T}" y2="${H - B}" style="display:none"/>
				${series.map((s) => `<circle class="dot" data-k="${s.key}" r="4" fill="${s.color}" stroke="${this.color("--surface") || "#fff"}" stroke-width="2" style="display:none"/>`).join("")}
				<rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>`;
			plot.html(`<svg width="${W}" height="${H}" role="img" aria-label="${__("Daily activity line chart")}">${svg}</svg>`);
			const $svg = plot.find("svg");
			$svg.find(".hit").on("mousemove", (ev) => {
				const box = $svg[0].getBoundingClientRect();
				const i = Math.max(0, Math.min(t.days - 1, Math.round(((ev.clientX - box.left - L) / (W - L - R)) * (t.days - 1))));
				$svg.find(".cross").attr({ x1: x(i), x2: x(i) }).show();
				series.forEach((s) => $svg.find(`.dot[data-k="${s.key}"]`).attr({ cx: x(i), cy: y(t[s.key][i]) }).show());
				this.tip(ev, frappe.datetime.str_to_user(dates[i]), series.map((s) => [s.label, num(t[s.key][i]), s.color]));
			}).on("mouseleave", () => { $svg.find(".cross, .dot").hide(); this.$tip.hide(); });
		}

		// ------------------------------------------------------------ funnel (ordinal one-hue ramp)
		render_funnel(el, f) {
			el.html(`<h3>${__("Pipeline")}</h3><div class="sub">${__("Leads found in the period and how far they got")}</div>`);
			if (!f) return el.append(`<div class="sad-empty">${__("No leads in this period yet.")}</div>`);
			const stages = [["prospects", __("Found")], ["approved", __("Approved")], ["in_crm", __("In CRM")],
				["contacted", __("Contacted")], ["replied", __("Replied")], ["positive", __("Positive")],
				["deals", __("Deals")], ["won", __("Won")]];
			const top = Math.max(1, f.prospects);
			// Each stage against the stage it comes from: phone-first leads are contacted without being in the CRM,
			// so "contacted" is measured against "approved" (the preview showed "164% of in CRM").
			const from = { approved: "prospects", in_crm: "approved", contacted: "approved", replied: "contacted",
				positive: "replied", deals: "contacted", won: "deals" };
			const names = Object.fromEntries(stages);
			el.append(`<div class="sad-funnel">${stages.map(([k, name], i) => {
				const base = from[k] ? f[from[k]] : null;
				const conv = base ? `${Math.round((100 * f[k]) / base)}% ${__("of {0}", [names[from[k]].toLowerCase()])}` : "";
				return `<div class="row" title="${e(name)}: ${num(f[k])}"><span>${e(name)}</span>
					<div class="track"><div class="fill" style="width:${(100 * f[k]) / top}%;background:var(--q${Math.min(8, i + 1)})"></div></div>
					<span class="n">${num(f[k])}</span>${conv ? `<span class="conv">${e(conv)}</span>` : ""}</div>`;
			}).join("")}</div>`);
		}

		// ------------------------------------------------------------ stacked bars: agent work per day
		render_activity(el, a, t) {
			const agents = a.agents.filter((g) => a.series[g].some(Boolean));
			const colors = Object.fromEntries(a.agents.map((g, i) => [g, this.color(SERIES[i])]));
			const dates = Array.from({ length: t.days }, (_, i) => frappe.datetime.add_days(t.start, i));
			el.html(`<h3>${__("Agent work")}</h3><div class="sub">${__("Actions the agents took each day")}</div>
				<div class="sad-legend">${agents.map((g) => `<span><i style="background:${colors[g]}"></i>${e(AGENTS[g])}</span>`).join("")}</div>
				<div class="plot"></div>${this.table_details([__("Day"), ...agents.map((g) => AGENTS[g])],
					dates.map((day, i) => [frappe.datetime.str_to_user(day), ...agents.map((g) => a.series[g][i])]))}`);
			if (!agents.length) return el.find(".plot").html(`<div class="sad-empty">${__("No agent activity in this period.")}</div>`);
			const plot = el.find(".plot");
			const W = Math.max(260, plot.width()), H = 200, L = 34, T = 8, B = 24;
			const totals = dates.map((_, i) => agents.reduce((sum, g) => sum + a.series[g][i], 0));
			const nice = Math.max(4, Math.ceil(Math.max(...totals) / 4) * 4);
			const slot = (W - L) / t.days, bw = Math.max(2, Math.min(24, slot * 0.7));
			const y = (v) => T + (H - T - B) * (1 - v / nice);
			const every = Math.ceil(t.days / 6);
			let svg = [0, nice / 2, nice].map((v) => `<line class="${v ? "gridline" : "baseline"}" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/>
				<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${num(v)}</text>`).join("");
			dates.forEach((day, i) => {
				let base = 0;
				const x0 = L + i * slot + (slot - bw) / 2;
				agents.forEach((g, j) => {
					const v = a.series[g][i];
					if (!v) return;
					const top = j === agents.length - 1 || agents.slice(j + 1).every((h) => !a.series[h][i]);
					const h = Math.max(1, y(base) - y(base + v) - 2); // 2px surface gap between segments
					svg += `<rect x="${x0}" y="${y(base + v)}" width="${bw}" height="${h}" fill="${colors[g]}" rx="${top ? 3 : 0}"/>`;
					base += v;
				});
				if (i % every === 0 || i === t.days - 1) {
					svg += `<text x="${x0 + bw / 2}" y="${H - 6}" text-anchor="middle">${e(frappe.datetime.str_to_user(day).slice(0, 5))}</text>`;
				}
				svg += `<rect class="hit" data-i="${i}" x="${L + i * slot}" y="${T}" width="${slot}" height="${H - T - B}" fill="transparent"/>`;
			});
			plot.html(`<svg width="${W}" height="${H}" role="img" aria-label="${__("Agent work stacked bar chart")}">${svg}</svg>`);
			plot.find(".hit").on("mousemove", (ev) => {
				const i = Number(ev.currentTarget.dataset.i);
				this.tip(ev, `${frappe.datetime.str_to_user(dates[i])} · ${num(totals[i])}`,
					agents.slice().reverse().map((g) => [AGENTS[g], num(a.series[g][i]), colors[g]]));
			}).on("mouseleave", () => this.$tip.hide());
		}

		// ------------------------------------------------------------ calls and AI triage
		render_calls(el, c, outcomes, triage) {
			const rows = [["call_interested", __("Interested")], ["call_callback", __("Call back")],
				["call_not_interested", __("Not interested")], ["call_no_answer", __("No answer")], ["call_wrong_number", __("Wrong number")]];
			const max = Math.max(1, ...rows.map(([k]) => outcomes[k] || 0));
			const tmax = Math.max(1, triage.approve, triage.reject, triage.unsure);
			el.html(`<h3>${__("Calls and AI triage")}</h3><div class="sub">${__("Phone-first pilots, and how the AI sorted borderline leads")}</div>
				<div class="sad-mini">
					<div><b>${num(c.calls)}</b><span>${__("calls assigned")}</span></div>
					<div><b>${num(c.logged)}</b><span>${__("outcomes logged")}</span></div>
					<div><b>${c.reach_rate}%</b><span>${__("reached")}</span></div>
					<div><b>${num(c.interested)}</b><span>${__("interested")}</span></div></div>
				<div class="sad-hbars">${rows.map(([k, name]) => `<div class="row"><span>${e(name)}</span>
					<div><div class="fill" style="width:${(100 * (outcomes[k] || 0)) / max}%"></div></div><span class="n">${num(outcomes[k] || 0)}</span></div>`).join("")}</div>
				<div class="sub" style="margin-top:12px">${__("AI triage verdicts")}</div>
				<div class="sad-hbars">${[["approve", __("Looks like a fit")], ["reject", __("Misfit")], ["unsure", __("Unsure")]].map(([k, name]) =>
					`<div class="row"><span>${e(name)}</span><div><div class="fill" style="width:${(100 * (triage[k] || 0)) / tmax}%;background:var(--s3)"></div></div>
					<span class="n">${num(triage[k] || 0)}</span></div>`).join("")}</div>`);
		}

		// ------------------------------------------------------------ channels
		render_channels(el, c) {
			const minutes = (v) => (v == null ? "–" : `${num(v)} ${__("min")}`);
			el.html(`<h3>${__("Channels")}</h3><div class="sub">${__("Where leads talk to you, how fast they get an answer, and what it brings")}</div>
				<div class="sad-mini">
					<div><b>${num(c.chats)}</b><span>${__("chats")}</span></div>
					<div><b>${num(c.comments)}</b><span>${__("buying comments")}</span></div>
					<div><b>${num(c.instant)}</b><span>${__("answered at once")}</span></div>
					<div><b>${minutes(c.median_minutes)}</b><span>${__("median time to answer")}</span></div></div>`);
			if (!c.rows.length) return el.append(`<div class="sad-empty">${__("No conversations in this period.")}</div>`);
			const max = Math.max(1, ...c.rows.map((r) => r.inbound));
			const NAMES = { "Web Chat": __("Website chat"), Call: __("Calls") };
			el.append(`<div class="tw"><table class="t"><thead><tr><th>${__("Channel")}</th><th>${__("Messages in")}</th>
				<th>${__("Answered")}</th><th>${__("Median answer")}</th><th>${__("New leads")}</th><th>${__("Deals")}</th></tr></thead><tbody>
				${c.rows.map((r) => `<tr><td>${e(NAMES[r.channel] || __(r.channel))}</td>
					<td><span class="inbar" style="width:${Math.round((48 * r.inbound) / max)}px"></span>${num(r.inbound)}</td>
					<td>${num(r.answered)}</td><td>${minutes(r.median_minutes)}</td><td>${num(r.leads)}</td>
					<td>${num(r.deals)}</td></tr>`).join("")}</tbody></table></div>`);
		}

		// ------------------------------------------------------------ attribution tables with inline bars
		render_table(el, title, sub, groups) {
			el.html(`<h3>${e(title)}</h3><div class="sub">${e(sub)}</div>`);
			if (!groups || !groups.length) return el.append(`<div class="sad-empty">${__("No data yet.")}</div>`);
			const max = Math.max(1, ...groups.map((g) => g.prospects));
			// Tables scroll inside their card on narrow screens (the preview clipped "Won value").
			el.append(`<div class="tw"><table class="t"><thead><tr><th>${e(title)}</th><th>${__("Leads")}</th><th>${__("Contacted")}</th>
				<th>${__("Replied")}</th><th>${__("Positive")}</th><th>${__("Deals")}</th><th>${__("Won value")}</th></tr></thead><tbody>
				${groups.map((g) => `<tr><td>${e(SOURCES[g.label] || __(g.label))}</td>
					<td><span class="inbar" style="width:${Math.round((48 * g.prospects) / max)}px"></span>${num(g.prospects)}</td>
					<td>${num(g.contacted)}</td><td>${num(g.replied)} <span class="rate">${g.reply_rate}%</span></td>
					<td>${num(g.positive)}</td><td>${num(g.deals)} <span class="rate">${g.deal_rate}%</span></td>
					<td>${format_currency(g.won_value || 0)}</td></tr>`).join("")}</tbody></table></div>`);
		}

		// ------------------------------------------------------------ campaigns
		render_campaigns(el, rows) {
			el.html(`<h3>${__("Campaigns")}</h3><div class="sub">${__("Outreach results, pilots and AI analysis")}</div>`);
			if (!rows.length) return el.append(`<div class="sad-empty">${__("No campaigns yet. The Content agent drafts one when a segment has enough approved leads.")}</div>`);
			el.append(`<div class="tw"><table class="t"><thead><tr><th>${__("Campaign")}</th><th>${__("Members")}</th><th>${__("Sent")}</th>
				<th>${__("Reply rate")}</th><th>${__("Positive")}</th><th>${__("Deals")}</th><th>${__("Pilot")}</th><th></th></tr></thead><tbody>
				${rows.map((c) => {
					const m = c.metrics || {};
					const v = VERDICTS[c.pilot_verdict];
					const pilot = c.pilot_mode ? `<span class="sad-pill ${v ? v[1] : ""}" title="${e(c.pilot_summary || "")}"><span class="dot"></span>${e(v ? v[0] : __("Not measured"))}</span>` : `<span class="muted">—</span>`;
					return `<tr><td><a href="/desk/sales-campaign/${encodeURIComponent(c.name)}">${e(c.campaign_name)}</a>
						<div class="muted">${e(__(c.status))}</div></td>
						<td>${num(m.members)}</td><td>${num((m.totals || {}).outreach)}</td><td>${m.reply_rate || 0}%</td>
						<td>${m.positive_reply_rate || 0}%</td><td>${num(m.deals)}</td><td>${pilot}</td>
						<td><div class="actions">${c.pilot_mode ? `<button class="btn btn-xs btn-default pilot" data-name="${e(c.name)}">${__("Measure")}</button>` : ""}
							<button class="btn btn-xs btn-default analyze" data-name="${e(c.name)}">${__("Analyze with AI")}</button></div></td></tr>`;
				}).join("")}</tbody></table></div>`);
			el.find("button.pilot").on("click", (ev) => frappe.call({ method: "reckon_sales_agent.api.pilot_report",
				args: { campaign: ev.currentTarget.dataset.name }, freeze: true }).then(() => this.load()));
			el.find("button.analyze").on("click", (ev) => frappe.call({ method: "reckon_sales_agent.api.analyze_campaign",
				args: { campaign: ev.currentTarget.dataset.name }, freeze: true }).then(() => this.load()));
		}

		// ------------------------------------------------------------ helpers
		table_details(head, rows) {
			return `<details class="tbl"><summary>${__("Show as a table")}</summary><table class="t"><thead><tr>${head.map((h) =>
				`<th>${e(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((v) => `<td>${e(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></details>`;
		}

		tip(ev, heading, rows) {
			this.$tip.html(`<div class="h">${e(heading)}</div>${rows.map(([k, v, color]) =>
				`<div class="r"><span><i style="background:${color}"></i>${e(k)}</span><b>${e(v)}</b></div>`).join("")}`).show();
			const w = this.$tip.outerWidth(), h = this.$tip.outerHeight();
			const left = ev.clientX + 14 + w > window.innerWidth ? ev.clientX - w - 14 : ev.clientX + 14;
			this.$tip.css({ left, top: Math.max(8, ev.clientY - h - 10) });
		}
	}
})();
