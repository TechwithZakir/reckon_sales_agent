// Integrations: every channel and service the agents use, as a gallery of tiles. A tile shows the integration's
// state at a glance; opening it slides in a panel with its setup (sign-in, keys, webhook addresses, options).
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-channels"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Integrations"), single_column: true });
		page.add_inner_button(__("Conversations"), () => frappe.set_route("sales-inbox"));
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.hub = new Hub(page);
	};
	frappe.pages["sales-channels"].on_page_show = (wrapper) => wrapper.hub && wrapper.hub.load();

	const API = "reckon_sales_agent.api_channels.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	// Line icons (24px grid, stroke) and letter marks for the social platforms.
	const ICONS = {
		mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
		send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
		whatsapp: '<path d="M3 21l1.6-4.6A8.5 8.5 0 1 1 8 19.6z"/><path d="M9 9.5c.3 2 2.5 4.2 4.5 4.5l1-1.2 2 .9c-.3 1.2-1.4 1.8-2.6 1.6-3-.6-5.4-3-6-6-.2-1.2.4-2.3 1.6-2.6l.9 2z"/>',
		chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8M8 13h5"/>',
		sms: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M9 7h6M9 10h4"/><circle cx="12" cy="18" r=".8"/>',
		phone: '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2z"/>',
		wave: '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2z"/><path d="M15 3a6 6 0 0 1 6 6M15 7a2 2 0 0 1 2 2"/>',
		mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
		spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
		cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
		form: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
		shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
		search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
		close: '<path d="M6 6l12 12M18 6 6 18"/>',
		copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
		arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
	};
	const icon = (name, size = 20) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.spark}</svg>`;

	const CATEGORIES = [["all", __("All")], ["messaging", __("Messaging")], ["social", __("Social & leads")],
		["voice", __("Calls & SMS")], ["email", __("Email")], ["ai", __("AI & team")]];
	const STATE_LABEL = { on: __("Connected"), warn: __("Needs attention"), off: __("Not connected"), na: __("Unavailable") };

	// The gallery. ``state(d)`` -> [on|warn|off|na, short text]; ``body(d)`` -> the panel; ``bind($p, d)`` wires it.
	const INTEGRATIONS = [
		{ key: "autopilot", cat: "ai", name: __("AI autopilot & team"), glyph: "spark", color: "#7c3aed",
			desc: __("Answer simple chats at once, share conversations among your team"),
			state: (d) => d.fast.auto_answer ? ["on", __("Autopilot on")] : ["off", __("Every reply waits for approval")] },
		{ key: "ai", cat: "ai", name: __("AI model"), glyph: "cpu", color: "#0f766e",
			desc: __("The AI behind every agent, chosen by your system provider"),
			state: (d) => d.ai.error ? ["warn", d.ai.error] : d.ai.on ? ["on", `${d.ai.label}${d.ai.model ? " · " + d.ai.model : ""}`] : ["off", __("AI is off")] },
		{ key: "webchat", cat: "messaging", name: __("Website chat"), glyph: "chat", color: "#db2777",
			desc: __("A chat button on your website, answered by the AI and your team"),
			state: (d) => d.webchat.enabled ? ["on", __("{0} chats", [d.counts["Web Chat"]])] : ["off", __("Off")] },
		{ key: "whatsapp", cat: "messaging", name: "WhatsApp", glyph: "whatsapp", color: "#16a34a",
			desc: __("WhatsApp Business Cloud API: replies, templates, opt-ins"),
			state: (d) => !d.whatsapp.installed ? ["na", __("App not installed")] : d.whatsapp.enabled && d.whatsapp.account ? ["on", d.whatsapp.account] : d.whatsapp.enabled ? ["warn", __("Choose an account")] : ["off", __("Off")] },
		{ key: "facebook", cat: "social", name: __("Facebook & Messenger"), mark: "f", color: "#1877f2",
			desc: __("Pages: approved posts, Messenger chats, buying comments"),
			state: (d) => social(d, ["Facebook Page"]) },
		{ key: "instagram", cat: "social", name: "Instagram", mark: "ig", color: "#c13584",
			desc: __("Professional accounts: posts, messages and comments"),
			state: (d) => social(d, ["Instagram"]) },
		{ key: "linkedin", cat: "social", name: __("LinkedIn pages"), mark: "in", color: "#0a66c2",
			desc: __("Company pages you administer: approved posts"),
			state: (d) => d.linkedin_ready ? social(d, ["LinkedIn"]) : ["na", __("Waiting for the system provider")] },
		{ key: "meta_leads", cat: "social", name: __("Meta lead ads"), glyph: "form", color: "#1877f2",
			desc: __("Facebook and Instagram lead forms, in real time, with a call task"),
			state: (d) => social(d, ["Facebook Page"], __("Through your Facebook Pages")) },
		{ key: "linkedin_leads", cat: "social", name: __("LinkedIn lead forms"), glyph: "form", color: "#0a66c2",
			desc: __("Lead Gen form answers every hour, with a call task"),
			state: (d) => d.linkedin_ready ? social(d, ["LinkedIn Lead Gen"]) : ["na", __("Waiting for the system provider")] },
		{ key: "twilio", cat: "voice", name: "Twilio", glyph: "wave", color: "#e11d48",
			desc: __("Calls, recordings, SMS and RCS from one account"),
			state: (d) => d.twilio.ready ? ["on", [d.twilio.calls && __("Calls"), d.twilio.sms && "SMS/RCS", d.twilio.voice_ai && __("Voice AI")].filter(Boolean).join(" · ") || __("Connected")] : ["off", __("Not connected")] },
		{ key: "voice_ai", cat: "ai", name: __("AI voice assistant"), glyph: "mic", color: "#9333ea",
			desc: __("Answers incoming calls from your approved facts, connects a person for the rest"),
			state: (d) => !d.twilio.ready ? ["na", __("Needs Twilio")] : d.twilio.voice_ai ? ["on", __("Answering calls")] : ["off", __("Off")] },
		{ key: "sms", cat: "voice", name: __("SMS (Bangladesh)"), glyph: "sms", color: "#ea580c",
			desc: __("BulkSMSBD, SSL Wireless or the platform gateway"),
			state: (d) => !d.sms.enabled ? ["off", __("Off")] : d.sms.configured ? ["on", __(d.sms.provider)] : ["warn", __("Needs keys")] },
		{ key: "asterisk", cat: "voice", name: __("Office phone (Asterisk)"), glyph: "phone", color: "#475569",
			desc: __("Your own PBX and a Bangladeshi IPTSP SIP trunk"),
			state: (d) => d.phone.provider === "Asterisk (SIP)" ? (d.phone.asterisk ? ["on", __("Click-to-call on")] : ["warn", __("Needs the ARI address")]) : ["off", __("Not used")] },
		{ key: "email", cat: "email", name: __("Email"), glyph: "mail", color: "#2563eb",
			desc: __("Your outgoing mailbox for replies and campaigns"),
			state: (d) => d.twilio.email ? ["on", __("Through SendGrid")] : d.email.account ? ["on", d.email.account] : ["warn", __("No outgoing account")] },
		{ key: "sendgrid", cat: "email", name: "Twilio SendGrid", glyph: "send", color: "#0284c7",
			desc: __("High-volume email with bounce and spam-report tracking"),
			state: (d) => d.twilio.email ? (d.values.sendgrid_api_key ? ["on", __("Sending")] : ["warn", __("Needs an API key")]) : ["off", __("Not used")] },
	];

	// The system provider's tiles: shown and saved only to vendor roles (the server checks too).
const PLATFORM_TILES = [
    { key: "platform_ai", cat: "platform", platform: true, name: __("AI provider and model"), glyph: "cpu", color: "#0f766e",
        desc: __("The AI for every customer; customers may bring their own if you allow it"),
        state: (d) => {
            const p = d.platform;
            if (!p.ai_enabled) return ["off", __("Off")];
            return p.anthropic_api_key || p.openai_api_key || p.local_ai_base_url ? ["on", p.ai_provider || ""] : ["warn", __("Needs a key")];
        } },
    { key: "platform_meta", cat: "platform", platform: true, name: __("Meta app"), mark: "f", color: "#1877f2",
        desc: __("One app for every customer: Pages, Instagram, Messenger and lead ads"),
        state: (d) => d.platform.meta_app_id && d.platform.meta_app_secret ? ["on", __("App set up")]
            : d.platform.meta_app_id ? ["warn", __("Needs the secret")] : ["off", __("Not set up")] },
    { key: "platform_linkedin", cat: "platform", platform: true, name: __("LinkedIn app"), mark: "in", color: "#0a66c2",
        desc: __("One app for every customer: company pages and Lead Gen forms"),
        state: (d) => d.platform.linkedin_client_id && d.platform.linkedin_client_secret ? ["on", __("App set up")]
            : d.platform.linkedin_client_id ? ["warn", __("Needs the secret")] : ["off", __("Not set up")] },
    { key: "platform_transcription", cat: "platform", platform: true, name: __("Call transcription"), glyph: "mic", color: "#9333ea",
        desc: __("Transcribes recorded calls and writes the summary to the CRM"),
        state: (d) => !d.platform.transcription_enabled ? ["off", __("Off")] : ["on", d.platform.transcription_provider || ""] },
    { key: "platform_lead_sources", cat: "platform", platform: true, name: __("Lead sources"), glyph: "search", color: "#2563eb",
        desc: __("Brave, Google Places, Google Maps and Search providers that find leads"),
        state: (d) => { const p = d.platform, n = ["brave_enabled", "places_enabled", "serpapi_enabled", "apify_enabled", "scrapingdog_enabled", "scrapingbee_enabled"].filter((k) => p[k]).length;
            return n ? ["on", __("{0} provider(s) on", [n])] : ["warn", __("No provider on")]; } },
    { key: "platform_research", cat: "platform", platform: true, name: __("Website research"), glyph: "form", color: "#0d9488",
        desc: __("How the agents read a lead's website: politeness, limits and size"),
        state: (d) => d.platform.research_enabled ? ["on", __("On")] : ["off", __("Off")] },
    { key: "platform_social", cat: "platform", platform: true, name: __("Social publishing"), glyph: "send", color: "#0284c7",
        desc: __("Publishing approved posts to Facebook, Instagram and LinkedIn: API versions"),
        state: (d) => d.platform.social_enabled ? ["on", __("On")] : ["off", __("Off")] },
    { key: "platform_email_events", cat: "platform", platform: true, name: __("Email delivery events"), glyph: "mail", color: "#2563eb",
        desc: __("Bounces and spam reports from your email provider reach the do-not-contact list"),
        state: (d) => d.platform.email_webhook_secret ? ["on", __("Signed")] : ["warn", __("Needs a signing secret")] },
    { key: "platform_plans", cat: "platform", platform: true, name: __("Plans and limits"), glyph: "shield", color: "#475569",
        desc: __("Monthly limits per Company, research budgets and internal companies"),
        state: (d) => d.platform.monthly_message_limit || d.platform.monthly_ai_limit ? ["on", __("Limits set")] : ["warn", __("No limits set")] },
    { key: "platform_experimental", cat: "platform", platform: true, name: __("Experimental browsers"), glyph: "cpu", color: "#b91c1c",
        desc: __("Headless browsers for Google Maps and Search: off unless you have reviewed the terms"),
        state: (d) => d.platform.maps_browser_enabled || d.platform.search_browser_enabled ? ["warn", __("On")] : ["off", __("Off")] },
];

function social(d, platforms, onText) {
		const rows = d.accounts.filter((a) => platforms.includes(a.platform));
		if (rows.some((a) => a.enabled && a.last_error)) return ["warn", __("Reconnect needed")];
		const live = rows.filter((a) => a.enabled);
		if (live.length) return ["on", onText || (live.length === 1 ? live[0].account_name : __("{0} accounts", [live.length]))];
		return platforms.some((p) => p.startsWith("LinkedIn")) || d.meta_ready ? ["off", __("Not connected")] : ["na", __("Waiting for the system provider")];
	}

	class Hub {
		constructor(page) {
			this.page = page;
			this.cat = "all";
			this.q = "";
			this.$root = $('<div class="sch"></div>').appendTo(page.main);
			$(document).off("keydown.schhub").on("keydown.schhub", (ev) => { if (ev.key === "Escape") this.close(); });
		}

		call(method, args) {
			return frappe.xcall(API + method, this.company ? { ...(args || {}), company: this.company } : (args || {}));
		}

		load() {
			const params = new URLSearchParams(window.location.search);
			if (params.get("connected")) frappe.show_alert({ message: __("Connected {0} account(s).", [params.get("connected")]), indicator: "green" });
			if (params.get("connect_error")) frappe.msgprint({ title: __("Not connected"), message: e(params.get("connect_error")), indicator: "orange" });
			if (params.get("connected") || params.get("connect_error")) window.history.replaceState(null, "", window.location.pathname);
			return this.call("overview").then((d) => this.render(d));
		}

		// ------------------------------------------------------------ gallery
		company_switch(d) {
			return `<label class="sch-company"><span>${icon("shield", 15)} ${__("Company")}</span><select class="form-control sch-co">${(d.companies || []).map((c) => `<option ${c === d.company ? "selected" : ""}>${e(c)}</option>`).join("")}</select></label>`;
		}

		render(d) {
			this.data = d;
			const shown = INTEGRATIONS.filter((i) => !i.platform);
			const states = shown.map((i) => i.state(d)[0]);
			const connected = states.filter((s) => s === "on").length, attention = states.filter((s) => s === "warn").length;
			this.$root.html(`
				<div class="sch-hero">
					<div><h2>${__("Integrations")}</h2>
						<p>${__("Connect the channels your leads use. Each one feeds Conversations and the agents.")}</p></div>
					${d.is_vendor ? this.company_switch(d) : ""}
					<div class="sch-stats"><div><b>${connected}</b><span>${__("connected")}</span></div>
						<div class="${attention ? "warn" : ""}"><b>${attention}</b><span>${__("need attention")}</span></div>
						<div><b>${shown.length - connected - attention}</b><span>${__("available")}</span></div></div>
				</div>
				${d.vendor ? this.vendor_strip(d.vendor) : ""}
				${d.outbound_enabled ? "" : `<div class="sch-note">${icon("shield", 16)}<span>${__("Dry run is on: approved replies are recorded but not delivered. Switch it off in Sales Agent Settings when you are ready.")}</span></div>`}
				<div class="sch-toolbar">
					<div class="sch-cats" role="tablist">${(d.is_vendor ? [...CATEGORIES, ["platform", __("System provider")]] : CATEGORIES).map(([k, l]) => `<button role="tab" data-cat="${k}" class="${this.cat === k ? "on" : ""}">${e(l)}</button>`).join("")}</div>
					<label class="sch-search">${icon("search", 15)}<input placeholder="${__("Search integrations")}" value="${e(this.q)}"></label>
				</div>
				<div class="sch-tiles"></div>
				<div class="sch-drawer" aria-hidden="true"><div class="sch-scrim"></div><aside class="sch-panel" role="dialog" aria-modal="true"></aside></div>`);
			this.render_tiles();
			this.$root.find(".sch-cats button").on("click", (ev) => { this.cat = ev.currentTarget.dataset.cat; this.$root.find(".sch-cats button").removeClass("on"); $(ev.currentTarget).addClass("on"); this.render_tiles(); });
			this.$root.find(".sch-search input").on("input", (ev) => { this.q = ev.target.value.toLowerCase(); this.render_tiles(); });
			this.$root.find(".sch-scrim").on("click", () => this.close());
			this.$root.find(".sch-co").on("change", (ev) => { this.company = ev.target.value; this.openKey = null; this.load(); });
			this.$root.find(".sch-vendor-strip").on("click", () => this.open("vendor"));
			if (this.openKey) this.open(this.openKey);
		}

		render_tiles() {
			const d = this.data;
			const rows = [...INTEGRATIONS, ...(d.is_vendor ? PLATFORM_TILES : [])].filter((i) => (this.cat === "all" || i.cat === this.cat)
				&& (!this.q || `${i.name} ${i.desc}`.toLowerCase().includes(this.q)));
			this.$root.find(".sch-tiles").html(rows.map((i) => {
				const [state, text] = i.state(d);
				return `<button class="sch-tile ${state}" data-key="${i.key}">
					<span class="sch-logo" style="--c:${i.color}">${i.mark ? `<b>${e(i.mark)}</b>` : icon(i.glyph, 22)}</span>
					<span class="sch-tile-body"><b>${e(i.name)}</b><span class="sch-desc">${e(i.desc)}</span></span>
					<span class="sch-tile-foot"><span class="sch-state ${state}"><i></i>${e(STATE_LABEL[state])}</span>
						<span class="sch-state-text" title="${e(text)}">${e(state === "on" || state === "warn" ? text : "")}</span>
						<span class="sch-go">${state === "on" ? __("Manage") : state === "na" ? __("Details") : __("Set up")} ${icon("arrow", 14)}</span></span>
				</button>`;
			}).join("") || `<div class="sch-empty">${__("No integration matches.")}</div>`);
			this.$root.find(".sch-tile").on("click", (ev) => this.open(ev.currentTarget.dataset.key));
		}

		vendor_strip(v) {
			const done = v.checks.filter((c) => c.ok).length;
			return `<button class="sch-vendor-strip">${icon("shield", 18)}<span><b>${__("System provider setup")}</b>
				${__("{0} of {1} done · only you see this", [done, v.checks.length])}</span>${icon("arrow", 16)}</button>`;
		}

		// ------------------------------------------------------------ panel
		help(p, key, refresh) {
			const box = p.find(".sch-help-box").html(`<div class="sch-help-card"><span class="sch-spin"></span> ${__("Reading your setup…")}</div>`);
			return this.call("guide", { key, refresh: refresh ? 1 : 0 })
				.then((g) => this.render_help(box, g, () => this.help(p, key, true)))
				.catch(() => box.html(`<div class="sch-help-card">${__("The guide is unavailable right now. Use the Reference links below.")}</div>`));
		}

		render_help(box, g, refresh) {
			const title = g.source === "ai" ? __("AI guide") : __("Setup checklist");
			box.html(`<div class="sch-help-card">
				<div class="sch-help-head"><b>${e(title)}</b><span class="sch-muted">${e(g.summary)}</span>
					<span class="sch-help-tools"><button class="btn btn-default btn-xs sch-help-refresh">${__("Refresh")}</button>
					<button class="btn btn-default btn-xs sch-help-close" aria-label="${__("Close")}">×</button></span></div>
				${this.steps(g.steps.map((st) => [st.done, `<b>${e(st.title)}</b> ${e(st.detail)}`]))}
				${(g.watch_out || []).length ? `<div class="sch-note small">${g.watch_out.map((w) => `<div>${e(w)}</div>`).join("")}</div>` : ""}
			</div>`);
			box.find(".sch-help-close").on("click", () => box.empty());
			box.find(".sch-help-refresh").on("click", refresh);
		}

		guides(key) {
			const links = (this.data.references || {})[key];
			if (!links) return "";
			return `<section><h4>${__("Reference")}</h4><div class="sch-guides">${links.map(([label, url]) =>
				`<a class="btn btn-default btn-sm" href="${e(url)}" target="_blank" rel="noopener">${e(label)} ↗</a>`).join("")}</div></section>`;
		}

		open(key) {
			const d = this.data;
			const item = key === "vendor" ? { key, name: __("System provider setup"), glyph: "shield", color: "#334155",
				desc: __("Once for every Company"), state: () => ["on", ""] } : [...INTEGRATIONS, ...PLATFORM_TILES].find((i) => i.key === key);
			if (!item || (item.platform && !this.data.is_vendor)) return;
			this.openKey = key;
			const [state] = item.state(d);
			const panel = this.$root.find(".sch-panel").html(`
				<header><span class="sch-logo" style="--c:${item.color}">${item.mark ? `<b>${e(item.mark)}</b>` : icon(item.glyph, 22)}</span>
					<div class="grow"><h3>${e(item.name)}</h3><div class="sch-desc">${e(item.desc)}</div></div>
					${key === "vendor" ? "" : `<span class="sch-state ${state}"><i></i>${e(STATE_LABEL[state])}</span>`}
					${key === "vendor" ? "" : `<button class="btn btn-default btn-xs sch-help" title="${__("AI guide")}" aria-label="${__("AI guide")}">?</button>`}
					<button class="btn btn-default btn-xs sch-close" aria-label="${__("Close")}">${icon("close", 14)}</button></header>
				<div class="sch-help-box"></div><div class="sch-panel-body">${this.body(key, d)}${this.guides(key)}</div>`);
			this.$root.find(".sch-drawer").addClass("open").attr("aria-hidden", "false");
			panel.find(".sch-close").on("click", () => this.close());
			panel.find(".sch-help").on("click", () => this.help(panel, key, false));
			this.bind(panel, key, d);
		}

		close() {
			this.openKey = null;
			this.$root.find(".sch-drawer").removeClass("open").attr("aria-hidden", "true");
		}

		refresh(d, message) {
			this.render(d);
			if (message) frappe.show_alert({ message, indicator: "green" });
		}

		// Panel pieces ------------------------------------------------
		section(title, html) {
			return `<section><h4>${e(title)}</h4>${html}</section>`;
		}

		steps(list) {
			return `<ol class="sch-steps">${list.map(([done, text]) => `<li class="${done ? "done" : ""}"><i>${done ? "✓" : ""}</i><span>${text}</span></li>`).join("")}</ol>`;
		}

		copy_row(label, url) {
			return `<div class="sch-url"><span>${e(label)}</span><div><code>${e(url)}</code>
				<button class="btn btn-default btn-xs sch-copy-url" data-url="${e(url)}" title="${__("Copy")}">${icon("copy", 13)}</button></div></div>`;
		}

		fields(list, source = this.data.values, scope = "company") {
			const v = source, dis = this.data.can_manage ? "" : "disabled";
			return `<div class="sch-fields">${list.map((f) => {
				const val = v[f.f];
				if (f.type === "check") return `<label class="sch-switch"><input type="checkbox" data-f="${f.f}" ${val ? "checked" : ""} ${dis}><span></span>${e(f.label)}</label>`;
				const help = f.help ? `<small>${e(f.help)}</small>` : "";
				if (f.type === "select") return `<label>${e(f.label)}<select class="form-control" data-f="${f.f}" ${dis}>${f.options.map((o) => `<option ${o === val ? "selected" : ""}>${e(o)}</option>`).join("")}</select>${help}</label>`;
				if (f.type === "secret") return `<label>${e(f.label)}<input class="form-control" type="password" autocomplete="new-password" data-f="${f.f}" placeholder="${val ? __("Saved · type to replace") : ""}" ${dis}>${help}</label>`;
				if (f.type === "textarea") return `<label>${e(f.label)}<textarea class="form-control" rows="3" data-f="${f.f}" ${dis}>${e(val || "")}</textarea>${help}</label>`;
				return `<label>${e(f.label)}<input class="form-control" data-f="${f.f}" value="${e(val || "")}" placeholder="${e(f.placeholder || "")}" ${dis}>${help}</label>`;
			}).join("")}${this.data.can_manage ? `<div class="sch-actions"><button class="btn btn-primary btn-sm sch-save" data-scope="${scope}">${__("Save")}</button></div>` : ""}</div>`;
		}

		accounts(platforms, messaging) {
			const rows = this.data.accounts.filter((a) => platforms.includes(a.platform));
			if (!rows.length) return `<div class="sch-muted">${__("Nothing connected yet.")}</div>`;
			const dis = this.data.can_manage ? "" : "disabled";
			return `<div class="sch-accounts">${rows.map((a) => `<div class="sch-account ${a.last_error ? "bad" : ""}" data-name="${e(a.name)}">
				<div class="grow"><b>${e(a.account_name)}</b>
					<div class="sch-muted">${a.last_error ? e(a.last_error) : e(a.last_check || "")}${a.token_expires_on ? " · " + __("access ends {0}", [e(frappe.datetime.str_to_user(a.token_expires_on))]) : ""}</div></div>
				${messaging ? `<label class="sch-switch small"><input type="checkbox" class="sch-msg" ${a.receive_messages ? "checked" : ""} ${dis}><span></span>${__("Messages")}</label>` : ""}
				<label class="sch-switch small"><input type="checkbox" class="sch-on" ${a.enabled ? "checked" : ""} ${dis}><span></span>${__("On")}</label>
				${this.data.can_manage ? `<button class="btn btn-default btn-xs sch-test">${__("Test")}</button>` : ""}</div>`).join("")}</div>`;
		}

		connect_button(provider, label, ready) {
			if (!ready) return `<div class="sch-note small">${__("Your system provider has not set up this app yet.")}</div>`;
			return this.data.can_manage ? `<button class="btn btn-primary btn-sm sch-connect" data-provider="${provider}">${e(label)}</button>` : "";
		}

		body(key, d) {
			const t = d.twilio;
			switch (key) {
			case "vendor":
				return this.section(__("Checklist"), this.steps(d.vendor.checks.map((c) => [c.ok, e(c.label)])))
					+ this.section(__("Addresses for the Meta and LinkedIn apps"), this.copy_row(__("OAuth redirect URI (Meta and LinkedIn)"), d.vendor.redirect_uri)
						+ this.copy_row(__("Webhook callback URL (Meta: Page and Instagram)"), d.vendor.meta_webhook)
						+ `<button class="btn btn-default btn-sm sch-token">${__("Make a new webhook verify token")}</button>`)
					+ `<a class="btn btn-default btn-sm" href="/desk/sales-agent-platform-settings">${__("Open platform settings")}</a>`;
			case "autopilot":
				return this.section(__("AI autopilot"), `<div class="sch-fields">
						<label class="sch-switch"><input type="checkbox" class="sch-auto" ${d.fast.auto_answer ? "checked" : ""}><span></span>${__("Answer simple chat questions at once")}</label>
						<small class="sch-muted">${__("Only facts from your approved knowledge. Prices it cannot find, discounts, complaints and anything unsure go to a person.")}</small>
						<label class="sch-switch"><input type="checkbox" class="sch-wa" ${d.fast.whatsapp ? "checked" : ""}><span></span>${__("Also answer WhatsApp (inside the 24-hour window)")}</label>
						<label class="sch-switch"><input type="checkbox" class="sch-comments" ${d.fast.comment_to_chat ? "checked" : ""}><span></span>${__("Answer buying comments on our posts with one private message")}</label></div>`)
					+ this.section(__("Your team"), `<div class="sch-fields">
						<label>${__("Sales team (one email per line)")}<textarea class="form-control sch-agents" rows="3" placeholder="sales1@yourcompany.com">${e(d.fast.agents)}</textarea>
							<small>${__("They answer conversations; each lead keeps one owner across its calls, follow-ups and chats.")}</small></label>
						<label>${__("Calls and follow-ups go to")}<select class="form-control sch-routing">${["One salesperson", "Share across the team"].map((o) => `<option ${o === d.fast.call_routing ? "selected" : ""} value="${e(o)}">${e(o === "One salesperson" ? __("One salesperson (named in Get started)") : __("Share across the sales team (least busy first)"))}</option>`).join("")}</select></label>
						<label class="sch-switch"><input type="checkbox" class="sch-assign" ${d.fast.auto_assign ? "checked" : ""}><span></span>${__("Share new conversations automatically (fewest open first)")}</label>
						<label>${__("Remind {0} when a chat waits longer than (minutes, 0 = off)", [e(d.fast.assignee || __("the salesperson"))])}<input type="number" class="form-control sch-sla" min="0" max="1440" value="${e(d.fast.sla_minutes)}"></label>
						${d.can_manage ? `<div class="sch-actions"><button class="btn btn-primary btn-sm sch-fast-save">${__("Save")}</button></div>` : ""}</div>`);
			case "platform_ai":
				return d.platform ? this.section(__("Default AI"), this.fields([
					{ f: "ai_enabled", type: "check", label: __("AI is on for every customer") },
					{ f: "ai_provider", type: "select", label: __("Provider"), options: ["Anthropic (Claude)", "OpenAI", "Local (OpenAI-compatible)"] },
					{ f: "ai_model", label: __("Claude model") },
					{ f: "ai_effort", type: "select", label: __("Effort"), options: ["low", "medium", "high"] },
					{ f: "anthropic_api_key", type: "secret", label: __("Anthropic API key") },
					{ f: "openai_api_key", type: "secret", label: __("OpenAI API key") },
					{ f: "openai_model", label: __("OpenAI model") },
					{ f: "openai_base_url", label: __("OpenAI API address") },
					{ f: "local_ai_base_url", label: __("Local AI server address"), placeholder: "http://127.0.0.1:11434/v1" },
					{ f: "local_ai_model", label: __("Local model") },
					{ f: "local_ai_api_key", type: "secret", label: __("Local AI key") },
				], d.platform, "platform"))
					+ this.section(__("Customers"), this.fields([
					{ f: "allow_company_ai_override", type: "check", label: __("Customers may use the AI set for their Company") },
					{ f: "allow_company_ai_endpoints", type: "check", label: __("Customers may use their own AI server address (HTTPS)") },
				], d.platform, "platform")) : "";
			case "platform_meta":
				return d.platform ? this.section(__("Meta app"), this.fields([
					{ f: "meta_app_id", label: __("App ID") },
					{ f: "meta_app_secret", type: "secret", label: __("App secret"), help: __("Also checks every webhook's signature.") },
					{ f: "meta_verify_token", type: "secret", label: __("Webhook verify token"), help: __("Paste the same text in the Meta app's webhook settings.") },
				], d.platform, "platform"))
					+ this.section(__("Addresses for the Meta app"), this.copy_row(__("OAuth redirect URI"), d.vendor.redirect_uri)
						+ this.copy_row(__("Webhook callback URL"), d.vendor.meta_webhook)
						+ `<button class="btn btn-default btn-sm sch-token">${__("Make a new verify token")}</button>`) : "";
			case "platform_linkedin":
				return d.platform ? this.section(__("LinkedIn app"), this.fields([
					{ f: "linkedin_client_id", label: __("Client ID") },
					{ f: "linkedin_client_secret", type: "secret", label: __("Client secret") },
				], d.platform, "platform"))
					+ this.section(__("Address for the LinkedIn app"), this.copy_row(__("OAuth redirect URI"), d.vendor.redirect_uri)) : "";
			case "platform_transcription":
				return d.platform ? this.section(__("Recorded calls"), this.fields([
					{ f: "transcription_enabled", type: "check", label: __("Transcribe recorded calls") },
					{ f: "transcription_provider", type: "select", label: __("Speech-to-text service"), options: ["OpenAI", "Local (OpenAI-compatible)"] },
					{ f: "transcription_model", label: __("Model"), placeholder: "whisper-1" },
				], d.platform, "platform"))
					+ `<div class="sch-note small">${__("Customers' own recordings are transcribed with this service. Callers must hear a recording notice.")}</div>` : "";
			case "platform_lead_sources":
				return d.platform ? this.section(__("Brave Search"), this.fields([
					{ f: "brave_enabled", type: "check", label: __("Use Brave Search (web, places, page context)") },
					{ f: "brave_api_key", type: "secret", label: __("Brave API key") },
					{ f: "brave_country", label: __("Country (optional)"), placeholder: "BD" },
				], d.platform, "platform"))
					+ this.section(__("Google Places API"), this.fields([
					{ f: "places_enabled", type: "check", label: __("Use Google Places") },
					{ f: "google_places_api_key", type: "secret", label: __("Google Places API key") },
					{ f: "places_terms_reviewed", type: "check", label: __("Google Maps Platform terms reviewed"), help: __("Turn on only after your team has read Google's terms.") },
					{ f: "places_retention_days", label: __("Keep Places data (days)") },
				], d.platform, "platform"))
					+ this.section(__("Google Maps providers"), this.fields([
					{ f: "maps_terms_ack", type: "check", label: __("Accept responsibility for Google Maps data use"), help: __("Google's terms restrict scraping Google Maps.") },
					{ f: "maps_data_retention_days", label: __("Keep Maps data (days)") },
					{ f: "serpapi_enabled", type: "check", label: __("Use SerpAPI (Maps)") },
					{ f: "serpapi_api_key", type: "secret", label: __("SerpAPI key") },
					{ f: "apify_enabled", type: "check", label: __("Use Apify (Maps scraper)") },
					{ f: "apify_api_token", type: "secret", label: __("Apify API token") },
					{ f: "apify_actor", label: __("Apify actor") },
					{ f: "scrapingdog_enabled", type: "check", label: __("Use Scrapingdog (Maps)") },
					{ f: "scrapingdog_api_key", type: "secret", label: __("Scrapingdog key") },
					{ f: "scrapingbee_enabled", type: "check", label: __("Use ScrapingBee (Maps)") },
					{ f: "scrapingbee_api_key", type: "secret", label: __("ScrapingBee key") },
				], d.platform, "platform"))
					+ this.section(__("Google Search providers"), this.fields([
					{ f: "search_terms_ack", type: "check", label: __("Accept responsibility for Google Search data use") },
					{ f: "search_data_retention_days", label: __("Keep Search data (days)") },
					{ f: "search_country", label: __("Country (gl)") },
					{ f: "search_language", label: __("Language (hl)") },
					{ f: "search_serpapi_enabled", type: "check", label: __("Use SerpAPI (Search), with the SerpAPI key above") },
					{ f: "search_scrapingdog_enabled", type: "check", label: __("Use Scrapingdog (Search), with its key above") },
					{ f: "search_scrapingbee_enabled", type: "check", label: __("Use ScrapingBee (Search), with its key above") },
				], d.platform, "platform"))
					+ this.section(__("Routing"), this.fields([
					{ f: "default_places_provider", type: "select", label: __("Default places provider"), options: ["brave_place_search", "google_places_api", "scrapingdog_google_maps", "scrapingbee_google_maps", "serpapi_google_maps", "apify_google_maps"] },
					{ f: "default_page_context_provider", type: "select", label: __("Default page context provider"), options: ["brave_llm_context"] },
					{ f: "default_web_search_provider", type: "select", label: __("Default web search provider"), options: ["brave_web_search", "scrapingdog_google_search", "scrapingbee_google_search", "serpapi_google_search"] },
				], d.platform, "platform"))
					+ `<div class="sch-note small">${__("Brave is the default. Every other provider switched on joins Smart Sources.")}</div>` : "";
			case "platform_research":
				return d.platform ? this.section(__("Website research"), this.fields([
					{ f: "research_enabled", type: "check", label: __("Read lead websites") },
					{ f: "user_agent", label: __("Crawler user agent") },
					{ f: "fetch_timeout", label: __("Fetch timeout (seconds)") },
					{ f: "max_page_kb", label: __("Max page size (KB)") },
					{ f: "max_pages_per_site", label: __("Max pages per website") },
					{ f: "market_research_max_requests", label: __("Requests per market brief") },
				], d.platform, "platform"))
					+ `<div class="sch-note small">${__("Robots.txt is always respected; private network addresses are always refused.")}</div>` : "";
			case "platform_social":
				return d.platform ? this.section(__("Social publishing"), this.fields([
					{ f: "social_enabled", type: "check", label: __("Publish approved posts") },
					{ f: "meta_graph_version", label: __("Meta Graph API version"), placeholder: "v23.0" },
					{ f: "linkedin_api_version", label: __("LinkedIn API version (YYYYMM)"), placeholder: "202509" },
				], d.platform, "platform")) : "";
			case "platform_email_events":
				return d.platform ? this.section(__("Signing"), this.fields([
					{ f: "email_webhook_secret", type: "secret", label: __("Webhook signing secret"), help: __("Your email provider signs each event with this secret.") },
				], d.platform, "platform"))
					+ this.section(__("Address to paste into your email provider"), this.copy_row(__("Email events"), d.webchat.site + "/api/method/reckon_sales_agent.api.email_events")) : "";
			case "platform_plans":
				return d.platform ? this.section(__("Monthly limits per Company"), this.fields([
					{ f: "monthly_discovery_limit", label: __("Discovery") },
					{ f: "monthly_research_limit", label: __("Website research") },
					{ f: "monthly_ai_limit", label: __("AI requests") },
					{ f: "monthly_message_limit", label: __("Messages") },
				], d.platform, "platform")) + this.section(__("Internal companies"), this.fields([
					{ f: "internal_companies", type: "textarea", label: __("Companies with no subscription needed"), help: __("One per line.") },
				], d.platform, "platform")) : "";
			case "platform_experimental":
				return d.platform ? `<div class="sch-note">${__("These drive a headless browser on Google's pages. They break when Google changes its pages and may breach its terms. Leave them off unless you have reviewed the risk.")}</div>`
					+ this.section(__("Google Maps browser"), this.fields([
					{ f: "maps_browser_enabled", type: "check", label: __("Enable the Maps browser") },
					{ f: "maps_browser_max_results", label: __("Max places per search") },
					{ f: "maps_browser_delay", label: __("Delay between places (seconds)") },
					{ f: "maps_browser_language", label: __("Language (hl)") },
				], d.platform, "platform"))
					+ this.section(__("Google Search browser"), this.fields([
					{ f: "search_browser_enabled", type: "check", label: __("Enable the Search browser") },
					{ f: "search_browser_max_results", label: __("Max results per search") },
					{ f: "search_browser_delay", label: __("Delay between result pages (seconds)") },
				], d.platform, "platform")) : "";
			case "ai":
				return this.section(__("Current AI"), `<div class="sch-kv"><span>${__("Provider")}</span><b>${e(d.ai.label)}</b><span>${__("Model")}</span><b>${e(d.ai.model || "–")}</b>
						<span>${__("Status")}</span><b>${d.ai.error ? e(d.ai.error) : d.ai.on ? __("On") : __("Off")}</b></div>`)
					+ `<div class="sch-note small">${__("The AI provider and model are managed by your system provider (Claude, OpenAI or a local model).")}</div>`;
			case "webchat":
				return this.section(__("Settings"), `<div class="sch-fields">
						<label class="sch-switch"><input type="checkbox" class="sch-wc-on" ${d.webchat.enabled ? "checked" : ""}><span></span>${__("Show the chat on our website")}</label>
						<label>${__("Title")}<input class="form-control sch-wc-title" maxlength="80" value="${e(d.webchat.title)}"></label>
						<label>${__("Welcome message")}<textarea class="form-control sch-wc-welcome" rows="2" maxlength="500">${e(d.webchat.welcome)}</textarea></label>
						<label>${__("Your websites (one per line; empty allows any)")}<textarea class="form-control sch-wc-origins" rows="2" placeholder="https://www.example.com">${e(d.webchat.origins)}</textarea></label>
						${d.can_manage ? `<div class="sch-actions"><button class="btn btn-primary btn-sm sch-wc-save">${__("Save")}</button></div>` : ""}</div>`)
					+ (d.webchat.enabled && d.webchat.key ? this.section(__("Install on your website"), `<p class="sch-muted">${__("Paste before </body> on every page:")}</p>
						${this.copy_row(__("Script tag"), `<script src="${d.webchat.script}" data-site="${d.webchat.site}" data-key="${d.webchat.key}" defer><\/script>`)}`) : "");
			case "whatsapp":
				if (!d.whatsapp.installed) return `<div class="sch-note small">${__("Install the Frappe WhatsApp app (frappe_whatsapp) on this site to use WhatsApp.")}</div>`;
				return this.section(__("Account"), this.fields([
					{ f: "whatsapp_enabled", type: "check", label: __("Send and receive WhatsApp messages") },
					{ f: "whatsapp_account", type: "select", label: __("WhatsApp account"), options: ["", ...d.whatsapp.accounts.map((a) => a.name)] },
				]))
					+ this.section(__("Accounts available to you"), d.whatsapp.accounts.length
						? d.whatsapp.accounts.map((a) => `<div class="sch-kv"><span>${e(a.account_name || a.name)}</span><b>${e(a.status || "")}</b></div>`).join("")
						: `<div class="sch-muted">${__("No WhatsApp account is free for this Company. Add one in the WhatsApp Account list, with its phone number ID and token.")}</div>`)
					+ this.section(__("Paste into Meta: WhatsApp, Configuration"), this.copy_row(__("Webhook callback URL"), d.whatsapp.webhook)
						+ `<div class="sch-note small">${__("Subscribe to messages and message_template_status_update. The verify token is on the WhatsApp Account (Webhook Verify Token).")}</div>`)
					+ this.section(__("Setup guide"), this.steps([
						[false, __("In Meta Developers, create a Business app with the WhatsApp product, and get a permanent token, the Phone ID and the Business ID.")],
						[false, __("Create a WhatsApp Account in the WhatsApp Account list: Account Name, Token, Phone ID, Business ID, App ID, Webhook Verify Token (any long random text), URL https://graph.facebook.com and Version v17.0.")],
						[false, __("Choose it above and save. Tick Is Default Outgoing only if it is your only account; this setting takes priority over the default.")],
						[false, __("Paste the callback address above into Meta, with the verify token, and subscribe to messages and message_template_status_update.")],
						[false, __("Serve the site over HTTPS, in production mode: Meta refuses webhooks otherwise.")],
					]))
					+ `<div class="sch-note small">${__("After a customer writes, you can reply freely for 24 hours; after that only an approved template can be sent.")}</div>`;
			case "facebook":
			case "instagram":
				return this.section(__("Connect"), this.steps([[d.meta_ready, __("Your system provider set up the Meta app")],
						[d.accounts.some((a) => a.platform === (key === "facebook" ? "Facebook Page" : "Instagram")), __("Sign in with Facebook and choose your Pages")],
						[false, __("Optional: turn on comment-to-chat in AI autopilot & team")]])
						+ this.connect_button("meta", __("Connect with Facebook"), d.meta_ready))
					+ this.section(__("Connected accounts"), this.accounts(key === "facebook" ? ["Facebook Page"] : ["Instagram"], true))
					+ `<div class="sch-muted">${__("Messages so far: Messenger {0} · Instagram {1}", [d.counts.Messenger, d.counts.Instagram])}</div>`;
			case "meta_leads":
				return this.section(__("How it works"), this.steps([[d.accounts.some((a) => a.platform === "Facebook Page"), __("Connect your Facebook Pages (Facebook & Messenger)")],
						[false, __("New lead form answers arrive within seconds as approved leads, with a call task due now and an AI first reply to approve")],
						[false, __("Frappe CRM's own Lead Syncing keeps working; the same lead is linked, never duplicated")]]))
					+ this.connect_button("meta", __("Connect with Facebook"), d.meta_ready);
			case "linkedin":
				return this.section(__("Connect"), this.connect_button("linkedin", __("Connect with LinkedIn"), d.linkedin_ready))
					+ this.section(__("Connected pages"), this.accounts(["LinkedIn"], false));
			case "linkedin_leads":
				return this.section(__("Connect"), this.steps([[d.linkedin_ready, __("Your system provider set up the LinkedIn app")],
						[false, __("LinkedIn approved your Lead Sync API access")],
						[d.accounts.some((a) => a.platform === "LinkedIn Lead Gen"), __("Connect your lead forms")]])
						+ this.connect_button("linkedin_leads", __("Connect lead forms"), d.linkedin_ready))
					+ this.section(__("Connected"), this.accounts(["LinkedIn Lead Gen"], false));
			case "twilio":
				return this.section(__("Account"), this.fields([
						{ f: "twilio_account_sid", label: __("Account SID"), placeholder: "AC…" },
						{ f: "twilio_auth_token", type: "secret", label: __("Auth token"), help: __("Also verifies every webhook from Twilio.") },
						{ f: "twilio_phone_number", label: __("Twilio phone number"), placeholder: "+15551234567" },
						{ f: "twilio_messaging_service_sid", label: __("Messaging Service SID (for RCS)"), placeholder: "MG…", help: __("RCS where the phone supports it, SMS otherwise.") }]))
					+ this.section(__("Use Twilio for"), this.fields([
						{ f: "telephony_provider", type: "select", label: __("Calls go through"), options: ["Phone (tap to call)", "Asterisk (SIP)", "Twilio"] },
						{ f: "twilio_record_calls", type: "check", label: __("Record calls (transcribed and summarised; tell callers)") },
						{ f: "sms_provider", type: "select", label: __("SMS provider"), options: ["Platform gateway", "BulkSMSBD", "SSL Wireless", "Twilio (SMS and RCS)"] },
						{ f: "sms_enabled", type: "check", label: __("Send SMS") }]))
					+ (t.ready ? this.section(__("Paste into Twilio"), this.copy_row(__("Phone number → A call comes in"), t.urls.voice)
						+ this.copy_row(__("Phone number or Messaging Service → A message comes in"), t.urls.sms)) : "");
			case "voice_ai":
				return (t.ready ? "" : `<div class="sch-note small">${__("Connect Twilio first.")}</div>`)
					+ this.section(__("Assistant"), this.fields([
						{ f: "voice_ai_enabled", type: "check", label: __("Answer incoming calls with the AI assistant") },
						{ f: "voice_ai_greeting", type: "textarea", label: __("Greeting"), help: __("It always says it is an AI assistant.") },
						{ f: "voice_ai_language", label: __("Speech language"), placeholder: "en-US / bn-BD" },
						{ f: "voice_forward_to", label: __("Connect callers to (phone)"), help: __("When they ask for a person, or the answer is not in your approved facts.") }]))
					+ (t.ready ? this.section(__("Paste into Twilio"), this.copy_row(__("Phone number → A call comes in"), t.urls.voice)) : "");
			case "sms":
				return this.section(__("Gateway"), this.fields([
						{ f: "sms_enabled", type: "check", label: __("Send SMS (only to leads with SMS consent)") },
						{ f: "sms_provider", type: "select", label: __("Provider"), options: ["Platform gateway", "BulkSMSBD", "SSL Wireless", "Twilio (SMS and RCS)"] },
						{ f: "sms_api_key", type: "secret", label: __("API key / token"), help: __("BulkSMSBD API key or SSL Wireless API token.") },
						{ f: "sms_account", label: __("SSL Wireless SID") },
						{ f: "sms_sender_id", label: __("Sender ID / number"), placeholder: "8809617000000" }]))
					+ `<div class="sch-note small">${__("A lead who texts STOP (or বন্ধ) is never texted again. Replies by SMS arrive through Twilio.")}</div>`;
			case "asterisk":
				return this.section(__("Phone system"), this.fields([
						{ f: "telephony_provider", type: "select", label: __("Calls go through"), options: ["Phone (tap to call)", "Asterisk (SIP)", "Twilio"] },
						{ f: "ari_url", label: __("Asterisk ARI address (HTTPS)"), placeholder: "https://pbx.example.com:8089" },
						{ f: "ari_username", label: __("ARI user") }, { f: "ari_password", type: "secret", label: __("ARI password") },
						{ f: "sip_context", label: __("Dial plan context"), placeholder: "from-internal" },
						{ f: "sip_caller_id", label: __("Caller ID (your 09-series number)") },
						{ f: "telephony_webhook_secret", type: "secret", label: __("Call-events secret") },
						{ f: "calling_hours", label: __("Calling hours (Bangladesh time)"), placeholder: "09:00-20:00" }]));
			case "email":
				return this.section(__("Sending"), this.fields([{ f: "email_provider", type: "select", label: __("Send email through"), options: ["Frappe email account", "Twilio SendGrid"] }]))
					+ (d.email.account ? `<div class="sch-muted">${__("Outgoing account: {0}", [e(d.email.account)])}</div>` : `<div class="sch-note small">${__("Add an outgoing Email Account in Frappe, or use Twilio SendGrid.")}</div>`)
					+ `<a class="btn btn-default btn-sm" href="/desk/sales-templates">${__("Check email health (SPF, DKIM, DMARC)")}</a>`;
			case "sendgrid":
				return this.section(__("Account"), this.fields([
						{ f: "email_provider", type: "select", label: __("Send email through"), options: ["Frappe email account", "Twilio SendGrid"] },
						{ f: "sendgrid_api_key", type: "secret", label: __("API key") },
						{ f: "sendgrid_from_email", label: __("From address (verified in SendGrid)") },
						{ f: "sendgrid_webhook_key", type: "textarea", label: __("Signed Event Webhook public key"), help: __("Bounces and spam reports then reach your do-not-contact list.") }]))
					+ this.section(__("Paste into SendGrid"), this.copy_row(__("Mail Settings → Event Webhook → HTTP POST URL"), t.urls.sendgrid_events));
			default:
				return "";
			}
		}

		bind(p, key, d) {
			p.find(".sch-copy-url").on("click", (ev) => frappe.utils.copy_to_clipboard(ev.currentTarget.dataset.url));
			p.find(".sch-connect").on("click", (ev) => {
				$(ev.currentTarget).prop("disabled", true);
				this.call("social_connect", { provider: ev.currentTarget.dataset.provider })
					.then((url) => (window.location.href = url)).catch(() => $(ev.currentTarget).prop("disabled", false));
			});
			const account = (ev) => $(ev.currentTarget).closest(".sch-account").data("name");
			p.find(".sch-on").on("change", (ev) => this.call("set_account", { account: account(ev), enabled: ev.currentTarget.checked ? 1 : 0 }).then((r) => this.refresh(r)));
			p.find(".sch-msg").on("change", (ev) => this.call("set_account", { account: account(ev), receive_messages: ev.currentTarget.checked ? 1 : 0 }).then((r) => this.refresh(r)));
			p.find(".sch-test").on("click", (ev) => this.call("check_account", { account: account(ev) }).then((r) => this.refresh(r, __("Checked"))));
			p.find(".sch-save").on("click", (ev) => {
				const data = {};
				p.find("[data-f]").each((_, el) => { data[el.dataset.f] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value; });
				$(ev.currentTarget).prop("disabled", true);
				this.call($(ev.currentTarget).data("scope") === "platform" ? "save_platform_settings" : "save_settings", { data: JSON.stringify(data) }).then((r) => this.refresh(r, __("Saved")))
					.finally(() => $(ev.currentTarget).prop("disabled", false));
			});
			p.find(".sch-wc-save").on("click", () => this.call("set_webchat", { data: JSON.stringify({
				enabled: p.find(".sch-wc-on").is(":checked") ? 1 : 0, title: p.find(".sch-wc-title").val(),
				welcome: p.find(".sch-wc-welcome").val(), origins: p.find(".sch-wc-origins").val(),
			}) }).then((r) => this.refresh(r, __("Website chat saved"))));
			p.find(".sch-fast-save").on("click", () => this.call("set_fast_answers", { data: JSON.stringify({
				auto_answer: p.find(".sch-auto").is(":checked") ? 1 : 0, comment_to_chat: p.find(".sch-comments").is(":checked") ? 1 : 0,
				sla_minutes: Number(p.find(".sch-sla").val() || 0), whatsapp: p.find(".sch-wa").is(":checked") ? 1 : 0,
				agents: p.find(".sch-agents").val(), auto_assign: p.find(".sch-assign").is(":checked") ? 1 : 0,
				call_routing: p.find(".sch-routing").val(),
			}) }).then((r) => this.refresh(r, __("Saved"))));
			p.find(".sch-token").on("click", () => frappe.confirm(__("Make a new verify token? The old one stops working in the Meta app."),
				() => this.call("new_verify_token").then((token) => frappe.msgprint({ title: __("Paste this into the Meta app's webhook settings"),
					message: `<pre class="sch-code">${e(token)}</pre><p>${__("It is shown only once.")}</p>` }))));
			if (!d.can_manage) p.find("input, select, textarea").not(".sch-copy-url").prop("disabled", true);
		}
	}
})();
