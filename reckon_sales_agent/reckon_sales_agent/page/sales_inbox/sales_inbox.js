// Conversations: a dock-style inbox for every channel a lead uses (email, WhatsApp, SMS, Messenger, Instagram,
// website chat, calls). Left dock: the conversations. Centre: the thread and the reply box. Right dock: the lead,
// its owner, AI mode, tags and channels. Changes arrive live over Frappe's realtime channel; a slow poll is only a
// fallback. Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	const SOUND_KEY = "rsa_sound";  // shared with the Desk dock: the same bell setting everywhere
	const sound_on = () => { try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch (err) { return true; } };
	const set_sound = (on) => { try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch (err) { /* private browsing */ } };
	frappe.pages["sales-inbox"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Conversations"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		page.add_inner_button(__("Integrations"), () => frappe.set_route("sales-channels"));
		wrapper.inbox = new Inbox(page);
	};
	frappe.pages["sales-inbox"].on_page_show = (wrapper) => wrapper.inbox && wrapper.inbox.start();
	frappe.pages["sales-inbox"].on_page_hide = (wrapper) => wrapper.inbox && wrapper.inbox.stop();

	const API = "reckon_sales_agent.api_conversations.";
	const EVENT = "rsa_inbox";
	const FALLBACK_MS = 60000;
	const PREFS = "rsa_inbox_layout";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const when = (v) => (v ? frappe.datetime.prettyDate(v) : "");
	const CHANNELS = { "Web Chat": __("Website chat"), Messenger: "Messenger", Instagram: "Instagram", WhatsApp: "WhatsApp",
		SMS: "SMS", Voice: __("Phone call"), Email: __("Email"), Call: __("Phone call"), LinkedIn: "LinkedIn" };
	const SOURCES = { meta_lead_ads: __("Meta lead form"), linkedin_lead_gen: __("LinkedIn lead form"), voice: __("Phone call") };
	const MODES = [["Company default", __("Company default")], ["Autopilot", __("AI autopilot")],
		["Suggest only", __("AI suggests, we send")], ["Human only", __("Human only")]];
	const FILTERS = [["waiting", __("Waiting")], ["mine", __("Mine")], ["unassigned", __("Unassigned")],
		["needs", __("Needs a person")], ["open", __("Open")], ["resolved", __("Resolved")]];

	const loadPrefs = () => {
		try { return { left: true, right: true, max: false, bl: true, folded: false, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; }
		catch (err) { return { left: true, right: true, max: false, bl: true, folded: false }; }
	};

	class Inbox {
		constructor(page) {
			this.page = page;
			this.filter = "waiting";
			this.search = "";
			this.prefs = loadPrefs();
			this.pending = new Set();
			this.flush = frappe.utils.debounce(() => { this.pending.clear(); this.load(true); }, 300);
			this.onRealtime = (data) => { if (data && data.prospect) this.pending.add(data.prospect); this.flush(); };
			this.$root = $(`<div class="sin">
				<aside class="sin-dock sin-left"><div class="sin-list"></div></aside>
				<section class="sin-main">
					<div class="sin-topbar">
						<span class="sin-live"></span>
						<div class="sin-tools">
							<button class="btn btn-default btn-xs" data-t="left"></button>
							<button class="btn btn-default btn-xs" data-t="right"></button>
							<button class="btn btn-default btn-xs" data-t="bl"></button>
							<button class="btn btn-default btn-xs" data-t="max"></button>
						</div>
					</div>
					<div class="sin-thread"></div>
				</section>
				<aside class="sin-dock sin-right"><div class="sin-ctx"></div></aside>
			</div>`).appendTo(page.main);
			this.$root.find(".sin-tools button").on("click", (ev) => {
				const key = ev.currentTarget.dataset.t;
				this.prefs[key] = key === "max" ? !this.prefs.max : !this.prefs[key];
				this.save_prefs();
				this.apply_layout();
			});
			this.apply_layout();
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		save_prefs() {
			try { localStorage.setItem(PREFS, JSON.stringify(this.prefs)); } catch (err) { /* private mode: this visit only */ }
		}

		apply_layout() {
			const p = this.prefs;
			this.$root.toggleClass("no-left", !p.left).toggleClass("no-right", !p.right).toggleClass("max", !!p.max)
				.toggleClass("dock-bl", !!p.bl).toggleClass("folded", !!p.folded);
			this.$root.find('[data-t="bl"]').text(p.bl ? __("Side column") : __("Dock bottom left"));
			this.$root.find('[data-t="left"]').text(p.left ? __("Hide list") : __("Show list"));
			this.$root.find('[data-t="right"]').text(p.right ? __("Hide details") : __("Show details"));
			this.$root.find('[data-t="max"]').text(p.max ? __("Standard width") : __("Full width"));
		}

		render_live() {
			const live = !!(frappe.realtime && frappe.realtime.socket && frappe.realtime.socket.connected);
			this.$root.find(".sin-live").attr("class", `sin-live ${live ? "on" : ""}`)
				.attr("title", live ? __("Updates arrive live") : __("Reconnecting; checking every minute"))
				.text(live ? __("Live") : __("Syncing"));
		}

		start() {
			this.load();
			if (frappe.realtime && frappe.realtime.off) frappe.realtime.off(EVENT, this.onRealtime);
			if (frappe.realtime && frappe.realtime.on) frappe.realtime.on(EVENT, this.onRealtime);
			clearInterval(this.timer);
			this.timer = setInterval(() => !document.hidden && this.load(true), FALLBACK_MS);
		}

		stop() {
			if (frappe.realtime && frappe.realtime.off) frappe.realtime.off(EVENT, this.onRealtime);
			clearInterval(this.timer);
		}

		load(quiet) {
			return this.call("threads").then((rows) => {
				this.rows = rows;
				if (!this.current && rows.length) this.current = (rows.find((r) => r.needs_reply) || rows[0]).prospect;
				this.render_list();
				this.render_live();
				// Never redraw a thread under someone typing a reply, or using a menu in the details dock.
				const busy = this.$root.find(".sin-text").val()
					|| this.$root.find(".sin-thread, .sin-ctx").toArray().some((el) => $.contains(el, document.activeElement));
				if (this.current && !(quiet && busy)) this.open(this.current);
				else if (!this.current) this.$root.find(".sin-thread").html(`<div class="sin-empty">${__("No conversations yet. Replies, chats, texts, calls and lead forms appear here.")}</div>`);
			});
		}

		channel_of(r) {
			const c = r.conversation || {};
			return c.last_channel || r.chat || "";
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
				<div class="sin-dock-head"><b>${__("Conversations")}</b><span class="sin-dock-count">${this.rows.filter((r) => this.matches(r, "waiting")).length} ${__("waiting")}</span><button class="btn btn-default btn-xs sin-sound" title="${__("New message sound")}">${sound_on() ? "🔔" : "🔕"}</button><button class="btn btn-default btn-xs sin-fold" title="${this.prefs.folded ? __("Expand") : __("Fold")}">${this.prefs.folded ? "+" : "–"}</button></div>
				<input class="form-control sin-search" placeholder="${__("Search name, phone, tag")}" value="${e(this.search)}">
				<div class="sin-tabs">${FILTERS.map(([k, l]) => `<button data-f="${k}" class="${this.filter === k ? "on" : ""}">${e(l)} <b>${this.rows.filter((r) => this.matches(r, k)).length}</b></button>`).join("")}</div>
				${rows.map((r) => {
					const c = r.conversation || {};
					const channel = this.channel_of(r);
					return `<button class="sin-item ${r.prospect === this.current ? "on" : ""}" data-p="${e(r.prospect)}">
					<div class="top"><b>${e(r.business || r.prospect)}</b><span>${e(when(r.last))}</span></div>
					<div class="meta">${r.needs_reply ? `<span class="sin-badge warn">${__("They spoke last")}</span>` : ""}
						${r.draft_waiting ? `<span class="sin-badge">${__("Draft ready")}</span>` : ""}
						${channel ? `<span class="sin-badge ch">${e(CHANNELS[channel] || __(channel))}</span>` : SOURCES[r.source] ? `<span class="sin-badge src">${e(SOURCES[r.source])}</span>` : ""}
						${c.assigned_to ? `<span class="sin-badge src" title="${e(c.assigned_to)}">${e(frappe.user.full_name(c.assigned_to) || c.assigned_to)}</span>` : ""}
						${(c.tags || []).map((t) => `<span class="sin-badge ${t === "needs-human" ? "warn" : "tag"}">#${e(t)}</span>`).join("")}</div></button>`;
				}).join("") || `<div class="sin-empty small">${__("Nothing here.")}</div>`}`);
			if (searching) list.find(".sin-search").trigger("focus").get(0).setSelectionRange(this.search.length, this.search.length);
			list.find(".sin-search").on("input", frappe.utils.debounce((ev) => { this.search = ev.target.value; this.render_list(); }, 250));
			list.find(".sin-tabs button").on("click", (ev) => { this.filter = ev.currentTarget.dataset.f; this.render_list(); });
			list.find(".sin-sound").on("click", () => { set_sound(!sound_on()); this.render_list(); });
			list.find(".sin-fold").on("click", () => { this.prefs.folded = !this.prefs.folded; this.save_prefs(); this.apply_layout(); this.render_list(); });
			list.find(".sin-item").on("click", (ev) => { this.current = ev.currentTarget.dataset.p; this.render_list(); this.open(this.current); });
		}

		open(prospect) {
			this.$root.addClass("m-thread");  // on phones: show the thread, not the list
			if (this.shown !== prospect) this.$root.find(".sin-thread").html(`<div class="sin-empty">${__("Loading…")}</div>`);
			return this.call("thread", { prospect }).then((t) => { this.shown = prospect; this.render_thread(prospect, t); });
		}

		timeline_html(items, name) {
			if (!items.length) return `<div class="sin-empty small">${__("No messages yet.")}</div>`;
			const avatar = String(name || "?").trim().charAt(0).toUpperCase() || "?";
			let day = "";
			return items.map((i) => {
				const d = i.at ? String(i.at).slice(0, 10) : "";
				const sep = d && d !== day ? `<div class="sin-day">${e(frappe.datetime.str_to_user(d))}</div>` : "";
				day = d || day;
				if (i.direction === "note") return `${sep}<div class="sin-note-line">${e(i.text || __(i.status))}</div>`;
				const out = i.direction === "out";
				return `${sep}<div class="sin-row ${out ? "out" : "in"}">${out ? "" : `<span class="sin-av">${e(avatar)}</span>`}
					<div class="sin-bubble ${out ? "out" : "in"}">${i.subject ? `<b>${e(i.subject)}</b><br>` : ""}${e(i.text)}
					<div class="sin-stamp">${e(CHANNELS[i.channel] || i.channel)} · ${e(__(i.status))} · ${e(when(i.at))}</div></div></div>`;
			}).join("");
		}

		copilot(prospect) {
			return this.call("copilot_summary", { prospect }).then((g) => {
				frappe.msgprint({ title: __("Copilot"), indicator: "blue", message: this.copilot_html(g) });
				if (g.meeting_suggested) {
					frappe.confirm(__("A meeting fits here. Draft a meeting proposal for you to approve?"), () => this.call("copilot_book_meeting", { prospect })
						.then(() => frappe.show_alert({ message: __("Meeting proposal drafted in Meetings"), indicator: "green" })));
				}
			});
		}

		copilot_html(g) {
			const risks = (g.risks || []).map((r) => `<li>${e(r)}</li>`).join("");
			return `<p>${e(g.summary)}</p><p><b>${e(__("Next step"))}:</b> ${e(g.next_step)}</p>${risks ? `<b>${e(__("Watch out"))}</b><ul>${risks}</ul>` : ""}`
				+ `<div class="sin-muted small">${e(g.source === "ai" ? __("AI summary, read-only") : __("Summary from CRM facts, read-only"))}</div>`;
		}

		render_thread(prospect, t) {
			const el = this.$root.find(".sin-thread"), ctx = this.$root.find(".sin-ctx");
			const p = t.prospect, c = t.conversation;
			const ok = t.channels.filter((ch) => ch.ok);
			const resolved = c.status === "Resolved";
			const waClosed = t.channels.some((ch) => ch.channel === "WhatsApp" && ch.window_closed);
			const waTemplates = waClosed && (t.wa_templates || []).length ? `<div class="sin-reply-row sin-wa"><span class="sin-muted">${__("24-hour window closed: send an approved template")}</span><select class="form-control input-sm sin-wa-tpl">${t.wa_templates.map((w) => `<option value="${e(w.name)}">${e(w.template_name)}</option>`).join("")}</select><button class="btn btn-default btn-sm sin-wa-send">${__("Send template")}</button></div>` : "";
			el.html(`<div class="sin-head"><button class="btn btn-default btn-xs sin-m-back" aria-label="${__("Back")}">‹</button><div><h3>${e(p.business_name)}</h3>
					<div class="sin-muted">${[p.email ? e(p.email) : "", p.phone ? `<a href="tel:${e(p.phone)}">${e(p.phone)}</a>` : "", e(p.city || "")].filter(Boolean).join(" · ")}</div></div>
					<div class="sin-links"><button class="btn btn-default btn-xs sin-copilot">${__("Copilot")}</button><button class="btn btn-xs ${resolved ? "btn-default" : "btn-primary"} sin-status">${resolved ? __("Reopen") : __("Resolve")}</button></div></div>
				${c.handoff_reason && !resolved ? `<div class="sin-warn">${__("Needs a person")}: ${e(c.handoff_reason)}</div>` : ""}
				<div class="sin-timeline">${this.timeline_html(t.timeline, p.business_name)}</div>
				<div class="sin-drafts">${t.drafts.map((d) => `<div class="sin-draft" data-m="${e(d.name)}">
					<div class="sin-muted">${__("AI draft")} · ${e(CHANNELS[d.channel] || d.channel)} → ${e(d.recipient || "")}</div>
					${d.subject ? `<b>${e(d.subject)}</b>` : ""}<div class="txt">${e($("<div>").html(d.body).text())}</div>
					${d.error ? `<div class="sin-warn">${e(d.error)}</div>` : ""}
					<div class="sin-actions"><button class="btn btn-xs btn-default sin-use">${__("Edit before sending")}</button>
						<button class="btn btn-xs btn-default sin-discard">${__("Discard")}</button>
						<button class="btn btn-xs btn-primary sin-send">${__("Approve and send")}</button></div></div>`).join("")}</div>
				${p.do_not_contact ? `<div class="sin-warn">${__("This lead asked not to be contacted.")}</div>` : `<div class="sin-reply">
					${waTemplates}${ok.length ? `<div class="sin-reply-row"><select class="form-control input-sm sin-channel">${ok.map((ch) => `<option value="${e(ch.channel)}">${e(CHANNELS[ch.channel] || __(ch.channel))}${ch.from ? ` · ${e(ch.from)}` : ""}</option>`).join("")}</select>
						<span class="sin-muted">${e(t.channels.filter((ch) => !ch.ok).map((ch) => `${CHANNELS[ch.channel] || ch.channel}: ${ch.reason}`).join(" · "))}</span></div>
						<textarea class="form-control sin-text" rows="3" placeholder="${__("Write your reply… (Ctrl+Enter to send)")}"></textarea>
						<div class="sin-actions"><input class="form-control input-sm sin-instr" placeholder="${__("Or tell the AI what to say")}">
							<button class="btn btn-default btn-sm sin-suggest">${__("AI suggest")}</button>
							<button class="btn btn-primary btn-sm sin-write">${__("Send")}</button></div>`
						: `<div class="sin-warn">${__("No channel to reply on right now")}: ${e(t.channels.map((ch) => `${ch.channel}: ${ch.reason}`).join(" · ") || __("no email, phone or chat"))}</div>`}</div>`}`);
			el.find(".sin-timeline").scrollTop(1e6);
			el.find(".sin-m-back").on("click", () => this.$root.removeClass("m-thread"));

			ctx.html(`<div class="sin-card"><h4>${__("Lead")}</h4>
					<div class="sin-kv"><span>${__("Source")}</span><b>${e(CHANNELS[this.channel_of({ conversation: c })] || SOURCES[p.source_type] || p.source_type || "–")}</b>
						${p.consent_source ? `<span>${__("Consent")}</span><b>${e(p.consent_source)}</b>` : ""}
						${c.last_inbound_at ? `<span>${__("Wrote")}</span><b>${e(when(c.last_inbound_at))}</b>` : ""}</div>
					<div class="sin-links"><a class="btn btn-xs btn-default" href="/desk/sales-prospect/${encodeURIComponent(p.name)}">${__("Lead")}</a>
						${p.crm_lead ? `<a class="btn btn-xs btn-default" href="/crm/leads/${encodeURIComponent(p.crm_lead)}">${__("CRM")}</a>` : ""}</div></div>
				<div class="sin-card"><h4>${__("Owner")}</h4>
					<select class="form-control sin-assign"><option value="">${__("Nobody")}</option>
						${t.agents.map((a) => `<option value="${e(a.user)}" ${a.user === c.assigned_to ? "selected" : ""}>${e(a.name)}${a.user === t.me ? " (" + __("me") + ")" : ""}</option>`).join("")}</select></div>
				<div class="sin-card"><h4>${__("AI")}</h4>
					<select class="form-control sin-mode">${MODES.map(([k, l]) => `<option value="${e(k)}" ${k === c.ai_mode ? "selected" : ""}>${e(l)}</option>`).join("")}</select>
					<div class="sin-muted">${__("now: {0}", [e(__(c.effective))])}</div></div>
				<div class="sin-card"><h4>${__("Tags")}</h4>
					<div class="sin-tags">${(c.tags || []).map((tg) => `<span class="sin-badge ${tg === "needs-human" ? "warn" : "tag"}">#${e(tg)} <a class="sin-untag" data-t="${e(tg)}" title="${__("Remove")}">×</a></span>`).join("")}</div>
					<input class="form-control sin-tag-in" placeholder="${__("Add a tag and press Enter")}" maxlength="40"></div>
				<div class="sin-card"><h4>${__("Channels")}</h4>
					${t.channels.map((ch) => `<div class="sin-chan ${ch.ok ? "ok" : ""}"><span>${e(CHANNELS[ch.channel] || ch.channel)}</span><small>${ch.from ? `${e(ch.from)} · ` : ""}${e(ch.reason)}</small></div>`).join("")}</div>`);

			const refresh = () => { this.open(prospect); this.load(true); };
			el.find(".sin-copilot").on("click", () => this.copilot(prospect));
			el.find(".sin-status").on("click", () => this.call("set_status", { prospect, status: resolved ? "Open" : "Resolved" }).then(refresh));
			ctx.find(".sin-assign").on("change", (ev) => this.call("assign", { prospect, user: ev.target.value }).then(refresh));
			ctx.find(".sin-mode").on("change", (ev) => this.call("set_mode", { prospect, mode: ev.target.value }).then(refresh));
			ctx.find(".sin-tag-in").on("keydown", (ev) => {
				if (ev.key !== "Enter" || !ev.target.value.trim()) return;
				this.call("tag", { prospect, tag: ev.target.value.trim() }).then(refresh);
			});
			ctx.find(".sin-untag").on("click", (ev) => this.call("tag", { prospect, tag: ev.currentTarget.dataset.t, remove: 1 }).then(refresh));
			const send = () => {
				const text = el.find(".sin-text").val().trim();
				if (!text) return;
				el.find(".sin-write").prop("disabled", true);
				this.call("send", { prospect, channel: el.find(".sin-channel").val(), text })
					.then((status) => { frappe.show_alert({ message: __("Sent ({0})", [__(status)]), indicator: "green" }); el.find(".sin-text").val(""); refresh(); })
					.finally(() => el.find(".sin-write").prop("disabled", false));
			};
			el.find(".sin-write").on("click", send);
			el.find(".sin-wa-send").on("click", () => this.call("send", { prospect, channel: "WhatsApp", text: "", template: el.find(".sin-wa-tpl").val() })
				.then((status) => { frappe.show_alert({ message: __("Sent ({0})", [__(status)]), indicator: "green" }); refresh(); }));
			el.find(".sin-text").on("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) send(); });
			el.find(".sin-suggest").on("click", (ev) => {
				$(ev.currentTarget).prop("disabled", true);
				frappe.call({ method: API + "suggest", args: { prospect, instruction: el.find(".sin-instr").val() }, freeze: true,
					freeze_message: __("Reading the conversation and writing a reply…") })
					.then(() => this.open(prospect)).always(() => $(ev.currentTarget).prop("disabled", false));
			});
			el.find(".sin-use").on("click", (ev) => {
				// The AI's draft goes into the reply box: the person edits it and sends it as their own.
				const box = $(ev.currentTarget).closest(".sin-draft");
				el.find(".sin-text").val(box.find(".txt").text()).trigger("focus");
				this.call("discard", { message: box.data("m") }).then(() => box.remove());
			});
			el.find(".sin-send").on("click", (ev) => {
				const name = $(ev.currentTarget).closest(".sin-draft").data("m");
				frappe.confirm(__("Approve and send this message?"), () => this.call("approve_and_send", { message: name })
					.then((status) => { frappe.show_alert({ message: __("Status: {0}", [__(status)]), indicator: "green" }); refresh(); }));
			});
			el.find(".sin-discard").on("click", (ev) => this.call("discard", { message: $(ev.currentTarget).closest(".sin-draft").data("m") })
				.then(() => this.open(prospect)));
		}
	}
})();
