// Conversations: every lead's thread across email, WhatsApp, SMS, Messenger, Instagram, website chat, calls and
// forms. Each conversation has an owner, a status, tags and an AI mode; people reply here themselves or approve
// the AI's drafts. Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-inbox"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Conversations"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		page.add_inner_button(__("Integrations"), () => frappe.set_route("sales-channels"));
		wrapper.inbox = new Inbox(page);
	};
	frappe.pages["sales-inbox"].on_page_show = (wrapper) => wrapper.inbox && wrapper.inbox.start();
	frappe.pages["sales-inbox"].on_page_hide = (wrapper) => wrapper.inbox && wrapper.inbox.stop();

	const API = "reckon_sales_agent.api_conversations.";
	const POLL_MS = 15000;
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const when = (v) => (v ? frappe.datetime.prettyDate(v) : "");
	const SOURCES = { meta_lead_ads: __("Meta lead form"), messenger: __("Messenger"), instagram: __("Instagram"),
		web_chat: __("Website chat"), sms: __("SMS"), voice: __("Phone call"), linkedin_lead_gen: __("LinkedIn lead form") };
	const CHANNELS = { "Web Chat": __("Website chat") };
	const MODES = [["Company default", __("Company default")], ["Autopilot", __("AI autopilot")],
		["Suggest only", __("AI suggests, we send")], ["Human only", __("Human only")]];
	const FILTERS = [["waiting", __("Waiting")], ["mine", __("Mine")], ["unassigned", __("Unassigned")],
		["needs", __("Needs a person")], ["open", __("Open")], ["resolved", __("Resolved")]];

	class Inbox {
		constructor(page) {
			this.page = page;
			this.filter = "waiting";
			this.search = "";
			this.$root = $(`<div class="sin"><aside class="sin-list"></aside><section class="sin-thread"></section></div>`).appendTo(page.main);
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		start() {
			this.load();
			this.stop();
			// New messages appear without reloading; a reply being typed is never redrawn.
			this.timer = setInterval(() => !document.hidden && this.load(true), POLL_MS);
		}

		stop() {
			clearInterval(this.timer);
		}

		load(quiet) {
			return this.call("threads").then((rows) => {
				this.rows = rows;
				if (!this.current && rows.length) this.current = (rows.find((r) => r.needs_reply) || rows[0]).prospect;
				this.render_list();
				// Never redraw the thread under someone typing a reply or a tag, or using a menu.
				const busy = this.$root.find(".sin-text").val() || $.contains(this.$root.find(".sin-thread")[0], document.activeElement);
				if (this.current && !(quiet && busy)) this.open(this.current);
				else if (!this.current) this.$root.find(".sin-thread").html(`<div class="sin-empty">${__("No conversations yet. Replies, chats, texts, calls and lead forms appear here.")}</div>`);
			});
		}

		matches(r, filter) {
			const c = r.conversation || {};
			const me = frappe.session.user;
			const open = (c.status || "Open") !== "Resolved";
			const ok = {
				waiting: r.needs_reply && open, mine: c.assigned_to === me && open, unassigned: !c.assigned_to && open,
				needs: (c.tags || []).includes("needs-human") && open, open, resolved: !open,
			}[filter || this.filter];
			const q = this.search.toLowerCase();
			return ok && (!q || `${r.business || ""} ${r.email || ""} ${r.phone || ""} ${(c.tags || []).join(" ")}`.toLowerCase().includes(q));
		}

		render_list() {
			const rows = this.rows.filter((r) => this.matches(r));
			const list = this.$root.find(".sin-list");
			const searching = list.find(".sin-search").is(":focus");
			list.html(`
				<input class="form-control sin-search" placeholder="${__("Search name, phone, tag")}" value="${e(this.search)}">
				<div class="sin-tabs">${FILTERS.map(([k, l]) => `<button data-f="${k}" class="${this.filter === k ? "on" : ""}">${e(l)} <b>${this.rows.filter((r) => this.matches(r, k)).length}</b></button>`).join("")}</div>
				${rows.map((r) => {
					const c = r.conversation || {};
					return `<button class="sin-item ${r.prospect === this.current ? "on" : ""}" data-p="${e(r.prospect)}">
					<div class="top"><b>${e(r.business || r.prospect)}</b><span>${e(when(r.last))}</span></div>
					<div class="meta">${r.needs_reply ? `<span class="sin-badge warn">${__("They spoke last")}</span>` : ""}
						${r.draft_waiting ? `<span class="sin-badge">${__("Draft ready")}</span>` : ""}
						${r.chat ? `<span class="sin-badge src">${e(CHANNELS[r.chat] || __(r.chat))}</span>` : SOURCES[r.source] ? `<span class="sin-badge src">${e(SOURCES[r.source])}</span>` : ""}
						${c.assigned_to ? `<span class="sin-badge src" title="${e(c.assigned_to)}">${e(frappe.user.full_name(c.assigned_to) || c.assigned_to)}</span>` : ""}
						${(c.tags || []).map((t) => `<span class="sin-badge ${t === "needs-human" ? "warn" : "tag"}">#${e(t)}</span>`).join("")}</div></button>`;
				}).join("") || `<div class="sin-empty small">${__("Nothing here.")}</div>`}`);
			if (searching) list.find(".sin-search").trigger("focus").get(0).setSelectionRange(this.search.length, this.search.length);
			list.find(".sin-search").on("input", frappe.utils.debounce((ev) => { this.search = ev.target.value; this.render_list(); }, 250));
			list.find(".sin-tabs button").on("click", (ev) => { this.filter = ev.currentTarget.dataset.f; this.render_list(); });
			list.find(".sin-item").on("click", (ev) => { this.current = ev.currentTarget.dataset.p; this.render_list(); this.open(this.current); });
		}

		open(prospect) {
			const el = this.$root.find(".sin-thread");
			if (this.shown !== prospect) el.html(`<div class="sin-empty">${__("Loading…")}</div>`);
			return this.call("thread", { prospect }).then((t) => { this.shown = prospect; this.render_thread(el, prospect, t); });
		}

		render_thread(el, prospect, t) {
			const p = t.prospect, c = t.conversation;
			const ok = t.channels.filter((ch) => ch.ok);
			const resolved = c.status === "Resolved";
			el.html(`<div class="sin-head"><div><h3>${e(p.business_name)}</h3>
					<div class="sin-muted">${[p.email ? e(p.email) : "", p.phone ? `<a href="tel:${e(p.phone)}">${e(p.phone)}</a>` : "", e(p.city || "")]
						.filter(Boolean).join(" · ")}${p.consent_source ? ` · ${__("consent")}: ${e(p.consent_source)}` : ""}</div></div>
					<div class="sin-links"><a class="btn btn-xs btn-default" href="/desk/sales-prospect/${encodeURIComponent(p.name)}">${__("Lead")}</a>
					${p.crm_lead ? `<a class="btn btn-xs btn-default" href="/crm/leads/${encodeURIComponent(p.crm_lead)}">${__("CRM")}</a>` : ""}
					<button class="btn btn-xs ${resolved ? "btn-default" : "btn-primary"} sin-status">${resolved ? __("Reopen") : __("Resolve")}</button></div></div>
				<div class="sin-bar">
					<label>${__("Owner")} <select class="form-control input-xs sin-assign"><option value="">${__("Nobody")}</option>
						${t.agents.map((a) => `<option value="${e(a.user)}" ${a.user === c.assigned_to ? "selected" : ""}>${e(a.name)}${a.user === t.me ? " (" + __("me") + ")" : ""}</option>`).join("")}</select></label>
					<label>${__("AI")} <select class="form-control input-xs sin-mode">${MODES.map(([k, l]) => `<option value="${e(k)}" ${k === c.ai_mode ? "selected" : ""}>${e(l)}</option>`).join("")}</select></label>
					<span class="sin-muted">${c.ai_mode === "Company default" ? __("now: {0}", [e(__(c.effective))]) : ""}</span>
					<div class="sin-tags">${(c.tags || []).map((tg) => `<span class="sin-badge ${tg === "needs-human" ? "warn" : "tag"}">#${e(tg)}
						<a class="sin-untag" data-t="${e(tg)}" title="${__("Remove")}">×</a></span>`).join("")}
						<input class="sin-tag-in" placeholder="${__("+ tag")}" maxlength="40"></div></div>
				${c.handoff_reason && !resolved ? `<div class="sin-warn">${__("Needs a person")}: ${e(c.handoff_reason)}</div>` : ""}
				<div class="sin-timeline">${t.timeline.map((i) => `<div class="sin-msg ${e(i.direction)}">
					<div class="sin-muted">${e(CHANNELS[i.channel] || i.channel)} · ${e(__(i.status))} · ${e(when(i.at))}</div>
					${i.subject ? `<b>${e(i.subject)}</b>` : ""}<div class="txt">${e(i.text)}</div></div>`).join("")
					|| `<div class="sin-empty small">${__("No messages yet.")}</div>`}</div>
				<div class="sin-drafts">${t.drafts.map((d) => `<div class="sin-draft" data-m="${e(d.name)}">
					<div class="sin-muted">${__("AI draft")} · ${e(CHANNELS[d.channel] || d.channel)} → ${e(d.recipient || "")}</div>
					${d.subject ? `<b>${e(d.subject)}</b>` : ""}<div class="txt">${e($("<div>").html(d.body).text())}</div>
					${d.error ? `<div class="sin-warn">${e(d.error)}</div>` : ""}
					<div class="sin-actions"><button class="btn btn-xs btn-default sin-use">${__("Edit before sending")}</button>
						<button class="btn btn-xs btn-default sin-discard">${__("Discard")}</button>
						<button class="btn btn-xs btn-primary sin-send">${__("Approve and send")}</button></div></div>`).join("")}</div>
				${p.do_not_contact ? `<div class="sin-warn">${__("This lead asked not to be contacted.")}</div>` : `<div class="sin-reply">
					${ok.length ? `<div class="sin-reply-row"><select class="form-control input-sm sin-channel">${ok.map((ch) => `<option value="${e(ch.channel)}">${e(CHANNELS[ch.channel] || __(ch.channel))}</option>`).join("")}</select>
						<span class="sin-muted">${e(t.channels.filter((ch) => !ch.ok).map((ch) => `${CHANNELS[ch.channel] || ch.channel}: ${ch.reason}`).join(" · "))}</span></div>
						<textarea class="form-control sin-text" rows="3" placeholder="${__("Write your reply… (Ctrl+Enter to send)")}"></textarea>
						<div class="sin-actions"><input class="form-control input-sm sin-instr" placeholder="${__("Or tell the AI what to say")}">
							<button class="btn btn-default btn-sm sin-suggest">${__("AI suggest")}</button>
							<button class="btn btn-primary btn-sm sin-write">${__("Send")}</button></div>`
						: `<div class="sin-warn">${__("No channel to reply on right now")}: ${e(t.channels.map((ch) => `${ch.channel}: ${ch.reason}`).join(" · ") || __("no email, phone or chat"))}</div>`}</div>`}`);
			el.find(".sin-timeline").scrollTop(1e6);
			const reload = (r) => { this.render_thread(el, prospect, r); this.load(true); };
			el.find(".sin-status").on("click", () => this.call("set_status", { prospect, status: resolved ? "Open" : "Resolved" }).then(reload));
			el.find(".sin-assign").on("change", (ev) => this.call("assign", { prospect, user: ev.target.value }).then(reload));
			el.find(".sin-mode").on("change", (ev) => this.call("set_mode", { prospect, mode: ev.target.value }).then(reload));
			el.find(".sin-tag-in").on("keydown", (ev) => {
				if (ev.key !== "Enter" || !ev.target.value.trim()) return;
				this.call("tag", { prospect, tag: ev.target.value.trim() }).then(reload);
			});
			el.find(".sin-untag").on("click", (ev) => this.call("tag", { prospect, tag: ev.currentTarget.dataset.t, remove: 1 }).then(reload));
			const send = () => {
				const text = el.find(".sin-text").val().trim();
				if (!text) return;
				el.find(".sin-write").prop("disabled", true);
				this.call("send", { prospect, channel: el.find(".sin-channel").val(), text })
					.then((status) => { frappe.show_alert({ message: __("Sent ({0})", [__(status)]), indicator: "green" }); el.find(".sin-text").val(""); this.open(prospect); this.load(true); })
					.finally(() => el.find(".sin-write").prop("disabled", false));
			};
			el.find(".sin-write").on("click", send);
			el.find(".sin-text").on("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) send(); });
			el.find(".sin-suggest").on("click", (ev) => {
				$(ev.currentTarget).prop("disabled", true);
				frappe.call({ method: API + "suggest", args: { prospect, instruction: el.find(".sin-instr").val() }, freeze: true,
					freeze_message: __("Reading the conversation and writing a reply…") })
					.then(() => this.open(prospect)).always(() => $(ev.currentTarget).prop("disabled", false));
			});
			el.find(".sin-use").on("click", (ev) => {
				// Take the AI's draft into the reply box: the person edits and sends it as their own.
				const box = $(ev.currentTarget).closest(".sin-draft");
				el.find(".sin-text").val(box.find(".txt").text()).trigger("focus");
				this.call("discard", { message: box.data("m") }).then(() => box.remove());
			});
			el.find(".sin-send").on("click", (ev) => {
				const name = $(ev.currentTarget).closest(".sin-draft").data("m");
				frappe.confirm(__("Approve and send this message?"), () => this.call("approve_and_send", { message: name })
					.then((status) => { frappe.show_alert({ message: __("Status: {0}", [__(status)]), indicator: "green" }); this.open(prospect); this.load(true); }));
			});
			el.find(".sin-discard").on("click", (ev) => this.call("discard", { message: $(ev.currentTarget).closest(".sin-draft").data("m") })
				.then(() => this.open(prospect)));
		}
	}
})();
