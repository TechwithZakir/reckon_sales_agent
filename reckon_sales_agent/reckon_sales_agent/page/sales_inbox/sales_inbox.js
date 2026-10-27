// Conversations: every lead's thread across email, WhatsApp, calls, forms and meetings, with AI replies
// that a person approves. Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-inbox"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Conversations"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.inbox = new Inbox(page);
	};
	frappe.pages["sales-inbox"].on_page_show = (wrapper) => wrapper.inbox && wrapper.inbox.load();

	const API = "reckon_sales_agent.api_conversations.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const when = (v) => (v ? frappe.datetime.prettyDate(v) : "");
	const SOURCES = { meta_lead_ads: __("Meta lead form") };

	class Inbox {
		constructor(page) {
			this.page = page;
			this.filter = "waiting";
			this.$root = $(`<div class="sin"><aside class="sin-list"></aside><section class="sin-thread"></section></div>`).appendTo(page.main);
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		load() {
			return this.call("threads").then((rows) => {
				this.rows = rows;
				if (!this.current && rows.length) this.current = (rows.find((r) => r.needs_reply) || rows[0]).prospect;
				this.render_list();
				if (this.current) this.open(this.current);
				else this.$root.find(".sin-thread").html(`<div class="sin-empty">${__("No conversations yet. Replies, calls and lead forms appear here.")}</div>`);
			});
		}

		render_list() {
			const rows = this.filter === "waiting" ? this.rows.filter((r) => r.needs_reply) : this.rows;
			const waiting = this.rows.filter((r) => r.needs_reply).length;
			this.$root.find(".sin-list").html(`
				<div class="sin-tabs"><button data-f="waiting" class="${this.filter === "waiting" ? "on" : ""}">${__("Waiting for us")} <b>${waiting}</b></button>
					<button data-f="all" class="${this.filter === "all" ? "on" : ""}">${__("All")} <b>${this.rows.length}</b></button></div>
				${rows.map((r) => `<button class="sin-item ${r.prospect === this.current ? "on" : ""}" data-p="${e(r.prospect)}">
					<div class="top"><b>${e(r.business || r.prospect)}</b><span>${e(when(r.last))}</span></div>
					<div class="meta">${r.needs_reply ? `<span class="sin-badge warn">${__("They spoke last")}</span>` : ""}
						${r.draft_waiting ? `<span class="sin-badge">${__("Draft ready")}</span>` : ""}
						${SOURCES[r.source] ? `<span class="sin-badge src">${e(SOURCES[r.source])}</span>` : ""}</div></button>`).join("")
					|| `<div class="sin-empty small">${this.filter === "waiting" ? __("Nobody is waiting for a reply.") : __("No conversations yet.")}</div>`}`);
			this.$root.find(".sin-tabs button").on("click", (ev) => { this.filter = ev.currentTarget.dataset.f; this.render_list(); });
			this.$root.find(".sin-item").on("click", (ev) => { this.current = ev.currentTarget.dataset.p; this.render_list(); this.open(this.current); });
		}

		open(prospect) {
			const el = this.$root.find(".sin-thread").html(`<div class="sin-empty">${__("Loading…")}</div>`);
			return this.call("thread", { prospect }).then((t) => {
				const p = t.prospect;
				el.html(`<div class="sin-head"><div><h3>${e(p.business_name)}</h3>
						<div class="sin-muted">${[p.email ? e(p.email) : "", p.phone ? `<a href="tel:${e(p.phone)}">${e(p.phone)}</a>` : "", e(p.city || "")]
							.filter(Boolean).join(" · ")}${p.consent_source ? ` · ${__("consent")}: ${e(p.consent_source)}` : ""}</div></div>
						<div class="sin-links"><a class="btn btn-xs btn-default" href="/desk/sales-prospect/${encodeURIComponent(p.name)}">${__("Lead")}</a>
						${p.crm_lead ? `<a class="btn btn-xs btn-default" href="/crm/leads/${encodeURIComponent(p.crm_lead)}">${__("CRM")}</a>` : ""}</div></div>
					<div class="sin-timeline">${t.timeline.map((i) => `<div class="sin-msg ${e(i.direction)}">
						<div class="sin-muted">${e(i.channel)} · ${e(__(i.status))} · ${e(when(i.at))}</div>
						${i.subject ? `<b>${e(i.subject)}</b>` : ""}<div class="txt">${e(i.text)}</div></div>`).join("")
						|| `<div class="sin-empty small">${__("No messages yet.")}</div>`}</div>
					<div class="sin-drafts">${t.drafts.map((d) => `<div class="sin-draft" data-m="${e(d.name)}">
						<div class="sin-muted">${__("Draft")} · ${e(d.channel)} → ${e(d.recipient || "")}</div>
						${d.subject ? `<b>${e(d.subject)}</b>` : ""}<div class="txt">${e($("<div>").html(d.body).text())}</div>
						${d.error ? `<div class="sin-warn">${e(d.error)}</div>` : ""}
						<div class="sin-actions"><a class="btn btn-xs btn-default" href="/desk/sales-outreach-message/${encodeURIComponent(d.name)}">${__("Edit")}</a>
							<button class="btn btn-xs btn-default sin-discard">${__("Discard")}</button>
							<button class="btn btn-xs btn-primary sin-send">${__("Approve and send")}</button></div></div>`).join("")}</div>
					${p.do_not_contact ? `<div class="sin-warn">${__("This lead asked not to be contacted.")}</div>` : `<div class="sin-compose">
						<input class="form-control sin-instr" placeholder="${__("Optional: tell the AI what to say (e.g. offer a demo on Sunday)")}">
						<button class="btn btn-primary btn-sm sin-suggest">${__("Suggest a reply with AI")}</button></div>`}`);
				el.find(".sin-timeline").scrollTop(1e6);
				el.find(".sin-suggest").on("click", (ev) => {
					$(ev.currentTarget).prop("disabled", true);
					frappe.call({ method: API + "suggest", args: { prospect, instruction: el.find(".sin-instr").val() }, freeze: true,
						freeze_message: __("Reading the conversation and writing a reply…") })
						.then(() => this.load()).always(() => $(ev.currentTarget).prop("disabled", false));
				});
				el.find(".sin-send").on("click", (ev) => {
					const name = $(ev.currentTarget).closest(".sin-draft").data("m");
					frappe.confirm(__("Approve and send this message?"), () => this.call("approve_and_send", { message: name })
						.then((status) => { frappe.show_alert({ message: __("Status: {0}", [__(status)]), indicator: "green" }); this.load(); }));
				});
				el.find(".sin-discard").on("click", (ev) => this.call("discard", { message: $(ev.currentTarget).closest(".sin-draft").data("m") })
					.then(() => this.load()));
			});
		}
	}
})();
