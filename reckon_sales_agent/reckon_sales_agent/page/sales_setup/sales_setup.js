// Get started: one guided page. Managers set the Company up in six steps with AI filling in the blanks;
// a new salesperson gets a two-step track. Each step is done when the system says so.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-setup"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Get Started"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.setup = new Setup(page);
	};
	frappe.pages["sales-setup"].on_page_show = (wrapper) => wrapper.setup && wrapper.setup.load();
	frappe.pages["sales-setup"].on_page_hide = (wrapper) => wrapper.setup && clearTimeout(wrapper.setup.timer);

	const API = "reckon_sales_agent.api_setup.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const lines = (v) => String(v || "").split("\n").map((s) => s.trim()).filter(Boolean);
	const CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
	const SPARK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>';
	const INTRO = {
		business: __("Type your website: the AI reads it and fills in what you sell and who buys it. Correct anything it got wrong."),
		market: __("The Research agent studies your market on the web and proposes customer segments to target."),
		facts: __("Messages may only state facts you approved. The AI drafts them from your website; you approve the true ones."),
		team: __("Who signs your emails, the address the law requires in them, who makes the calls, and who gets the daily digest."),
		sources: __("Where the agents look for leads. Your provider switches the sources on; you confirm you may use them."),
		autopilot: __("Let the agents run every hour within your rules. Launching campaigns and sending messages always wait for you."),
		me: __("Your name goes into the call scripts the agents write for you, and your number into the CRM."),
		day: __("How a day with your AI sales team works."),
	};

	class Setup {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="sus"></div>').appendTo(page.main);
			this.open = null;
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		load() {
			return this.call("status").then((s) => {
				this.s = s;
				if (!this.open || !s.steps.some((x) => x.key === this.open)) {
					this.open = (s.steps.find((x) => !x.done) || s.steps[s.steps.length - 1]).key;
				}
				this.render();
				// Keep watching while an agent is working in the background.
				clearTimeout(this.timer);
				const busy = s.profile.onboarding_status === "Reading website" || (s.brief && s.brief.status === "Researching");
				if (busy) this.timer = setTimeout(() => this.load(), 4000);
			});
		}

		render() {
			const s = this.s;
			const doneAll = s.steps.every((x) => x.done);
			this.$root.html(`
				<div class="sus-hero"><div><h2>${s.seller ? __("Welcome to the sales team") : __("Set up your AI sales team")}</h2>
					<p>${s.seller ? __("Two short steps, then the agents hand you your calls every morning.")
						: __("Six steps, most of them done by AI. Every step can be changed later.")}</p></div>
					<div class="sus-progress" title="${s.progress}%"><div class="ring" style="--p:${s.progress}"><span>${s.progress}%</span></div></div></div>
				${doneAll ? `<div class="sus-done">${CHECK} <b>${__("All set.")}</b> ${__("Your agents are working; follow them in the Agent Studio.")}
					<button class="btn btn-primary btn-sm sus-go">${__("Open the Agent Studio")}</button></div>` : ""}
				<div class="sus-steps">${s.steps.map((step, i) => `
					<section class="sus-step ${step.done ? "done" : ""} ${this.open === step.key ? "open" : ""}" data-key="${step.key}">
						<button class="sus-head" aria-expanded="${this.open === step.key}">
							<span class="num">${step.done ? CHECK : i + 1}</span>
							<span class="t"><b>${e(__(step.title))}</b><span class="intro">${e(INTRO[step.key])}</span></span>
							<span class="state">${step.done ? __("Done") : __("To do")}</span></button>
						<div class="sus-body"></div></section>`).join("")}</div>`);
			this.$root.find(".sus-go").on("click", () => frappe.set_route("sales-agent"));
			this.$root.find(".sus-head").on("click", (ev) => {
				const key = $(ev.currentTarget).closest(".sus-step").data("key");
				this.open = this.open === key ? null : key;
				this.render();
			});
			const step = this.$root.find(`.sus-step[data-key="${this.open}"] .sus-body`);
			if (step.length) this[`step_${this.open}`](step);
		}

		next() {
			return this.load().then(() => {
				const todo = this.s.steps.find((x) => !x.done);
				if (todo) { this.open = todo.key; this.render(); }
			});
		}

		busy(btn, promise) {
			const $b = $(btn).prop("disabled", true);
			return promise.finally(() => $b.prop("disabled", false));
		}

		// ------------------------------------------------------------ 1. business
		step_business(el) {
			const p = this.s.profile;
			const reading = p.onboarding_status === "Reading website";
			const field = (key, label, rows, hint) => `<label class="sus-field"><span>${e(label)}</span>
				<textarea class="form-control" data-f="${key}" rows="${rows}" placeholder="${e(hint || "")}">${e(p[key])}</textarea></label>`;
			el.html(`<div class="sus-ai">${SPARK}<div class="grow"><b>${__("Let AI fill this in")}</b>
					<div class="sus-row"><input class="form-control sus-web" placeholder="${__("yourcompany.com")}" value="${e(p.website)}">
					<button class="btn btn-default btn-sm sus-read" ${this.s.seller ? "disabled" : ""}>${reading ? __("Reading…") : __("Read my website")}</button></div>
					${p.onboarding_status === "Failed" ? `<div class="sus-warn">${__("The website could not be read. Fill in the fields below instead.")}</div>` : ""}</div></div>
				<div class="sus-grid">
					<label class="sus-field"><span>${__("Business name")}</span><input class="form-control" data-f="business_name" value="${e(p.business_name)}"></label>
					${field("what_we_sell", __("What you sell (one sentence)"), 2, __("e.g. Distribution management software for FMCG and pharma distributors"))}
					${field("products", __("Products and services (one per line)"), 3)}
					${field("target_industries", __("Industries you sell to"), 3)}
					${field("business_types", __("Types of business that buy"), 3, __("e.g. distributors, wholesalers"))}
					${field("regions", __("Where you sell"), 3, __("e.g. Dhaka, Chattogram"))}
					${field("competitors", __("Competitors (never contacted)"), 2)}
				</div>
				<div class="sus-actions"><button class="btn btn-primary btn-sm sus-save">${__("Save and continue")}</button></div>`);
			el.find(".sus-read").on("click", (ev) => {
				const website = el.find(".sus-web").val().trim();
				if (!website) return frappe.msgprint(__("Type your website first."));
				this.busy(ev.currentTarget, frappe.xcall("reckon_sales_agent.api_agent_studio.onboard", { website })
					.then(() => { frappe.show_alert({ message: __("Reading your website…"), indicator: "blue" }); return this.load(); }));
			});
			el.find(".sus-save").on("click", (ev) => {
				const data = {};
				el.find("[data-f]").each((_, x) => (data[x.dataset.f] = x.value));
				if (!String(data.what_we_sell || "").trim()) return frappe.msgprint(__("Say what you sell in one sentence."));
				this.busy(ev.currentTarget, frappe.xcall("reckon_sales_agent.api_studio.save_business", { data: JSON.stringify(data) })
					.then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ 2. market
		step_market(el) {
			const b = this.s.brief;
			if (!this.s.steps.find((x) => x.key === "business").done) {
				return el.html(`<div class="sus-muted">${__("Describe your business first (step 1).")}</div>`);
			}
			if (!b || b.status === "Failed") {
				el.html(`${b ? `<div class="sus-warn">${__("The last research failed")}: ${e(b.error || "")}</div>` : ""}
					<div class="sus-ai">${SPARK}<div class="grow"><b>${__("Research my market")}</b>
					<div class="sus-muted">${__("About two minutes. The agent reads the web about your industries, buyers and competitors.")}</div></div>
					<button class="btn btn-primary btn-sm sus-research">${__("Start research")}</button></div>`);
				return el.find(".sus-research").on("click", (ev) => this.busy(ev.currentTarget,
					frappe.xcall("reckon_sales_agent.api_studio.research_market").then(() => this.load())));
			}
			if (b.status === "Researching") {
				return el.html(`<div class="sus-wait"><span class="spin"></span>${__("Researching your market. This page updates by itself.")}</div>`);
			}
			const approved = b.status === "Approved";
			el.html(`<p class="sus-muted">${e(b.summary || "")}</p>
				${b.segments.map((g) => `<label class="sus-seg"><input type="checkbox" value="${e(g.name)}"
					${(approved ? g.include : g.priority <= 2) ? "checked" : ""} ${approved ? "disabled" : ""}>
					<div><b>${e(g.segment_name)}</b> <span class="sus-badge">${__("Priority {0}", [g.priority])}</span>
					<div class="sus-muted">${e(g.fit_reason || "")}</div>
					<div class="sus-chips">${g.keywords.map((k) => `<span>${e(k)}</span>`).join("")}</div></div></label>`).join("")}
				<div class="sus-actions">${approved ? `<span class="sus-muted">${__("Segments chosen. The agents search them every week.")}</span>`
					: `<span class="sus-muted">${__("Suggested: the priority 1 and 2 segments.")}</span>
					<button class="btn btn-primary btn-sm sus-keep">${__("Target these segments")}</button>`}</div>`);
			el.find(".sus-keep").on("click", (ev) => {
				const keep = el.find("input:checked").map((_, x) => x.value).get();
				if (!keep.length) return frappe.msgprint(__("Keep at least one segment."));
				this.busy(ev.currentTarget, this.call("choose_segments", { brief: b.name, keep: JSON.stringify(keep) }).then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ 3. facts
		step_facts(el) {
			const facts = this.s.facts;
			const drafts = facts.filter((f) => f.status === "Draft");
			el.html(`<div class="sus-ai">${SPARK}<div class="grow"><b>${__("Draft facts from my website")}</b>
					<div class="sus-muted">${__("The AI writes short facts from your pages. Nothing is used until you approve it.")}</div></div>
					<button class="btn btn-default btn-sm sus-draft">${facts.length ? __("Draft more") : __("Draft facts")}</button></div>
				${facts.map((f) => `<label class="sus-fact ${f.status === "Approved" ? "ok" : ""}">
					<input type="checkbox" value="${e(f.name)}" ${f.status === "Approved" ? "checked disabled" : "checked"}>
					<div class="grow"><b>${e(f.title)}</b> <span class="sus-badge">${e(__(f.category))}</span>
						${f.status === "Approved" ? `<span class="sus-badge ok">${__("Approved")}</span>` : ""}
						<div class="sus-muted">${e(f.content)}</div>
						${f.source_url ? `<a class="sus-src" href="${e(f.source_url)}" target="_blank" rel="noopener noreferrer">${e(f.source_url)}</a>` : ""}</div>
					<a class="btn btn-xs btn-default" href="/desk/sales-knowledge-item/${encodeURIComponent(f.name)}">${__("Edit")}</a></label>`).join("")
					|| `<div class="sus-muted">${__("No facts yet.")}</div>`}
				${drafts.length ? `<div class="sus-actions"><span class="sus-muted">${__("Untick anything that is not true.")}</span>
					<button class="btn btn-primary btn-sm sus-approve">${__("Approve ticked facts")}</button></div>` : ""}`);
			el.find(".sus-draft").on("click", (ev) => this.busy(ev.currentTarget, frappe.call({ method: API + "draft_facts", freeze: true,
				freeze_message: __("Reading your website and drafting facts…") }).then((r) => {
				frappe.show_alert({ message: __("{0} draft fact(s) to review", [r.message]), indicator: "blue" });
				return this.load();
			})));
			el.find(".sus-approve").on("click", (ev) => {
				const names = el.find("input:checked:not(:disabled)").map((_, x) => x.value).get();
				if (!names.length) return frappe.msgprint(__("Tick at least one fact."));
				this.busy(ev.currentTarget, this.call("approve_facts", { names: JSON.stringify(names) }).then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ 4. team
		step_team(el) {
			const t = this.s.team;
			const suggest = (value) => (value ? `<button type="button" class="btn btn-xs btn-link sus-suggest" data-v="${e(value)}">${SPARK} ${__("Use {0}", [e(value)])}</button>` : "");
			el.html(`<div class="sus-grid">
					<label class="sus-field"><span>${__("Emails are signed by")}</span><input class="form-control" data-f="sender_name" value="${e(t.sender_name)}"
						placeholder="${__("e.g. Rahim from Reckon Technologies")}">${suggest(t.suggested_sender)}</label>
					<label class="sus-field"><span>${__("Your business address (shown at the bottom of every email)")}</span>
						<textarea class="form-control" rows="2" data-f="physical_address">${e(t.physical_address)}</textarea>${suggest(t.suggested_address)}</label>
					<label class="sus-field"><span>${__("Who makes the calls")}</span><select class="form-control" data-f="task_assignee">
						<option value="">${__("Whoever found the lead")}</option>
						${t.users.map((u) => `<option value="${e(u.user)}" ${u.user === t.task_assignee ? "selected" : ""}>${e(u.name)} · ${e(u.role || "")}</option>`).join("")}
					</select></label>
					<label class="sus-field"><span>${__("Also send the daily digest to (one per line)")}</span>
						<textarea class="form-control" rows="2" data-f="digest_recipients">${e(t.digest_recipients)}</textarea></label>
				</div>
				<div class="sus-actions"><button class="btn btn-primary btn-sm sus-save">${__("Save and continue")}</button></div>`);
			el.find(".sus-suggest").on("click", (ev) => $(ev.currentTarget).siblings("input, textarea").val(ev.currentTarget.dataset.v));
			el.find(".sus-save").on("click", (ev) => {
				const data = {};
				el.find("[data-f]").each((_, x) => (data[x.dataset.f] = x.value));
				if (!data.sender_name.trim() || !data.physical_address.trim()) {
					return frappe.msgprint(__("Emails need a sender name and your business address."));
				}
				this.busy(ev.currentTarget, this.call("save_team", { data: JSON.stringify(data) }).then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ 5. sources
		step_sources(el) {
			const src = this.s.sources;
			const names = { places: __("Business listings (Brave Places, Google Maps)"), page_context: __("Web pages with contact details"),
				web_search: __("Web search for verifying leads") };
			el.html(`<div class="sus-list">${Object.entries(src.providers).map(([cap, list]) => `<div class="sus-line">
					<span class="sus-dot ${list.length ? "ok" : ""}"></span><b>${e(names[cap])}</b>
					<span class="sus-muted">${list.length ? e(list.join(", ")) : __("Not switched on by your provider")}</span></div>`).join("")}</div>
				${src.connector_ready ? `<div class="sus-ok">${CHECK} ${__("Smart Sources is on: every source above in one search.")}</div>`
					: `<label class="sus-check"><input type="checkbox" class="sus-consent"> ${__("We may use these sources to find businesses, under the sources' terms and our provider's retention rules.")}</label>
					<div class="sus-actions"><button class="btn btn-primary btn-sm sus-use">${__("Use Smart Sources")}</button></div>`}`);
			el.find(".sus-use").on("click", (ev) => {
				if (!el.find(".sus-consent").is(":checked")) return frappe.msgprint(__("Tick the box to confirm first."));
				this.busy(ev.currentTarget, this.call("use_smart_sources").then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ 6. autopilot
		step_autopilot(el) {
			const a = this.s.autopilot;
			if (a.enabled) {
				return el.html(`<div class="sus-ok">${CHECK} ${__("Autopilot is on. The agents work every hour; decisions come to your inbox and digest.")}</div>
					<div class="sus-actions"><button class="btn btn-default btn-sm sus-go2">${__("Tune it in the Agent Studio")}</button></div>`)
					.find(".sus-go2").on("click", () => frappe.set_route("sales-agent"));
			}
			const v = a.suggested;
			el.html(`<div class="sus-muted" style="margin-bottom:8px">${SPARK} ${__("Suggested for your plan and scoring; change anything.")}</div>
				<div class="sus-grid">
					<label class="sus-field"><span>${__("Leads to find per week")}</span><input type="number" class="form-control" data-f="weekly_leads" min="5" max="1000" value="${e(v.weekly_leads)}"></label>
					<label class="sus-field"><span>${__("Approve leads automatically at fit score")}</span><input type="number" class="form-control" data-f="min_fit" min="0" max="100" value="${e(v.min_fit)}"></label>
					<label class="sus-field"><span>${__("Approved leads before a pilot campaign is drafted")}</span><input type="number" class="form-control" data-f="min_prospects" min="1" max="200" value="${e(v.min_prospects)}"></label>
					<div class="sus-field"><label class="sus-check"><input type="checkbox" data-c="ai_triage" checked> ${__("Let AI decide clear-cut leads")}</label>
						<label class="sus-check"><input type="checkbox" data-c="daily_digest" checked> ${__("Daily digest at 08:00")}</label></div>
				</div>
				<label class="sus-check"><input type="checkbox" class="sus-consent"> ${__("I agree the agents may use our enabled lead sources and create leads, CRM records and draft campaigns on their own.")}</label>
				<div class="sus-actions"><button class="btn btn-primary btn-sm sus-on">${__("Turn on autopilot")}</button></div>`);
			el.find(".sus-on").on("click", (ev) => {
				if (!el.find(".sus-consent").is(":checked")) return frappe.msgprint(__("Tick the box to confirm first."));
				const data = { enabled: 1, consent: 1 };
				el.find("[data-f]").each((_, x) => (data[x.dataset.f] = Number(x.value)));
				el.find("[data-c]").each((_, x) => (data[x.dataset.c] = x.checked ? 1 : 0));
				this.busy(ev.currentTarget, frappe.xcall("reckon_sales_agent.api_agent_studio.set_autopilot", { data: JSON.stringify(data) })
					.then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ salesperson: you
		step_me(el) {
			const me = this.s.me;
			el.html(`<div class="sus-grid">
					<label class="sus-field"><span>${__("First name (said on calls)")}</span><input class="form-control" data-f="first_name" value="${e(me.first_name)}"></label>
					<label class="sus-field"><span>${__("Last name")}</span><input class="form-control" data-f="last_name" value="${e(me.last_name)}"></label>
					<label class="sus-field"><span>${__("Mobile number")}</span><input class="form-control" data-f="mobile_no" value="${e(me.mobile_no)}" placeholder="+8801…"></label>
				</div>
				<div class="sus-actions"><button class="btn btn-primary btn-sm sus-save">${__("Save and continue")}</button></div>`);
			el.find(".sus-save").on("click", (ev) => {
				const data = {};
				el.find("[data-f]").each((_, x) => (data[x.dataset.f] = x.value));
				this.busy(ev.currentTarget, this.call("save_me", { data: JSON.stringify(data) }).then(() => this.next()));
			});
		}

		// ------------------------------------------------------------ salesperson: your day
		step_day(el) {
			const items = [
				[__("08:00"), __("A digest arrives with today's calls: each business, its number and a script in English and Bangla.")],
				[__("Call"), __("Tap the number in the Agent Studio's Calls card. The script says who they are and what to ask.")],
				[__("After"), __("Pick what happened: Interested, Call back, No answer, Not interested or Wrong number.")],
				[__("Agents"), __("They do the rest: add the lead to the CRM with a demo task, schedule the callback, or retry tomorrow.")],
			];
			el.html(`<ol class="sus-day">${items.map(([k, v]) => `<li><b>${e(k)}</b><span>${e(v)}</span></li>`).join("")}</ol>
				<div class="sus-actions"><button class="btn btn-default btn-sm sus-studio">${__("See my calls")}</button>
				<button class="btn btn-primary btn-sm sus-got">${__("Got it")}</button></div>`);
			el.find(".sus-studio").on("click", () => frappe.set_route("sales-agent"));
			el.find(".sus-got").on("click", (ev) => this.busy(ev.currentTarget, this.call("seen_day").then(() => this.next())));
		}
	}
})();
