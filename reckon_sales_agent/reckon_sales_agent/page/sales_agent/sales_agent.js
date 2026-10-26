// Agent Studio: the AI sales team works here; a person only decides.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-agent"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Agent Studio"), single_column: true });
		page.add_inner_button(__("Lead Finder (advanced)"), () => frappe.set_route("lead-finder"));
		page.add_inner_button(__("Prospect Review"), () => frappe.set_route("sales-review"));
		page.add_inner_button(__("Analytics"), () => frappe.set_route("sales-analytics"));
		page.add_inner_button(__("Open CRM"), () => (window.location.href = "/crm"));
		wrapper.studio = new AgentStudio(page);
	};
	frappe.pages["sales-agent"].on_page_show = (wrapper) => wrapper.studio && wrapper.studio.start();
	frappe.pages["sales-agent"].on_page_hide = (wrapper) => wrapper.studio && wrapper.studio.stop();

	const API = "reckon_sales_agent.api_agent_studio.";
	const POLL_MS = 8000;
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const ICONS = {
		Research: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
		Content: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
		Governance: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
		Engagement: '<path d="M4 5h16v11H8l-4 4z"/><path d="M8 9h8M8 12h5"/>',
		Analytics: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
		spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
	};
	const icon = (name, size = 18) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.spark}</svg>`;
	const STATUS = { working: __("Working"), needs_you: __("Needs you"), idle: __("Idle") };
	const ACTIONS = {
		autopilot_run: __("Autopilot run"), autopilot_on: __("Autopilot switched on"), autopilot_off: __("Autopilot switched off"),
		market_onboarding_started: __("Started reading your website"), market_profile_filled: __("Filled in your business profile"),
		market_profile_failed: __("Could not read your website"), market_research_started: __("Started market research"),
		market_brief_ready: __("Market brief ready"), market_brief_approved: __("Segments chosen"),
		discovery_queued: __("Lead search queued"), discovery_completed: __("Lead search finished"),
		research_done: __("Researched a lead's website"), research_partial: __("Researched a lead's website"),
		qualified: __("Scored a lead"), prospect_auto_approved: __("Approved a strong lead"), prospect_approved: __("Lead approved"),
		prospect_rejected: __("Lead rejected"), crm_synced: __("Added a lead to the CRM"), website_found: __("Found a lead's website"),
		content_sequence_written: __("Wrote a campaign"), campaign_submitted: __("Campaign ready for approval"),
		campaign_approved: __("Campaign approved"), campaign_paused: __("Campaign paused"), message_approved: __("Message approved"),
		reply_question: __("Classified a reply: question"), reply_interested: __("Classified a reply: interested"),
		reply_escalated: __("Handed a question to a person"), reply_answer_drafted: __("Drafted an answer"),
		reply_answered: __("Answered a question"), reply_complaint: __("Complaint: needs a person"), pilot_measured: __("Measured a pilot"),
	};
	const label = (a) => ACTIONS[a] || (a || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
	const plain = (html) => $("<div>").html(html || "").text();

	class AgentStudio {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="ags"></div>').appendTo(page.main);
			this.inboxKey = null;
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		start() {
			this.stop();
			this.refresh();
		}

		stop() {
			clearTimeout(this.timer);
			this.timer = null;
		}

		refresh() {
			return this.call("state").then((s) => {
				this.data = s;
				this.render();
			}).finally(() => {
				clearTimeout(this.timer);
				this.timer = setTimeout(() => this.refresh(), POLL_MS);
			});
		}

		// ---------------------------------------------------------------- layout
		render() {
			const s = this.data;
			if (!this.$root.children().length) {
				this.$root.html(`<div class="ags-hero"></div><div class="ags-setup"></div><div class="ags-lanes"></div>
					<div class="ags-funnel"></div>
					<div class="ags-cols"><section><h4>${__("Needs you")}</h4><div class="ags-inbox"></div></section>
						<section><h4>${__("Live activity")}</h4><div class="ags-feed"></div></section></div>`);
			}
			this.render_hero(s);
			this.render_setup(s);
			this.render_lanes(s);
			this.render_funnel(s);
			this.render_feed(s);
			// Re-draw the inbox only when its content changed, so ticks and typing survive the poll.
			const key = JSON.stringify(s.asks.map((a) => [a.key, a.ref, a.detail, (a.messages || []).length, (a.prospects || []).length]));
			if (key !== this.inboxKey) {
				this.inboxKey = key;
				this.render_inbox(s);
			}
		}

		render_hero(s) {
			const ap = s.autopilot;
			const pill = (cls, text) => `<span class="ags-pill ${cls}"><span class="dot"></span>${e(text)}</span>`;
			this.$root.find(".ags-hero").html(`
				<div><h2>${__("Your AI sales team")}</h2>
					<p>${__("Five agents find, research, write and follow up. You only approve what goes out.")}</p></div>
				<div class="ags-pills">
					${pill(ap.enabled ? "ok" : "", ap.enabled ? __("Autopilot on") : __("Autopilot off"))}
					${pill(s.ai ? "ok" : "warn", s.ai ? __("AI on") : __("AI off"))}
					${s.kill_switch ? pill("bad", __("Kill switch on")) : pill(s.outbound_enabled ? "ok" : "warn",
						s.outbound_enabled ? __("Sending live") : __("Dry run: nothing is sent"))}
					${ap.last_run ? pill("", __("Last run {0}", [frappe.datetime.prettyDate(ap.last_run)])) : ""}
					${s.can_manage ? `<button class="btn btn-primary btn-sm ags-run">${icon("spark", 14)} ${__("Run agents now")}</button>` : ""}
				</div>`);
			this.$root.find(".ags-run").on("click", (ev) => {
				$(ev.currentTarget).prop("disabled", true);
				this.call("run_now").then(() => frappe.show_alert({ message: __("The agents are on it."), indicator: "green" }))
					.finally(() => setTimeout(() => this.refresh(), 2500));
			});
		}

		// Onboarding (one line) and the autopilot switch.
		render_setup(s) {
			const el = this.$root.find(".ags-setup");
			const onboard = s.asks.find((a) => a.key === "onboard");
			const ap = s.autopilot;
			const sig = JSON.stringify([!!onboard, ap.enabled, s.can_manage]);
			if (sig === this.setupKey) return;
			this.setupKey = sig;
			let html = "";
			if (onboard) {
				html += `<div class="ags-card ags-onboard"><div class="ags-onboard-icon">${icon("spark", 22)}</div><div class="grow">
					<h3>${__("Start with your website")}</h3>
					<p>${__("The Research agent reads your site, fills in your business profile and researches your market. No forms.")}</p>
					<div class="ags-row"><input class="form-control ags-web" placeholder="${__("yourcompany.com")}">
						<input class="form-control ags-note" placeholder="${__("Optional: what you sell, in one sentence")}">
						<button class="btn btn-primary ags-go" ${s.can_manage ? "" : "disabled"}>${__("Start")}</button></div>
					${s.can_manage ? "" : `<div class="ags-muted">${__("Ask a Sales Agent admin or manager to start.")}</div>`}</div></div>`;
			}
			if (s.can_manage && !ap.enabled) {
				html += `<div class="ags-card ags-autopilot"><div class="grow"><h3>${__("Let the agents run on their own")}</h3>
					<p>${__("With autopilot on, the agents research your market, choose the best segments, find leads every week, approve leads that meet your thresholds and write pilot campaigns. Launching a campaign and sending any message always wait for you.")}</p>
					<label class="ags-check"><input type="checkbox" class="ags-consent"> ${__("I agree the agents may use our enabled lead sources and create leads, CRM records and draft campaigns on their own.")}</label></div>
					<button class="btn btn-primary ags-on">${__("Turn on autopilot")}</button></div>`;
			} else if (s.can_manage && ap.enabled) {
				html += `<details class="ags-card ags-tune"><summary>${__("Autopilot settings")}</summary><div class="ags-row">
					<label>${__("Leads per week")} <input type="number" class="form-control ags-weekly" min="5" max="1000" value="${e(ap.weekly_leads)}"></label>
					<label>${__("Approved leads before a campaign")} <input type="number" class="form-control ags-min" min="1" max="200" value="${e(ap.min_prospects)}"></label>
					<label>${__("Auto-approve leads at fit score")} <input type="number" class="form-control ags-fit" min="0" max="100" value="${e(ap.auto_approve_min_fit)}"></label>
					<label class="ags-check"><input type="checkbox" class="ags-segs" ${ap.auto_segments ? "checked" : ""}> ${__("Choose segments automatically")}</label>
					<button class="btn btn-default btn-sm ags-save">${__("Save")}</button>
					<button class="btn btn-default btn-sm ags-off">${__("Turn autopilot off")}</button></div>
					<div class="ags-muted">${__("Qualified leads at or above this score are approved and added to the CRM without you. Leads that score below your review threshold are set aside; approve one in Prospect Review to bring it back.")}</div></details>`;
			}
			el.html(html);
			el.find(".ags-go").on("click", (ev) => {
				const website = el.find(".ags-web").val().trim();
				const note = el.find(".ags-note").val().trim();
				if (!website && !note) return frappe.msgprint(__("Type your website, or a sentence about what you sell."));
				$(ev.currentTarget).prop("disabled", true);
				this.call("onboard", { website, note }).then(() => {
					frappe.show_alert({ message: __("Reading your website…"), indicator: "blue" });
					this.setupKey = null;
					this.refresh();
				}).catch(() => $(ev.currentTarget).prop("disabled", false));
			});
			el.find(".ags-on").on("click", () => {
				if (!el.find(".ags-consent").is(":checked")) return frappe.msgprint(__("Tick the box to confirm first."));
				this.set_autopilot({ enabled: 1, consent: 1 });
			});
			el.find(".ags-off").on("click", () => this.set_autopilot({ enabled: 0 }));
			el.find(".ags-save").on("click", () => this.set_autopilot({
				enabled: 1, weekly_leads: Number(el.find(".ags-weekly").val()), min_prospects: Number(el.find(".ags-min").val()),
				auto_segments: el.find(".ags-segs").is(":checked") ? 1 : 0, min_fit: Number(el.find(".ags-fit").val()),
			}));
		}

		set_autopilot(data) {
			return this.call("set_autopilot", { data: JSON.stringify(data) }).then((r) => {
				frappe.show_alert({ message: r.enabled ? __("Autopilot is on") : __("Autopilot is off"), indicator: r.enabled ? "green" : "orange" });
				this.setupKey = null;
				this.refresh();
			});
		}

		render_lanes(s) {
			this.$root.find(".ags-lanes").html(s.lanes.map((l) => `
				<div class="ags-lane ${e(l.status)}">
					<div class="ags-lane-head"><span class="ags-lane-icon">${icon(l.agent)}</span>
						<div class="grow"><b>${e(__(l.agent))}</b><div class="ags-muted">${e(l.title)}</div></div>
						<span class="ags-status ${e(l.status)}">${e(STATUS[l.status])}</span></div>
					<div class="ags-lane-now">${l.now.length ? l.now.map((n) => `<div>${l.status === "working" ? '<span class="ags-spin"></span>' : ""}${e(__(n))}</div>`).join("")
						: `<div class="ags-muted">${l.last ? e(label(l.last.action)) + " · " + e(frappe.datetime.prettyDate(l.last.creation)) : __("Nothing yet")}</div>`}</div>
					<div class="ags-metrics">${l.metrics.map(([k, v]) => `<span><b>${e(v)}</b> ${e(k)}</span>`).join("")}</div>
				</div>`).join(""));
		}

		render_funnel(s) {
			const max = Math.max(1, ...s.funnel.map(([, v]) => v));
			this.$root.find(".ags-funnel").html(s.funnel.map(([k, v]) => `<div class="ags-stage">
				<div class="ags-bar"><div style="height:${Math.max(4, Math.round((100 * v) / max))}%"></div></div>
				<b>${e(v)}</b><span>${e(k)}</span></div>`).join(""));
		}

		render_feed(s) {
			this.$root.find(".ags-feed").html(s.feed.map((a) => `<div class="ags-event">
				<span class="ags-dot ${e(a.agent || "Governance")}" title="${e(__(a.agent || "Governance"))}">${icon(a.agent || "Governance", 13)}</span>
				<div class="grow"><div><b>${e(label(a.action))}</b>${a.reference_name ? ` · <a href="/desk/${frappe.router.slug(a.reference_doctype || "")}/${encodeURIComponent(a.reference_name)}">${e(a.reference_name)}</a>` : ""}</div>
					${a.summary ? `<div class="ags-muted ags-clip">${e(a.summary)}</div>` : ""}</div>
				<span class="ags-muted ags-when">${e(frappe.datetime.prettyDate(a.creation))}</span></div>`).join("")
				|| `<div class="ags-empty">${__("The agents' work will appear here as it happens.")}</div>`);
		}

		// ---------------------------------------------------------------- the Needs-you inbox
		render_inbox(s) {
			const el = this.$root.find(".ags-inbox").empty();
			const asks = s.asks.filter((a) => a.key !== "onboard");
			if (!asks.length) {
				el.html(`<div class="ags-empty">${icon("Governance", 22)}<div>${__("Nothing needs you right now. The agents will ask here when a decision is yours.")}</div></div>`);
				return;
			}
			asks.forEach((a) => {
				const $c = $(`<div class="ags-ask"><div class="ags-ask-head"><span class="ags-dot ${e(a.agent)}">${icon(a.agent, 13)}</span>
					<div class="grow"><b>${e(__(a.title))}</b><div class="ags-muted">${e(__(a.detail || ""))}</div></div></div>
					<div class="ags-ask-body"></div></div>`).appendTo(el);
				const body = $c.find(".ags-ask-body");
				const fn = this[`ask_${a.key}`];
				if (fn) fn.call(this, body, a);
				else if (["research_market", "start_discovery", "draft_campaign", "auto_review"].includes(a.key)) this.ask_do(body, a);
			});
		}

		act(action, args, done) {
			return this.call("act", { action, args: JSON.stringify(args || {}) }).then((r) => {
				frappe.show_alert({ message: done || __("Done"), indicator: "green" });
				this.inboxKey = null;
				setTimeout(() => this.refresh(), 1200);
				return r;
			});
		}

		ask_do(body, a) {
			if (!this.data.can_manage) return body.html(`<div class="ags-muted">${__("A manager can start this.")}</div>`);
			$(`<button class="btn btn-primary btn-xs">${icon("spark", 12)} ${__("Do it")}</button>`).appendTo(body)
				.on("click", (ev) => {
					$(ev.currentTarget).prop("disabled", true);
					this.act(a.key, a.ref, __("Started; follow it in Live activity."));
				});
		}

		ask_approve_segments(body, a) {
			body.html(`${a.summary ? `<p class="ags-muted">${e(a.summary)}</p>` : ""}${a.segments.map((g) => `
				<label class="ags-seg"><input type="checkbox" value="${e(g.name)}" ${g.priority <= 2 ? "checked" : ""}>
					<div><b>${e(g.segment_name)}</b> <span class="ags-badge">P${e(g.priority)}</span>
					<div class="ags-muted">${e(g.fit_reason || "")}</div>
					<div class="ags-chips">${g.keywords.map((k) => `<span>${e(k)}</span>`).join("")}</div></div></label>`).join("")}
				<button class="btn btn-primary btn-xs ags-keep">${__("Target these segments")}</button>`);
			body.find(".ags-keep").on("click", () => {
				const keep = body.find("input:checked").map((_, x) => x.value).get();
				if (!keep.length) return frappe.msgprint(__("Keep at least one segment."));
				this.act("approve_segments", { brief: a.ref.brief, keep }, __("Segments chosen; the agents start finding leads."));
			});
		}

		ask_approve_campaign(body, a) {
			const c = a.campaign;
			body.html(`<div class="ags-kv"><span>${__("Offer")}</span><b>${e(c.offer || "-")}</b></div>
				<div class="ags-kv"><span>${__("Pilot")}</span><b>${c.pilot ? __("{0}% hold-out, up to {1} leads, {2} a day", [c.holdout, c.pilot_max, c.daily_limit]) : __("No")}</b></div>
				${c.steps.map((st) => `<details class="ags-msg"><summary>${__("Step {0}", [st.step_no])} · ${e(st.channel)} · ${__("day +{0}", [st.delay_days])}
					${st.subject ? ` · <b>${e(st.subject)}</b>` : ""}</summary><pre>${e(st.body)}</pre></details>`).join("")}
				${c.issues.length ? `<div class="ags-warn"><b>${__("The content check found:")}</b><ul>${c.issues.map((i) => `<li>${e(i)}</li>`).join("")}</ul>
					<label class="ags-check"><input type="checkbox" class="ags-ack"> ${__("I have read these and the campaign is accurate.")}</label></div>`
					: `<div class="ags-ok">${__("Content check passed: every claim is in your approved knowledge.")}</div>`}
				<div class="ags-row"><button class="btn btn-primary btn-xs ags-approve">${__("Approve and launch the pilot")}</button>
					<a class="btn btn-default btn-xs" href="/desk/sales-campaign/${encodeURIComponent(c.name)}">${__("Edit")}</a></div>`);
			body.find(".ags-approve").on("click", (ev) => {
				if (c.issues.length && !body.find(".ags-ack").is(":checked")) return frappe.msgprint(__("Confirm you have read the issues."));
				$(ev.currentTarget).prop("disabled", true);
				this.act("approve_campaign", { campaign: c.name, acknowledge_issues: c.issues.length ? 1 : 0 },
					__("Pilot launched; the agents draft the first messages.")).catch(() => $(ev.currentTarget).prop("disabled", false));
			});
		}

		ask_approve_drafts(body, a) {
			body.html(`${a.messages.map((m) => `<label class="ags-draft"><input type="checkbox" value="${e(m.name)}" checked>
				<details class="grow"><summary>${e(m.channel)} → ${e(m.recipient || "")}${m.is_reply ? ` <span class="ags-badge">${__("answer")}</span>` : ""}
					${m.subject ? ` · <b>${e(m.subject)}</b>` : ""}</summary><pre>${e(plain(m.body))}</pre></details></label>`).join("")}
				<div class="ags-row"><button class="btn btn-primary btn-xs ags-ok-msgs">${__("Approve selected")}</button>
				<span class="ags-muted">${this.data.outbound_enabled ? __("Approved messages go out within your daily limit.") : __("Dry run: approved messages are logged, not sent.")}</span></div>`);
			body.find(".ags-ok-msgs").on("click", () => {
				const messages = body.find("input:checked").map((_, x) => x.value).get();
				if (!messages.length) return;
				this.act("approve_messages", { messages }, __("{0} message(s) approved", [messages.length]));
			});
		}

		ask_review(body, a) {
			body.html(`${a.prospects.map((p) => `<div class="ags-lead" data-name="${e(p.name)}">
				<div class="grow"><a href="/desk/sales-prospect/${encodeURIComponent(p.name)}"><b>${e(p.business_name)}</b></a>
					<div class="ags-muted">${e([p.city, p.website && p.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")].filter(Boolean).join(" · "))}</div></div>
				<span class="ags-score" title="${__("Fit / deal probability / identity")}">${Math.round(p.fit_score || 0)} · ${Math.round(p.deal_probability || 0)}% · ${Math.round(p.identity_confidence || 0)}</span>
				<button class="btn btn-default btn-xs" data-d="approve">${__("Approve")}</button>
				<button class="btn btn-default btn-xs" data-d="reject">${__("Reject")}</button></div>`).join("")}
				<a class="btn btn-default btn-xs" href="/desk/sales-review">${__("Open the full review")}</a>`);
			body.find(".ags-lead button").on("click", (ev) => {
				const row = $(ev.currentTarget).closest(".ags-lead");
				row.find("button").prop("disabled", true);
				this.act("review", { prospects: [row.data("name")], decision: ev.currentTarget.dataset.d },
					ev.currentTarget.dataset.d === "approve" ? __("Approved and added to the CRM") : __("Rejected"));
			});
		}

		ask_followups(body, a) {
			body.html((a.tasks || []).map((t) => `<div class="ags-lead"><div class="grow"><b>${e(t.title)}</b>
				<div class="ags-muted">${e(t.business || "")}${t.due_date ? " · " + __("due {0}", [frappe.datetime.str_to_user(t.due_date)]) : ""}</div></div>
				<a class="btn btn-default btn-xs" href="/crm/leads/${encodeURIComponent(t.reference_docname)}">${__("Open in CRM")}</a></div>`).join("")
				|| `<div class="ags-muted">${__("Open your ToDo list to see them.")}</div>`);
		}

		ask_pause_campaign(body, a) {
			$(`<button class="btn btn-default btn-xs">${__("Pause the campaign")}</button>`).appendTo(body)
				.on("click", () => this.act("pause_campaign", { campaign: a.ref.campaign }, __("Campaign paused")));
		}

		ask_scale_campaign(body, a) {
			body.html(`<a class="btn btn-default btn-xs" href="/desk/sales-campaign/${encodeURIComponent(a.ref.campaign)}">${__("Open the campaign to widen it")}</a>`);
		}
	}
})();
