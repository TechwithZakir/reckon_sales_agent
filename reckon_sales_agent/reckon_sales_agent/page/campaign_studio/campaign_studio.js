// Campaign Studio: audiences, campaigns, recipients, and the copilot and autopilot that help run them.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["campaign-studio"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Campaign Studio"), single_column: true });
		page.add_inner_button(__("Message Templates"), () => frappe.set_route("sales-templates"));
		page.add_inner_button(__("Capture Studio"), () => frappe.set_route("capture-studio"));
		page.add_inner_button(__("Automation Studio"), () => frappe.set_route("automation-studio"));
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.studio = new Studio(page);
	};
	frappe.pages["campaign-studio"].on_page_show = (wrapper) => wrapper.studio && wrapper.studio.show();

	const API = "reckon_sales_agent.api_campaign_studio.";
	const CORE = "reckon_sales_agent.api.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v) => Number(v || 0).toLocaleString();
	const pct = (v) => `${Number(v || 0).toFixed(1).replace(/\.0$/, "")}%`;
	const MANAGER_ROLES = ["Reckon Sales Agent Admin", "Reckon Sales Agent Manager", "Reckon Vendor Superuser", "System Manager"];
	// The server decides who may change anything; this only hides buttons that would be refused.
	const can_manage = () => frappe.session.user === "Administrator" || MANAGER_ROLES.some((role) => frappe.user.has_role(role));
	const TABS = [["overview", __("Overview")], ["campaigns", __("Campaigns")], ["audiences", __("Audiences")],
		["recipients", __("Recipients")], ["autopilot", __("Copilot & Autopilot")]];
	const TEMP = { "Hot": "hot", "Warm": "warm", "Cold": "cold", "Opted out": "out" };
	const AUDIENCE_TYPES = ["Prospects", "CRM Leads", "CRM Contacts", "Customers", "Specific people", "Segment"];
	const ACTIONS = {
		new_audience: __("New audience"), pilot: __("New campaign"), call_hot: __("See who"), pause: __("Open campaign"),
		narrow_audience: __("Open campaign"), scale: __("Open campaign"), rewrite_subject: __("Open templates"),
		edit_template: __("Open templates"), set_window: __("Set window"),
	};
	const store = {
		get(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (err) { return fallback; } },
		set(key, value) { try { localStorage.setItem(key, value); } catch (err) { /* private window: nothing to remember */ } },
	};

	const tile = (label, value, sub) => `<div class="cst-tile"><span>${label}</span><b>${value}</b><span>${sub || "&nbsp;"}</span></div>`;

	const funnel_html = (engagement) => {
		const c = engagement.counts;
		const top = Math.max(c.sent || 0, 1);
		return `<div class="cst-funnel">${[[__("Sent"), c.sent], [__("Delivered"), c.delivered], [__("Opened"), c.opened],
			[__("Clicked"), c.clicked], [__("Replied"), c.replied]].map(([label, n]) =>
			`<div><span>${label}</span><i style="width:${Math.max(2, Math.round(100 * (n || 0) / top))}%"></i><b>${num(n)}</b></div>`).join("")}</div>
			<div class="cst-muted" style="margin-top:8px">${__("Opens are approximate: some mail apps load images in advance, and scanners are filtered when they identify themselves.")}</div>`;
	};

	const days_html = (by_day) => {
		const days = Object.entries(by_day || {}).slice(-14);
		if (!days.length) return `<div class="cst-empty">${__("No activity yet.")}</div>`;
		const top = Math.max(1, ...days.map(([, v]) => Math.max(v.sent, v.opened)));
		return `<div class="cst-days">${days.map(([day, v]) => `<div title="${e(day)}: ${v.sent} ${__("sent")}, ${v.opened} ${__("opened")}, ${v.clicked} ${__("clicked")}">
			<i class="alt" style="height:${Math.round(100 * v.opened / top)}%"></i><i style="height:${Math.round(100 * v.sent / top)}%"></i><small>${e(day.slice(8))}</small></div>`).join("")}</div>
			<div class="cst-muted">${__("Blue: sent. Green: opened.")}</div>`;
	};

	// "What do you want to do?": each card sets the goal and the shape of the sequence (a delay in days per step); templates are chosen next.
	const QUICK = [
		{ id: "announce", title: __("Make an announcement"), text: __("One message to everyone."), goal: "Event invite", delays: [0], pilot: false },
		{ id: "follow", title: __("Follow up a new lead"), text: __("A first message, then two follow-ups."), goal: "Book a meeting", delays: [0, 3, 7], pilot: false },
		{ id: "reengage", title: __("Re-engage quiet people"), text: __("Two messages, tried on a small group first."), goal: "Re-engage", delays: [0, 5], pilot: true },
		{ id: "event", title: __("Invite to an event"), text: __("An invitation and a reminder."), goal: "Event invite", delays: [0, 3], pilot: false },
		{ id: "upsell", title: __("Offer customers more"), text: __("An offer and one follow-up."), goal: "Upsell", delays: [0, 7], pilot: false },
	];
	const TONE = { good: "ok", ok: "", low: "warn", early: "" };
	const verdict_html = (v, steps) => `<section class="cst-card cst-verdict"><div class="cst-bar"><h3>${e(__(v.headline))}</h3><span class="cst-badge ${TONE[v.tone] || ""}">${e(__(v.tone === "early" ? "Early" : v.tone === "good" ? "Strong" : v.tone === "low" ? "Needs attention" : "Normal"))}</span></div>
		${v.lines.map((l) => `<div>${e(l)}</div>`).join("")}${v.advice.length ? `<div class="cst-muted" style="margin-top:8px">${__("What to try")}: ${v.advice.map(e).join(" ")}</div>` : ""}
		${steps && steps.length > 1 ? `<h4>${__("Where people drop out")}</h4><div class="cst-funnel">${steps.map((s) => `<div style="grid-template-columns:90px 1fr 190px"><span>${e(__(s.label))}</span><i style="width:${Math.max(2, s.of_sent)}%"></i><b>${num(s.count)} · ${pct(s.of_sent)}${s.key === "sent" ? "" : ` (${pct(s.of_previous)} ${__("of the step before")}${s.lost ? `, −${num(s.lost)}` : ""})`}</b></div>`).join("")}</div>` : ""}</section>`;

	const suggestions_html = (list) => (list && list.length ? list.map((s) => `<div class="cst-sug ${e(s.severity)}">
		<b>${e(s.title)}</b>${s.campaign_name ? ` <span class="cst-badge">${e(s.campaign_name)}</span>` : ""}
		<span class="cst-muted">${e(s.detail)}</span>
		${ACTIONS[s.action] ? `<button class="btn btn-default btn-xs cst-act" data-act="${e(s.action)}" data-campaign="${e(s.campaign || "")}">${ACTIONS[s.action]}</button>` : ""}</div>`).join("")
		: `<div class="cst-empty">${__("Nothing to suggest right now.")}</div>`);

	class Studio {
		constructor(page) {
			this.page = page;
			this.tab = store.get("cst_tab", "overview");
			this.$root = $(`<div class="cst"><nav class="cst-tabs">${TABS.map(([key, label]) =>
				`<button class="cst-tab" data-tab="${key}">${label}</button>`).join("")}</nav><div class="cst-body"></div></div>`).appendTo(page.main);
			this.$body = this.$root.find(".cst-body");
			this.$root.find(".cst-tab").on("click", (ev) => this.open(ev.currentTarget.dataset.tab));
			// One set of delegated handlers for the buttons that appear on several tabs.
			this.$body.on("click", ".cst-go", (ev) => {
				const { route, tab } = ev.currentTarget.dataset;
				if (route) frappe.set_route(route);
				else if (tab) this.open(tab);
			});
			this.$body.on("click", ".cst-act", (ev) => this.act(ev.currentTarget.dataset.act, ev.currentTarget.dataset.campaign));
		}

		show() { this.open(this.tab); }

		open(tab) {
			this.tab = TABS.some(([key]) => key === tab) ? tab : "overview";
			store.set("cst_tab", this.tab);
			this.$root.find(".cst-tab").each((_, node) => $(node).toggleClass("on", node.dataset.tab === this.tab));
			this.$body.html(`<div class="cst-empty">${__("Loading…")}</div>`);
			return this[`tab_${this.tab}`]().catch(() => this.$body.html(`<div class="cst-empty">${__("This could not be loaded.")}</div>`));
		}

		act(action, campaign) {
			if (action === "new_audience") return this.audience_dialog();
			if (action === "pilot") return this.campaign_dialog();
			if (action === "set_window") return this.open("autopilot");
			if (["rewrite_subject", "edit_template"].includes(action)) return frappe.set_route("sales-templates");
			return campaign ? this.campaign_detail(campaign) : this.open("campaigns");
		}

		// Overview ---------------------------------------------------------------

		tab_overview() {
			return frappe.xcall(API + "overview").then((d) => {
				const c = d.engagement.counts;
				const r = d.engagement.rates;
				const a = d.autopilot;
				this.$body.html(`
					<div class="cst-tiles">
						${tile(__("Active campaigns"), num(d.campaign_statuses.Active || 0), `${num(d.campaign_statuses["Pending Approval"] || 0)} ${__("waiting for approval")}`)}
						${tile(__("Sent, last 30 days"), num(c.sent))}
						${tile(__("Opened"), pct(r.open_rate), `${num(c.opened)} ${__("of")} ${num(c.sent)}`)}
						${tile(__("Clicked"), pct(r.click_rate), `${num(c.clicked)} ${__("of")} ${num(c.sent)}`)}
						${tile(__("Replied"), pct(r.reply_rate), `${num(c.replied)} ${__("of")} ${num(c.sent)}`)}
						${tile(__("Opted out"), pct(r.unsubscribe_rate), `${num(c.unsubscribed)} ${__("people")}`)}
					</div>
					${a.outbound_enabled ? "" : `<div class="cst-note">${__("Sending is switched off, so campaigns run as tests and reach nobody. Turn it on in Sales Agent Settings when you are ready.")}</div>`}
					${d.pending_approval ? `<div class="cst-note">${__("{0} message drafts are waiting for approval.", [d.pending_approval])}
						<a class="cst-go cst-link" data-route="sales-agent">${__("Open Agent Studio")}</a></div>` : ""}
					<div class="cst-grid">
						<section class="cst-card"><h3>${__("Funnel, last 30 days")}</h3>${funnel_html(d.engagement)}</section>
						<section class="cst-card"><h3>${__("Activity by day")}</h3>${days_html(d.engagement.by_day)}</section>
					</div>
					<section class="cst-card"><h3>${__("Copilot suggests")}</h3>${suggestions_html(d.suggestions)}</section>
					<section class="cst-card"><h3>${__("Autopilot")}: ${e(__(a.level))}</h3><div class="cst-muted">${e(a.descriptions[a.level])}</div>
						<div class="cst-actions" style="margin-top:8px"><button class="btn btn-default btn-xs cst-go" data-tab="autopilot">${__("Change")}</button></div></section>`);
			});
		}

		// Campaigns --------------------------------------------------------------

		tab_campaigns() {
			return frappe.xcall(API + "campaigns").then((rows) => {
				let draft = null;
				try { draft = JSON.parse(store.get("cst_wizard", "{}")); } catch (err) { draft = null; }
				const unfinished = draft && draft.name ? draft : null;
				this.$body.html(`<div class="cst-bar"><h3>${__("Campaigns")}</h3>
					${can_manage() ? `<button class="btn btn-primary btn-sm cst-new-campaign">${__("New campaign")}</button>` : ""}</div>
					${unfinished && can_manage() ? `<div class="cst-note">${__("You have an unfinished campaign: {0}.", [`<b>${e(unfinished.name)}</b>`])} <a class="cst-link cst-w-resume">${__("Continue")}</a></div>` : ""}
					<div class="cst-card"><div class="cst-row head"><span>${__("Campaign")}</span><span>${__("Sent")}</span><span>${__("Opened")}</span>
						<span>${__("Clicked")}</span><span>${__("Replied")}</span><span>${__("Bounced")}</span><span>${__("People")}</span></div>
					${rows.map((r) => `<div class="cst-row click" data-name="${e(r.name)}">
						<span><a>${e(r.campaign_name)}</a> <span class="cst-badge ${e(r.status)}">${e(__(r.status))}</span>
							<div class="cst-chips">${r.channels.map((c) => `<span class="cst-badge">${e(c)}</span>`).join("")}
							${r.audience_name ? `<span class="cst-muted">${e(r.audience_name)}</span>` : ""}</div></span>
						<span>${num(r.sent_count)}</span><span>${pct(r.open_rate)}</span><span>${pct(r.click_rate)}</span>
						<span>${pct(r.reply_rate)}</span><span>${pct(r.bounce_rate)}</span><span>${num(r.member_count)}</span></div>`).join("")
						|| `<div class="cst-empty">${__("No campaigns yet. Make an audience, then start one.")}</div>`}</div>`);
				this.$body.find(".cst-row.click").on("click", (ev) => this.campaign_detail(ev.currentTarget.dataset.name));
				this.paged(this.$body.find(".cst-card:has(.cst-row.head)"));
				this.$body.find(".cst-new-campaign").on("click", () => this.campaign_dialog());
				this.$body.find(".cst-w-resume").on("click", () => this.campaign_dialog());
				if (store.get("cst_use_template", "") && can_manage()) this.campaign_dialog();  // "Use in campaign" from the builder
			});
		}

		campaign_detail(name) {
			this.$body.html(`<div class="cst-empty">${__("Loading…")}</div>`);
			return frappe.xcall(API + "campaign", { name }).then((d) => {
				const en = d.metrics.engagement;
				const c = en.counts;
				const r = en.rates;
				const actions = [];
				if (["Draft", "Paused"].includes(d.status)) actions.push(["submit", __("Submit for approval")]);
				if (d.status === "Pending Approval" && can_manage()) actions.push(["approve", __("Approve and start")]);
				if (d.status === "Active") actions.push(["draft", __("Write drafts now")], ["members", __("Add new people")], ["pause", __("Pause")]);
				actions.push(["check", __("Check content")], ["export", __("Export CSV")], ["form", __("Open the form")]);
				const channel_rows = Object.entries(en.by_channel || {});
				const steps = d.steps.map((s) => {
					const row = (d.metrics.by_step || {})[String(s.step_no)] || { outreach: 0, replies: 0 };
					return `<div class="cst-row"><span><b>${__("Step")} ${s.step_no}</b> <span class="cst-badge">${e(s.channel)}</span>
						<div class="cst-muted">${e(s.subject || "")}</div></span><span>${s.delay_days || 0} ${__("days")}</span>
						<span>${num(row.outreach)} ${__("sent")}</span><span>${num(row.replies)} ${__("replies")}</span></div>`;
				}).join("");
				this.$body.html(`
					<div class="cst-bar"><div><a class="cst-link cst-back">&larr; ${__("All campaigns")}</a>
						<h3 style="margin-top:6px">${e(d.campaign_name)} <span class="cst-badge ${e(d.status)}">${e(__(d.status))}</span></h3></div>
						<div class="cst-actions">${actions.map(([key, label]) => `<button class="btn btn-default btn-sm cst-do" data-do="${key}">${label}</button>`).join("")}</div></div>
					${d.content_status === "Needs review" ? `<div class="cst-note"><b>${__("The content check found issues")}:</b> ${e(d.content_issues)}</div>` : ""}
					<div class="cst-tiles">
						${tile(__("People"), num(d.metrics.members), d.unreached ? `${num(d.unreached)} ${__("cannot be reached")}` : "")}
						${tile(__("Sent"), num(c.sent))}
						${tile(__("Opened"), pct(r.open_rate), `${num(c.opened)} ${__("of")} ${num(c.sent)}`)}
						${tile(__("Clicked"), pct(r.click_rate), `${pct(r.click_to_open_rate)} ${__("of opens")}`)}
						${tile(__("Replied"), pct(r.reply_rate), `${num(c.positive)} ${__("interested")}`)}
						${tile(__("Bounced"), pct(r.bounce_rate))}
						${tile(__("Opted out"), pct(r.unsubscribe_rate))}
						${tile(__("Deals"), num(d.metrics.deals), d.metrics.pipeline_value ? num(d.metrics.pipeline_value) : "")}
					</div>
					${verdict_html(d.verdict, d.step_conversion)}
					<div class="cst-grid"><section class="cst-card"><h3>${__("Funnel")}</h3>${funnel_html(en)}</section>
						<section class="cst-card"><h3>${__("Activity by day")}</h3>${days_html(en.by_day)}</section></div>
					<section class="cst-card"><h3>${__("Copilot suggests")}</h3>${suggestions_html(d.suggestions)}</section>
					${this.ab_card(d, en)}
					<div class="cst-grid">
						<section class="cst-card"><h3>${__("By channel")}</h3>${channel_rows.map(([channel, v]) => `<div class="cst-row">
							<span><b>${e(channel)}</b></span><span>${num(v.sent)} ${__("sent")}</span><span>${pct(v.open_rate)} ${__("opened")}</span>
							<span>${pct(v.click_rate)} ${__("clicked")}</span><span>${pct(v.reply_rate)} ${__("replied")}</span>
							${v.read ? `<span>${pct(v.read_rate)} ${__("read")}</span>` : ""}</div>`).join("") || `<div class="cst-empty">${__("Nothing sent yet.")}</div>`}</section>
						<section class="cst-card"><h3>${__("Steps")}</h3>${steps || `<div class="cst-empty">${__("No steps.")}</div>`}</section>
					</div>
					<div class="cst-grid">
						<section class="cst-card"><h3>${__("Most clicked links")}</h3>${d.top_links.map((l) => `<div class="cst-row">
							<span style="word-break:break-all">${e(l.url)}</span><span>${num(l.clicks)} ${__("clicks")}</span><span>${num(l.people)} ${__("people")}</span></div>`).join("")
							|| `<div class="cst-empty">${__("No clicks yet.")}</div>`}</section>
						<section class="cst-card"><h3>${__("Most engaged people")}</h3>${d.top_recipients.map((p) => `<div class="cst-row click cst-person" data-prospect="${e(p.prospect)}">
							<span><a>${e(p.business_name || p.name)}</a><div class="cst-muted">${e(p.email || p.phone || "")}</div></span>
							<span><span class="cst-badge ${TEMP[p.temperature] || "cold"}">${e(__(p.temperature))}</span></span><span>${p.score}</span></div>`).join("")
							|| `<div class="cst-empty">${__("Nobody has engaged yet.")}</div>`}</section>
					</div>`);
				this.$body.find(".cst-back").on("click", () => this.open("campaigns"));
				this.$body.find(".cst-person").on("click", (ev) => this.timeline_dialog(ev.currentTarget.dataset.prospect));
				this.$body.find(".cst-do").on("click", (ev) => this.campaign_action(ev.currentTarget.dataset.do, d));
			});
		}

		ab_card(d, en) {
			const letters = Object.keys(en.by_variant || {});
			if (!letters.length) return "";
			const subjects = {};
			d.steps.forEach((s) => { if (s.variants && s.variants.length) [s.subject, ...s.variants].forEach((text, i) => { subjects["ABC"[i]] = subjects["ABC"[i]] || text; }); });
			return `<section class="cst-card"><h3>${__("Subject lines · A/B test")}</h3>${letters.map((l) => { const v = en.by_variant[l]; return `<div class="cst-row" style="grid-template-columns:30px 2fr repeat(4, 1fr)">
				<b>${e(l)}</b><span>${e(subjects[l] || "")}</span><span>${num(v.sent)} ${__("sent")}</span><span>${pct(v.open_rate)} ${__("opened")}</span><span>${pct(v.click_rate)} ${__("clicked")}</span><span>${pct(v.reply_rate)} ${__("replied")}</span></div>`; }).join("")}
				<div class="cst-muted">${__("Each person gets one subject line. Keep the better one once every subject has enough sends to compare.")}</div></section>`;
		}

		campaign_action(action, d) {
			const reload = () => this.campaign_detail(d.name);
			const call = (method, args, message) => frappe.xcall(CORE + method, { campaign: d.name, ...(args || {}) })
				.then((r) => { frappe.show_alert({ message: message(r), indicator: "green" }); return reload(); });
			if (action === "form") return frappe.set_route("Form", "Sales Campaign", d.name);
			if (action === "export") {
				return frappe.xcall(API + "export_campaign", { name: d.name }).then((r) => {
					const blob = new Blob(["\ufeff" + r.csv], { type: "text/csv;charset=utf-8" });
					const link = document.createElement("a");
					link.href = URL.createObjectURL(blob); link.download = r.filename; document.body.appendChild(link); link.click(); link.remove();
					setTimeout(() => URL.revokeObjectURL(link.href), 4000);
					frappe.show_alert({ message: __("{0} rows exported", [r.rows]), indicator: "green" });
				});
			}
			if (action === "submit") return call("submit_campaign", null, () => __("Submitted for approval"));
			if (action === "pause") return call("pause_campaign", null, () => __("Paused"));
			if (action === "members") return call("refresh_members", null, (n) => __("{0} people added", [n]));
			if (action === "draft") return call("draft_now", null, (n) => __("{0} drafts written", [n]));
			if (action === "check") {
				return frappe.xcall(CORE + "check_campaign_content", { campaign: d.name }).then((res) => {
					frappe.msgprint({ title: __("Content check"), indicator: res.status === "Passed" ? "green" : "orange",
						message: res.issues && res.issues.length ? res.issues.map((i) => e(i)).join("<br>") : __("No issues found.") });
					return reload();
				});
			}
			if (action === "approve") {
				const go = (ack) => call("approve_campaign", { acknowledge_issues: ack ? 1 : 0 }, (n) => __("Approved: {0} people added", [n]));
				return d.content_status === "Needs review"
					? frappe.confirm(__("The content check found issues. Approve anyway?"), () => go(true))
					: go(false);
			}
		}

		// The campaign wizard: Setup, Audience, Content, Schedule and review ------------------------------

		campaign_dialog() { return this.wizard(); }

		wizard(preset) {
			let saved = {};
			try { saved = JSON.parse(store.get("cst_wizard", "{}")) || {}; } catch (err) { saved = {}; }
			const wanted = store.get("cst_use_template", "");
			store.set("cst_use_template", "");
			return Promise.all([frappe.xcall(API + "audiences"), frappe.xcall(API + "templates")]).then(([audiences, templates]) => {
				this.wz = Object.assign({ step: 1, name: "", goal: "", language: "English", offer: "", audience: "", daily_limit: 50,
					start_date: frappe.datetime.get_today(), pilot: false, pilot_max: 50, holdout: 20, steps: [{ template: "", delay_days: 0 }] }, saved, preset || {});
				if (wanted) this.wz.steps = [{ template: wanted, delay_days: 0 }];
				this.wz.audiences = audiences;
				this.wz.templates = templates;
				this.wz.checks = {};
				this.wz.state = null;
				this.paint_wizard();
			});
		}

		wz_persist() {
			const w = this.wz;
			store.set("cst_wizard", JSON.stringify({ step: w.step, name: w.name, goal: w.goal, language: w.language, offer: w.offer, audience: w.audience,
				daily_limit: w.daily_limit, start_date: w.start_date, pilot: w.pilot, pilot_max: w.pilot_max, holdout: w.holdout, steps: w.steps }));
		}

		wz_template(name) { return this.wz.templates.find((t) => t.name === name); }

		wz_audience() { return this.wz.audiences.find((a) => a.name === this.wz.audience); }

		paint_wizard() {
			const w = this.wz;
			const labels = [__("Setup"), __("Audience"), __("Content"), __("Schedule & review")];
			const stepper = `<ol class="cst-stepper">${labels.map((label, i) => `<li class="${w.step === i + 1 ? "on" : w.step > i + 1 ? "done" : ""}"><span>${w.step > i + 1 ? "✓" : i + 1}</span>${label}</li>`).join("")}</ol>`;
			const body = [null, () => this.wz_setup(), () => this.wz_audience_step(), () => this.wz_content(), () => this.wz_review()][w.step]();
			this.$body.html(`<div class="cst-bar"><div><a class="cst-link cst-w-cancel">&larr; ${__("All campaigns")}</a><h3 style="margin-top:6px">${__("New campaign")}</h3></div>
				<a class="cst-link cst-w-reset">${__("Start over")}</a></div>${stepper}<section class="cst-card">${body}</section>
				<div class="cst-actions" style="justify-content:space-between">
					<button class="btn btn-default cst-w-back" ${w.step === 1 ? "disabled" : ""}>${__("Back")}</button>
					<span class="cst-actions">${w.step === 4 ? `<button class="btn btn-default cst-w-create" data-submit="0">${__("Create draft")}</button>
						<button class="btn btn-primary cst-w-create" data-submit="1">${__("Create and submit for approval")}</button>` : `<button class="btn btn-primary cst-w-next">${__("Next")}</button>`}</span></div>`);
			const $b = this.$body;
			$b.find(".cst-w-cancel").on("click", () => this.open("campaigns"));
			$b.find(".cst-w-reset").on("click", () => { store.set("cst_wizard", "{}"); this.wizard({ step: 1, name: "", goal: "", offer: "", audience: "", steps: [{ template: "", delay_days: 0 }] }); });
			$b.find(".cst-w-back").on("click", () => { w.step -= 1; this.wz_persist(); this.paint_wizard(); });
			$b.find(".cst-w-next").on("click", () => this.wz_next());
			$b.find(".cst-w-create").on("click", (ev) => this.wz_create(ev.currentTarget.dataset.submit === "1"));
			$b.find("[data-w]").on("input change", (ev) => {
				const el = ev.currentTarget;
				w[el.dataset.w] = el.type === "checkbox" ? el.checked : (el.type === "number" ? Number(el.value || 0) : el.value);
				this.wz_persist();
				if (el.type === "checkbox" || el.tagName === "SELECT") this.paint_wizard();
			});
			$b.find(".cst-quick").on("click", (ev) => {
				const q = QUICK.find((x) => x.id === ev.currentTarget.dataset.q);
				w.goal = q.goal;
				w.pilot = q.pilot;
				w.steps = q.delays.map((days, i) => ({ template: (w.steps[i] && w.steps[i].template) || "", delay_days: days }));  // keep templates already chosen
				if (!w.name) w.name = q.title;
				this.wz_persist();
				this.paint_wizard();
			});
			if (w.step === 2) {
				$b.find(".cst-w-aud").on("change", (ev) => { w.audience = ev.currentTarget.value; this.wz_persist(); this.paint_wizard(); });
				$b.find(".cst-w-newaud").on("click", () => this.audience_dialog(null, (saved) => frappe.xcall(API + "audiences").then((list) => {
					w.audiences = list;
					w.audience = saved.name;
					this.wz_persist();
					this.paint_wizard();
				})));
			}
			if (w.step === 3) this.wz_bind_content();
			if (w.step === 4) this.wz_load_state();
		}

		wz_setup() {
			const w = this.wz;
			const picked = QUICK.find((q) => q.goal === w.goal && q.delays.join() === w.steps.map((x) => x.delay_days || 0).join());
			const cards = `<h4 class="cst-wl">${__("What do you want to do?")}</h4><div class="cst-picker">${QUICK.map((q) => `<button type="button" class="cst-quick ${picked && picked.id === q.id ? "on" : ""}" data-q="${q.id}"><b>${q.title}</b><span>${q.text}</span></button>`).join("")}</div>`;
			return `${cards}<h3 style="margin-top:14px">${__("Details")}</h3>
				<div class="cst-wgrid2"><div><label class="cst-wl">${__("Name")}</label><input class="form-control" data-w="name" value="${e(w.name)}" placeholder="${__("For example: Q4 re-engagement")}"></div>
					<div><label class="cst-wl">${__("Goal")}</label><select class="form-control" data-w="goal"><option value=""></option>${["Book a meeting", "Re-engage", "Upsell", "Event invite"].map((g) => `<option ${w.goal === g ? "selected" : ""}>${__(g)}</option>`).join("")}</select></div>
					<div><label class="cst-wl">${__("Language")}</label><select class="form-control" data-w="language">${["English", "Bangla"].map((l) => `<option ${w.language === l ? "selected" : ""}>${l}</option>`).join("")}</select></div>
					<div><label class="cst-wl">${__("Offer or next step")}</label><textarea class="form-control" rows="2" data-w="offer" placeholder="${__("What you are asking people to do")}">${e(w.offer)}</textarea></div></div>`;
		}

		wz_audience_step() {
			const w = this.wz;
			return `<div class="cst-bar"><h3>${__("Who should receive it?")}</h3>${can_manage() ? `<button class="btn btn-default btn-sm cst-w-newaud">${__("New audience")}</button>` : ""}</div>
				${w.audiences.map((a) => `<label class="cst-wcard ${w.audience === a.name ? "on" : ""}"><input type="radio" name="aud" class="cst-w-aud" value="${e(a.name)}" ${w.audience === a.name ? "checked" : ""}>
					<span><b>${e(a.audience_name)}</b> <span class="cst-badge">${e(__(a.audience_type))}</span>${a.sms_opt_in || a.whatsapp_opt_in ? ` <span class="cst-badge ok">${__("Permission recorded")}</span>` : ""}
					<div class="cst-muted">${num(a.size)} ${__("people")} · ${num(a.size_email)} ${__("with email")} · ${num(a.size_phone)} ${__("with phone")}</div></span></label>`).join("")
					|| `<div class="cst-empty">${__("No audiences yet. Make one to continue.")}</div>`}`;
		}

		wz_content() {
			const w = this.wz;
			if (!w.templates.length) {
				return `<div class="cst-empty">${__("No approved templates yet.")}<br><button class="btn btn-primary btn-sm cst-w-tplpage" style="margin-top:8px">${__("Build a template")}</button></div>`;
			}
			const groups = {};
			w.templates.forEach((t) => { (groups[t.channel] = groups[t.channel] || []).push(t); });
			const options = (current) => `<option value="">${__("Choose a template")}</option>${Object.entries(groups).map(([channel, list]) => `<optgroup label="${e(channel)}">${list.map((t) =>
				`<option value="${e(t.name)}" ${t.name === current ? "selected" : ""}>${e(t.template_name)}</option>`).join("")}</optgroup>`).join("")}`;
			const rows = w.steps.map((s, i) => {
				const t = this.wz_template(s.template);
				return `<div class="cst-wstep" data-i="${i}"><div class="cst-bar"><b>${__("Step")} ${i + 1}</b>${t ? `<span class="cst-badge">${e(t.channel)}</span>` : ""}
						<span style="flex:1"></span>${w.steps.length > 1 ? `<button class="btn btn-default btn-xs cst-w-del" data-i="${i}">${__("Remove")}</button>` : ""}</div>
					<div class="cst-wgrid"><select class="form-control cst-w-tpl" data-i="${i}">${options(s.template)}</select>
						<label class="cst-wl" style="margin:0">${i === 0 ? __("Starts") : __("Wait (days after the previous step)")}
							<input type="number" min="0" class="form-control cst-w-delay" data-i="${i}" value="${s.delay_days || 0}" ${i === 0 ? "disabled" : ""}></label></div>
					${t ? `<div class="cst-wprev"><b>${e(t.subject || t.template_name)}</b><div class="cst-muted">${e((t.language || ""))}</div>
						<div class="cst-wchecks" data-i="${i}">${this.wz_checks_html(s.template)}</div>
						<div class="cst-actions"><button class="btn btn-default btn-xs cst-w-edit" data-i="${i}">${__("Open in the builder")}</button></div></div>` : ""}</div>`;
			}).join("");
			return `<h3>${__("What will you send?")}</h3><div class="cst-muted" style="margin-bottom:8px">${__("Each step is an approved template. Build or change templates in the builder, then come back.")}</div>${rows}
				<div class="cst-actions"><button class="btn btn-default btn-sm cst-w-add">${__("Add a step")}</button><button class="btn btn-default btn-sm cst-w-tplpage">${__("Build a new template")}</button></div>${this.wz_reach_html()}`;
		}

		wz_checks_html(name) {
			const c = this.wz.checks[name];
			if (!c) return `<span class="cst-muted">${__("Checking…")}</span>`;
			const open = c.checks.filter((k) => !k.ok);
			return open.length ? `<span class="cst-badge warn">${open.length} ${__("pre-send checks open")}</span>${open.map((k) => `<div class="cst-muted">! ${e(k.label)}</div>`).join("")}`
				: `<span class="cst-badge ok">${__("All pre-send checks pass")}</span>`;
		}

		wz_reach_html() {
			const w = this.wz;
			const aud = this.wz_audience();
			const channels = [...new Set(w.steps.map((s) => (this.wz_template(s.template) || {}).channel).filter(Boolean))];
			if (!aud || !channels.length) return "";
			const line = (c) => c === "Email" ? `${__("Email reaches {0} of {1} people (those with an email).", [num(aud.size_email), num(aud.size)])}`
				: c === "LinkedIn" ? __("LinkedIn steps become tasks for your team.")
				: `${c}: ${__("{0} of {1} have a phone. Only people with recorded permission are messaged.", [num(aud.size_phone), num(aud.size)])}`;
			return `<div class="cst-note" style="margin-top:12px"><b>${__("Who each step can reach")}</b>${channels.map((c) => `<div>${e(line(c))}</div>`).join("")}</div>`;
		}

		wz_bind_content() {
			const w = this.wz;
			const $b = this.$body;
			const load = (name) => {
				if (!name || w.checks[name]) return;
				frappe.xcall("reckon_sales_agent.api_templates.get", { template: name }).then((t) => {
					w.checks[name] = t.result;
					$b.find(".cst-wchecks").each((_, el) => { if (w.steps[Number(el.dataset.i)].template === name) $(el).html(this.wz_checks_html(name)); });
				});
			};
			w.steps.forEach((s) => load(s.template));
			$b.find(".cst-w-tpl").on("change", (ev) => { w.steps[Number(ev.currentTarget.dataset.i)].template = ev.currentTarget.value; this.wz_persist(); this.paint_wizard(); });
			$b.find(".cst-w-delay").on("input", (ev) => { w.steps[Number(ev.currentTarget.dataset.i)].delay_days = Number(ev.currentTarget.value || 0); this.wz_persist(); });
			$b.find(".cst-w-add").on("click", () => { w.steps.push({ template: "", delay_days: 3 }); this.wz_persist(); this.paint_wizard(); });
			$b.find(".cst-w-del").on("click", (ev) => { w.steps.splice(Number(ev.currentTarget.dataset.i), 1); this.wz_persist(); this.paint_wizard(); });
			$b.find(".cst-w-edit").on("click", (ev) => { this.wz_persist(); frappe.set_route("sales-templates", w.steps[Number(ev.currentTarget.dataset.i)].template); });
			$b.find(".cst-w-tplpage").on("click", () => { this.wz_persist(); frappe.set_route("sales-templates"); });
		}

		wz_review() {
			const w = this.wz;
			const aud = this.wz_audience() || {};
			const st = w.state;
			const rows = w.steps.map((s, i) => { const t = this.wz_template(s.template) || {}; return `<div class="cst-row" style="grid-template-columns:70px 1fr 110px 120px"><span><b>${__("Step")} ${i + 1}</b></span>
				<span>${e(t.template_name || "")}</span><span><span class="cst-badge">${e(t.channel || "")}</span></span><span>${i === 0 ? __("At the start") : `+${s.delay_days || 0} ${__("days")}`}</span></div>`; }).join("");
			return `<h3>${__("Schedule and review")}</h3>
				<div class="cst-wgrid2"><div><label class="cst-wl">${__("Start date")}</label><input type="date" class="form-control" data-w="start_date" value="${e(w.start_date)}"></div>
					<div><label class="cst-wl">${__("Most messages per day")}</label><input type="number" min="1" class="form-control" data-w="daily_limit" value="${w.daily_limit}"></div></div>
				<label style="margin-top:10px;display:block"><input type="checkbox" data-w="pilot" ${w.pilot ? "checked" : ""}> ${__("Start with a pilot: only the first people, and hold some back to measure the effect")}</label>
				${w.pilot ? `<div class="cst-wgrid2"><div><label class="cst-wl">${__("Pilot size")}</label><input type="number" min="1" class="form-control" data-w="pilot_max" value="${w.pilot_max}"></div>
					<div><label class="cst-wl">${__("Held back, percent")}</label><input type="number" min="1" max="50" class="form-control" data-w="holdout" value="${w.holdout}"></div></div>` : ""}
				<h4>${__("Summary")}</h4>
				<div class="cst-muted"><b>${e(w.name)}</b>${w.goal ? ` · ${e(__(w.goal))}` : ""} · ${e(w.language)} · ${__("Audience")}: <b>${e(aud.audience_name || "")}</b> (${num(aud.size)} ${__("people")})</div>
				<div class="cst-card" style="margin-top:8px">${rows}</div>
				${st ? `<div class="cst-note">${st.outbound_enabled ? __("Sending is on.") : __("Sending is switched off, so the campaign runs as a test and reaches nobody until you turn it on in Sales Agent Settings.")}
					<br>${__("Autopilot")}: <b>${e(__(st.level))}</b>. ${e(st.descriptions[st.level])}</div>` : ""}
				<div class="cst-note">${__("Creating it does not send anything. A person approves the campaign first; that is the one decision for the whole sequence.")}</div>`;
		}

		wz_load_state() {
			if (this.wz.state) return;
			frappe.xcall(API + "overview").then((d) => { this.wz.state = d.autopilot; if (this.wz.step === 4) this.paint_wizard(); });
		}

		wz_next() {
			const w = this.wz;
			if (w.step === 1 && !(w.name || "").trim()) return frappe.msgprint(__("Give the campaign a name."));
			if (w.step === 2 && !w.audience) return frappe.msgprint(__("Choose who should receive it."));
			if (w.step === 3 && (!w.steps.length || w.steps.some((s) => !s.template))) return frappe.msgprint(__("Choose a template for every step."));
			w.step += 1;
			this.wz_persist();
			this.paint_wizard();
		}

		wz_create(submit) {
			const w = this.wz;
			frappe.xcall(API + "create_campaign", { data: JSON.stringify({ campaign_name: w.name, goal: w.goal, language: w.language, offer: w.offer, audience: w.audience,
				daily_limit: w.daily_limit, start_date: w.start_date, pilot: w.pilot, pilot_max: w.pilot_max, holdout: w.holdout, steps: w.steps, submit }) }).then((name) => {
				store.set("cst_wizard", "{}");
				frappe.show_alert({ message: submit ? __("Created and submitted. A manager approves it before anything is sent.") : __("Draft created. Submit it for approval when you are ready."), indicator: "green" });
				this.open("campaigns").then(() => this.campaign_detail(name));
			});
		}

		// Search, sort and pages (ten at a time) for a list of grid rows, with the header row as the sort header.
		paged($card, search = true) {
			if (window.rsa_tables) window.rsa_tables.enhance($card, { rows: ".cst-row:not(.head)", head: ".cst-row.head > span", search });
		}

		// Audiences --------------------------------------------------------------

		tab_audiences() {
			return frappe.xcall(API + "audiences").then((rows) => {
				this.$body.html(`<div class="cst-bar"><div><h3>${__("Audiences")}</h3>
					<div class="cst-muted">${__("Who a campaign goes to: prospects, CRM leads and contacts, customers, or people you pick.")}</div></div>
					${can_manage() ? `<button class="btn btn-primary btn-sm cst-new-audience">${__("New audience")}</button>` : ""}</div>
					${can_manage() ? `<div class="cst-quickstart"><span class="cst-muted">${__("Start from:")}</span>
						${[["Prospects", __("Lead Finder leads")], ["CRM Leads", __("CRM leads")], ["Customers", __("Customers")], ["CRM Contacts", __("CRM contacts")]]
							.map(([k, l]) => `<button class="btn btn-default btn-xs cst-qa" data-kind="${k}">${e(l)}</button>`).join("")}</div>` : ""}
					<div class="cst-aud-list">${rows.map((a) => `<section class="cst-card" data-name="${e(a.name)}"><div class="cst-bar">
						<div><b>${e(a.audience_name)}</b> <span class="cst-badge">${e(__(a.audience_type))}</span>
							${a.sms_opt_in || a.whatsapp_opt_in ? `<span class="cst-badge ok">${__("Permission recorded")}</span>` : ""}
							<div class="cst-muted">${num(a.size)} ${__("people")} · ${num(a.size_email)} ${__("with email")} · ${num(a.size_phone)} ${__("with phone")}
								· ${a.campaigns} ${__("campaigns")}${a.last_refreshed ? ` · ${__("counted")} ${frappe.datetime.prettyDate(a.last_refreshed)}` : ""}</div></div>
						<div class="cst-actions">${can_manage() ? `<button class="btn btn-primary btn-xs cst-a-run">${__("Start a campaign")}</button>
							<button class="btn btn-default btn-xs cst-a-edit">${__("Edit")}</button>
							<button class="btn btn-default btn-xs cst-a-count">${__("Count again")}</button>
							<button class="btn btn-default btn-xs cst-a-del">${__("Delete")}</button>` : ""}</div></div></section>`).join("")
						|| `<div class="cst-card cst-empty">${__("No audiences yet.")}</div>`}</div>`);
				if (window.rsa_tables) window.rsa_tables.enhance(this.$body.find(".cst-aud-list"), { rows: "> .cst-card[data-name]", sort: false });
				this.$body.find(".cst-new-audience").on("click", () => this.audience_dialog());
				this.$body.find(".cst-qa").on("click", (ev) => this.audience_dialog(null, null, { kind: ev.currentTarget.dataset.kind }));
				const name = (ev) => $(ev.currentTarget).closest("[data-name]").data("name");
				this.$body.find(".cst-a-run").on("click", (ev) => this.wizard({ step: 1, audience: name(ev) }));
				this.$body.find(".cst-a-edit").on("click", (ev) => this.audience_dialog(name(ev)));
				this.$body.find(".cst-a-count").on("click", (ev) => frappe.xcall(API + "refresh_audience", { name: name(ev) }).then(() => this.open("audiences")));
				this.$body.find(".cst-a-del").on("click", (ev) => frappe.confirm(__("Delete this audience?"), () =>
					frappe.xcall(API + "delete_audience", { name: name(ev) }).then(() => this.open("audiences"))));
			});
		}

		// Who a campaign goes to, built by choosing: where the people are, filters from your own data, a live count, and
		// either "everyone who matches" or "I will pick".
		audience_dialog(existing, after, preset) {
			const load = existing ? frappe.xcall(API + "audience", { name: existing }) : Promise.resolve({});
			Promise.all([load, frappe.xcall(API + "audience_options")]).then(([a, opts]) => {
				const KINDS = [
					["Prospects", __("Lead Finder leads"), __("Businesses the Lead Finder found and you approved.")],
					["CRM Leads", __("CRM leads"), __("Leads in your CRM, by status, source or owner.")],
					["CRM Contacts", __("CRM contacts"), __("Everyone in your CRM contacts.")],
					["Customers", __("Customers"), __("People behind a deal you won.")],
					["Segment", __("Saved segment"), __("A rule set made in Capture Studio.")],
				];
				const keyOf = (m) => (m.reference_doctype && m.reference_name ? `${m.reference_doctype}:${m.reference_name}` : `x:${m.email || m.phone || m.person_name}`);
				const st = {
					name: a.audience_name || "", description: a.description || "", kind: "Prospects", mode: "rule",
					picked: new Map(), q: "", page: 1, size: 10, total: 0, rows: [], summary: null, seq: 0,
					f: { status_filter: a.status_filter || "", source_filter: a.source_filter || "", owner_filter: a.owner_filter || "",
						city_filter: a.city_filter || "", industry_filter: a.industry_filter || "", minimum_fit_score: a.minimum_fit_score || "",
						require_email: !!a.require_email, require_phone: !!a.require_phone },
					segment: a.segment || "", sms: !!a.sms_opt_in, wa: !!a.whatsapp_opt_in, src: a.opt_in_source || "",
				};
				if (a.audience_type === "Specific people") {
					st.mode = "pick";
					(a.members || []).forEach((m) => st.picked.set(keyOf(m), m));
				} else if (a.audience_type) {
					st.kind = a.audience_type;
				}
				if (preset && preset.kind) st.kind = preset.kind;
				const memberOf = (r) => ({ reference_doctype: r.ref_doctype, reference_name: r.ref_name, person_name: r.name, email: r.email, phone: r.phone });
				const rowKey = (r) => keyOf(memberOf(r));
				const config = () => ({
					name: existing || undefined, audience_name: st.name, description: st.description,
					audience_type: st.mode === "pick" ? "Specific people" : st.kind,
					status_filter: st.f.status_filter, source_filter: st.f.source_filter, owner_filter: st.f.owner_filter,
					city_filter: st.f.city_filter, industry_filter: st.f.industry_filter, minimum_fit_score: st.f.minimum_fit_score || 0,
					require_email: st.f.require_email ? 1 : 0, require_phone: st.f.require_phone ? 1 : 0,
					segment: st.kind === "Segment" ? st.segment : "", sms_opt_in: st.sms ? 1 : 0, whatsapp_opt_in: st.wa ? 1 : 0, opt_in_source: st.src,
					members: st.mode === "pick" ? [...st.picked.values()] : [],
				});
				// What the filters would find (the kind being looked at, whatever the audience is saved as).
				const browse = () => ({ ...config(), audience_type: st.kind, members: [] });
				const select = (label, key, values, any) => `<div class="cst-field"><label>${e(label)}</label>
					<select class="form-control input-sm aud-f" data-key="${key}"><option value="">${e(any || __("Any"))}</option>
					${values.map((v) => `<option value="${e(v)}" ${String(st.f[key]) === String(v) ? "selected" : ""}>${e(v)}</option>`).join("")}</select></div>`;

				const dialog = new frappe.ui.Dialog({
					title: existing ? __("Edit audience") : __("New audience"), size: "extra-large",
					fields: [{ fieldname: "body", fieldtype: "HTML" }],
					primary_action_label: __("Save audience"),
					primary_action: () => {
						if (!st.name.trim()) return frappe.msgprint(__("Give the audience a name."));
						if (st.kind === "Segment" && st.mode !== "pick" && !st.segment) return frappe.msgprint(__("Choose a saved segment."));
						if (st.mode === "pick" && !st.picked.size) return frappe.msgprint(__("Tick at least one person, or switch to \"Everyone who matches\"."));
						if ((st.sms || st.wa) && !st.src.trim()) return frappe.msgprint(__("Say how these people agreed to be messaged."));
						frappe.xcall(API + "save_audience", { config: JSON.stringify(config()) }).then((saved) => {
							dialog.hide();
							if (after) after(saved);
							else this.open("audiences");
						});
					},
				});
				const $w = dialog.fields_dict.body.$wrapper;
				$w.html(`<div class="cst-aud">
					<div class="cst-field"><label>${__("Name")} <span class="text-danger">*</span></label>
						<input class="form-control aud-name" value="${e(st.name)}" placeholder="${__("e.g. Dhaka pharmacies, new this month")}"></div>
					<div class="cst-field"><label>${__("Who do you want to reach?")}</label><div class="aud-kinds"></div></div>
					<div class="aud-filters"></div>
					<div class="aud-modes"></div>
					<div class="aud-result">
						<div class="aud-sum"></div>
						<div class="aud-tools"><input type="search" class="form-control input-sm aud-q" placeholder="${__("Search by name, email or phone")}">
							<span class="aud-pickbar"></span></div>
						<div class="aud-rows"></div>
						<div class="cst-pager"><span class="cst-muted aud-info"></span><span class="aud-pages"></span></div>
					</div>
					<div class="cst-field"><label>${__("Note (optional)")}</label><input class="form-control aud-desc" value="${e(st.description)}"></div>
					<details class="aud-consent" ${st.sms || st.wa ? "open" : ""}><summary>${__("Permission for SMS and WhatsApp")}</summary>
						<div class="cst-muted">${__("Tick only if these people agreed to be texted or messaged on WhatsApp. Without it, SMS and WhatsApp steps skip them.")}</div>
						<label class="aud-check"><input type="checkbox" class="aud-sms" ${st.sms ? "checked" : ""}> ${__("They agreed to receive SMS")}</label>
						<label class="aud-check"><input type="checkbox" class="aud-wa" ${st.wa ? "checked" : ""}> ${__("They agreed to receive WhatsApp messages")}</label>
						<input class="form-control input-sm aud-src" value="${e(st.src)}" placeholder="${__("How they agreed (e.g. signup form, written consent)")}">
					</details></div>`);

				const paintKinds = () => {
					$w.find(".aud-kinds").html(KINDS.map(([k, l, d]) => `<button type="button" class="cst-quick ${st.kind === k ? "on" : ""}" data-kind="${k}"><b>${e(l)}</b><span>${e(d)}</span></button>`).join(""));
				};
				const paintFilters = () => {
					const f = st.f;
					const html = {
						"Prospects": () => `<div class="aud-grid">${select(__("Where it was found"), "source_filter", opts.prospect_sources)}
							${select(__("City"), "city_filter", opts.cities)}${select(__("Industry"), "industry_filter", opts.industries)}
							<div class="cst-field"><label>${__("Minimum fit score")}</label><input type="number" min="0" max="100" class="form-control input-sm aud-f" data-key="minimum_fit_score" value="${e(f.minimum_fit_score)}" placeholder="0"></div></div>`,
						"CRM Leads": () => `<div class="cst-field"><label>${__("Lead status (choose any)")}</label><div class="aud-chips">
							${(opts.lead_statuses.length ? opts.lead_statuses : []).map((v) => `<label class="aud-chip ${f.status_filter.split(",").map((x) => x.trim()).includes(v) ? "on" : ""}"><input type="checkbox" class="aud-status" value="${e(v)}" ${f.status_filter.split(",").map((x) => x.trim()).includes(v) ? "checked" : ""}> ${e(v)}</label>`).join("") || `<span class="cst-muted">${__("No statuses set up yet.")}</span>`}</div></div>
							<div class="aud-grid">${select(__("Source"), "source_filter", opts.lead_sources)}${select(__("Owner"), "owner_filter", opts.lead_owners)}</div>`,
						"Segment": () => `<div class="aud-grid">${`<div class="cst-field"><label>${__("Saved segment")}</label><select class="form-control input-sm aud-segment"><option value="">${__("Choose")}</option>
							${opts.segments.map((g) => `<option value="${e(g.name)}" ${st.segment === g.name ? "selected" : ""}>${e(g.label)}</option>`).join("")}</select>
							<div class="cst-muted">${__("Made in Capture Studio. Its rules are checked each time the audience is used.")}</div></div>`}</div>`,
					}[st.kind];
					$w.find(".aud-filters").html(`${html ? html() : ""}<div class="aud-checks">
						<label class="aud-check"><input type="checkbox" class="aud-req" data-key="require_email" ${f.require_email ? "checked" : ""}> ${__("Only people with an email")}</label>
						<label class="aud-check"><input type="checkbox" class="aud-req" data-key="require_phone" ${f.require_phone ? "checked" : ""}> ${__("Only people with a phone")}</label></div>`);
				};
				const paintModes = () => {
					$w.find(".aud-modes").html(`<div class="cst-seg">${[["rule", __("Everyone who matches"), __("Stays up to date as your records change.")], ["pick", __("I will choose people"), __("Tick the people you want from the list below.")]]
						.map(([m, l, d]) => `<button type="button" class="cst-quick ${st.mode === m ? "on" : ""}" data-mode="${m}"><b>${e(l)}</b><span>${e(d)}</span></button>`).join("")}</div>`);
				};
				const paintRows = () => {
					const s = st.summary || { total: 0, with_email: 0, with_phone: 0 };
					const pick = st.mode === "pick";
					$w.find(".aud-sum").html(`<b>${num(st.total)}</b> ${__("people match")} · ${num(s.with_email)} ${__("with email")} · ${num(s.with_phone)} ${__("with phone")}${pick ? ` · <b>${num(st.picked.size)}</b> ${__("chosen")}` : ""}`);
					$w.find(".aud-pickbar").html(pick ? `<button type="button" class="btn btn-default btn-xs aud-all">${__("Choose all {0} matching", [num(st.total)])}</button>
						<button type="button" class="btn btn-default btn-xs aud-none">${__("Clear")}</button>` : "");
					$w.find(".aud-rows").html(st.rows.length ? `<table class="aud-table"><thead><tr>${pick ? `<th><input type="checkbox" class="aud-page" aria-label="${__("Choose this page")}"></th>` : ""}<th>${__("Name")}</th><th>${__("Email")}</th><th>${__("Phone")}</th></tr></thead><tbody>
						${st.rows.map((r) => `<tr>${pick ? `<td><input type="checkbox" class="aud-pick" data-key="${e(rowKey(r))}" ${st.picked.has(rowKey(r)) ? "checked" : ""}></td>` : ""}
							<td>${e(r.name || "-")}</td><td>${e(r.email || "")}</td><td>${e(r.phone || "")}</td></tr>`).join("")}</tbody></table>`
						: `<div class="cst-empty">${st.kind === "Segment" && !st.segment ? __("Choose a saved segment to see who is in it.") : __("No one matches yet. Loosen a filter.")}</div>`);
					const pages = Math.max(1, Math.ceil(st.total / st.size));
					$w.find(".aud-info").text(st.total ? __("{0}–{1} of {2}", [(st.page - 1) * st.size + 1, Math.min(st.page * st.size, st.total), num(st.total)]) : "");
					const near = [...new Set([1, pages, st.page - 1, st.page, st.page + 1])].filter((n) => n >= 1 && n <= pages).sort((x, y) => x - y);
					let last = 0;
					const btn = (label, to, cls, off) => `<button type="button" class="btn btn-xs btn-default aud-pg ${cls || ""}" data-page="${to}" ${off ? "disabled" : ""}>${label}</button>`;
					$w.find(".aud-pages").html(pages <= 1 ? "" : btn("‹", st.page - 1, "", st.page === 1)
						+ near.map((n) => { const gap = n - last > 1 ? '<span class="cst-muted">…</span>' : ""; last = n; return gap + btn(n, n, n === st.page ? "btn-primary" : ""); }).join("")
						+ btn("›", st.page + 1, "", st.page === pages));
					$w.find(".aud-page").prop("checked", st.rows.length > 0 && st.rows.every((r) => st.picked.has(rowKey(r))));
				};
				const fetchRows = frappe.utils.debounce(() => {
					const mine = ++st.seq;
					if (st.kind === "Segment" && !st.segment) { st.rows = []; st.total = 0; st.summary = null; return paintRows(); }
					frappe.xcall(API + "audience_people", { config: JSON.stringify(browse()), search: st.q, page: st.page, page_length: st.size }).then((r) => {
						if (mine !== st.seq) return;
						st.rows = r.rows; st.total = r.total; st.summary = r.summary;
						paintRows();
					});
				}, 250);
				const changed = () => { st.page = 1; fetchRows(); };

				$w.on("input", ".aud-name", (ev) => { st.name = ev.currentTarget.value; });
				$w.on("input", ".aud-desc", (ev) => { st.description = ev.currentTarget.value; });
				$w.on("input", ".aud-src", (ev) => { st.src = ev.currentTarget.value; });
				$w.on("change", ".aud-sms", (ev) => { st.sms = ev.currentTarget.checked; });
				$w.on("change", ".aud-wa", (ev) => { st.wa = ev.currentTarget.checked; });
				$w.on("input", ".aud-q", (ev) => { st.q = ev.currentTarget.value; changed(); });
				$w.on("click", ".aud-kinds .cst-quick", (ev) => {
					st.kind = ev.currentTarget.dataset.kind;
					Object.assign(st.f, { status_filter: "", source_filter: "", owner_filter: "", city_filter: "", industry_filter: "", minimum_fit_score: "" });
					paintKinds(); paintFilters(); changed();
				});
				$w.on("click", ".aud-modes .cst-quick", (ev) => { st.mode = ev.currentTarget.dataset.mode; paintModes(); paintRows(); });
				$w.on("change", ".aud-f", (ev) => { st.f[ev.currentTarget.dataset.key] = ev.currentTarget.value; changed(); });
				$w.on("input", "input.aud-f", (ev) => { st.f[ev.currentTarget.dataset.key] = ev.currentTarget.value; changed(); });
				$w.on("change", ".aud-req", (ev) => { st.f[ev.currentTarget.dataset.key] = ev.currentTarget.checked; changed(); });
				$w.on("change", ".aud-segment", (ev) => { st.segment = ev.currentTarget.value; changed(); });
				$w.on("change", ".aud-status", () => {
					st.f.status_filter = $w.find(".aud-status:checked").map((_, x) => x.value).get().join(", ");
					$w.find(".aud-chip").each((_, c) => $(c).toggleClass("on", $(c).find("input").prop("checked")));
					changed();
				});
				$w.on("click", ".aud-pg:not([disabled])", (ev) => { st.page = Number(ev.currentTarget.dataset.page); fetchRows(); });
				$w.on("change", ".aud-pick", (ev) => {
					const row = st.rows.find((r) => rowKey(r) === ev.currentTarget.dataset.key);
					if (row) { if (ev.currentTarget.checked) st.picked.set(rowKey(row), memberOf(row)); else st.picked.delete(rowKey(row)); }
					paintRows();
				});
				$w.on("change", ".aud-page", (ev) => {
					st.rows.forEach((r) => { if (ev.currentTarget.checked) st.picked.set(rowKey(r), memberOf(r)); else st.picked.delete(rowKey(r)); });
					paintRows();
				});
				$w.on("click", ".aud-all", () => frappe.xcall(API + "audience_people", { config: JSON.stringify(browse()), search: st.q, page: 1, page_length: 5000 })
					.then((r) => { r.rows.forEach((x) => st.picked.set(rowKey(x), memberOf(x))); paintRows(); }));
				$w.on("click", ".aud-none", () => { st.picked.clear(); paintRows(); });

				paintKinds(); paintFilters(); paintModes();
				dialog.show();
				fetchRows();
			});
		}

		// Recipients -------------------------------------------------------------

		tab_recipients() {
			this.$body.html(`<div class="cst-bar"><div><h3>${__("Recipients")}</h3>
				<div class="cst-muted">${__("Everything a person has been sent and what they did with it, across all campaigns.")}</div></div></div>
				<input class="form-control cst-search" placeholder="${__("Search by name, email or phone")}">
				<div class="cst-card cst-people"></div>`);
			const list = this.$body.find(".cst-people");
			const run = () => frappe.xcall(API + "recipients", { search: this.$body.find(".cst-search").val() }).then((rows) => {
				list.html(`<div class="cst-row head"><span>${__("Person")}</span><span>${__("Warmth")}</span><span>${__("Score")}</span>
					<span>${__("Opened")}</span><span>${__("Clicked")}</span><span>${__("Replied")}</span><span>${__("Campaigns")}</span></div>
					${rows.map((p) => `<div class="cst-row click cst-person" data-prospect="${e(p.name)}">
						<span><a>${e(p.business_name)}</a><div class="cst-muted">${e(p.email || p.phone || "")}</div></span>
						<span><span class="cst-badge ${TEMP[p.temperature] || "cold"}">${e(__(p.temperature))}</span></span><span>${p.score}</span>
						<span>${p.counts.opened}</span><span>${p.counts.clicked}</span><span>${p.counts.replied}</span><span>${p.campaigns}</span></div>`).join("")
						|| `<div class="cst-empty">${__("Nobody found.")}</div>`}`);
				list.find(".cst-person").on("click", (ev) => this.timeline_dialog(ev.currentTarget.dataset.prospect));
				this.paged(list, false);
			});
			let timer = null;
			this.$body.find(".cst-search").on("input", () => { clearTimeout(timer); timer = setTimeout(run, 350); });
			return run();
		}

		timeline_dialog(prospect) {
			frappe.xcall(API + "recipient_timeline", { prospect }).then((t) => {
				const dialog = new frappe.ui.Dialog({ title: t.business_name || prospect, size: "large", fields: [{ fieldname: "body", fieldtype: "HTML" }] });
				dialog.fields_dict.body.$wrapper.html(`<div class="cst">
					<div class="cst-actions"><span class="cst-badge ${TEMP[t.temperature] || "cold"}">${e(__(t.temperature))}</span>
						<span class="cst-badge">${__("Score")} ${t.score}</span>
						<span class="cst-muted">${e(t.email || "")} ${e(t.phone || "")}</span></div>
					<div class="cst-muted" style="margin:6px 0">${num(t.counts.sent)} ${__("sent")} · ${num(t.counts.opened)} ${__("opened")} · ${num(t.counts.clicked)} ${__("clicked")}
						· ${num(t.counts.replied)} ${__("replied")} · ${t.campaigns.length} ${__("campaigns")}</div>
					<div class="cst-timeline">${t.timeline.slice().reverse().map((ev) => `<div class="cst-event"><span class="cst-muted">${e(ev.at.slice(0, 16))}</span>
						<span><b>${e(ev.label)}</b> <span class="cst-badge">${e(ev.channel)}</span> ${ev.campaign ? `<span class="cst-muted">${e(ev.campaign)}</span>` : ""}
						${ev.subject ? `<div class="cst-muted">${e(ev.subject)}</div>` : ""}${ev.detail ? `<div class="cst-muted">${e(ev.detail)}</div>` : ""}</span></div>`).join("")
						|| `<div class="cst-empty">${__("Nothing yet.")}</div>`}</div></div>`);
				dialog.set_primary_action(__("Open prospect"), () => frappe.set_route("Form", "Sales Prospect", prospect));
				dialog.show();
			});
		}

		// Copilot and autopilot --------------------------------------------------

		tab_autopilot() {
			return Promise.all([frappe.xcall(API + "overview"), frappe.xcall(API + "copilot_suggestions")]).then(([d, suggestions]) => {
				const a = d.autopilot;
				const manage = can_manage();
				this.$body.html(`
					<section class="cst-card"><h3>${__("Autopilot")}</h3>
						<div class="cst-muted">${__("How much the agent may do on its own. It never overrides consent, opt-outs, the daily limits, the sending switch or the kill switch, and a campaign that changed after approval needs a person again.")}</div>
						<div class="cst-levels">${a.levels.map((level) => `<div class="cst-level ${level === a.level ? "on" : ""}" data-level="${e(level)}">
							<b>${e(__(level))}</b><span class="cst-muted">${e(a.descriptions[level])}</span></div>`).join("")}</div>
						${manage ? "" : `<div class="cst-muted">${__("Only a Sales Agent manager can change this.")}</div>`}
						<h4>${__("Sending window")}</h4>
						<div class="cst-actions"><input class="form-control cst-window" style="max-width:180px" placeholder="09:00-20:00" value="${e(a.window)}" ${manage ? "" : "disabled"}>
							${manage ? `<button class="btn btn-default btn-sm cst-window-save">${__("Save")}</button>` : ""}</div>
						<div class="cst-muted">${__("Campaign messages wait outside this window (server time). Leave it empty to send at any time.")}</div>
						<h4>${__("Tracking")}</h4>
						<label><input type="checkbox" class="cst-track" data-k="track_opens" ${a.track_opens ? "checked" : ""} ${manage ? "" : "disabled"}> ${__("Track email opens")}</label><br>
						<label><input type="checkbox" class="cst-track" data-k="track_clicks" ${a.track_clicks ? "checked" : ""} ${manage ? "" : "disabled"}> ${__("Track link clicks (email, SMS, WhatsApp)")}</label>
					</section>
					<section class="cst-card"><h3>${__("Copilot suggests")}</h3>${suggestions_html(suggestions)}</section>`);
				const save = (args) => frappe.xcall(API + "set_autopilot", args).then(() => this.open("autopilot"));
				if (!manage) return;
				this.$body.find(".cst-level").on("click", (ev) => {
					const level = ev.currentTarget.dataset.level;
					if (level === "Auto-send") {
						frappe.confirm(__("Auto-send lets an approved campaign's messages go out without a second click, inside the sending window and daily limits. Switch it on?"), () => save({ level }));
					} else save({ level });
				});
				this.$body.find(".cst-window-save").on("click", () => save({ window: this.$body.find(".cst-window").val() }));
				this.$body.find(".cst-track").on("change", (ev) => save({ [ev.currentTarget.dataset.k]: ev.currentTarget.checked ? 1 : 0 }));
			});
		}
	}
})();
