// Message Templates: the library and the template builder (email, SMS, WhatsApp, LinkedIn).
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-templates"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Message Templates"), single_column: true });
		page.add_inner_button(__("Campaign Studio"), () => frappe.set_route("campaign-studio"));
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.templates = new Templates(page);
	};
	frappe.pages["sales-templates"].on_page_show = (wrapper) => wrapper.templates && wrapper.templates.show();

	const API = "reckon_sales_agent.api_templates.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const clone = (v) => JSON.parse(JSON.stringify(v));
	const CHANNELS = ["Email", "SMS", "WhatsApp", "LinkedIn"];
	const TONES = ["Friendly", "Professional", "Direct", "Consultative"];
	const GOALS = ["Book a meeting", "Re-engage", "Upsell", "Event invite"];
	const GLYPH = { heading: "H1", text: "Tt", image: "▢", button: "[ ]", columns: "||", divider: "—", product: "★", dynamic: "◇", signature: "@", social: "#", spacer: "↕" };
	const LABEL = { heading: __("Heading"), text: __("Text"), image: __("Image"), button: __("Button"), columns: __("Columns"), divider: __("Divider"),
		product: __("Product card"), dynamic: __("Dynamic content"), signature: __("Signature"), social: __("Social links"), spacer: __("Spacer") };
	const OPS = [["contains", __("contains")], ["is", __("is")], ["not_empty", __("is not empty")], ["empty", __("is empty")]];
	const AI_EDITS = [[__("Make it shorter"), "Make it shorter, keeping the meaning."], [__("Friendlier"), "Make it warmer and friendlier."],
		[__("More direct"), "Make it more direct and to the point."], [__("Translate to Bangla"), "Translate it to natural Bangla."],
		[__("Translate to English"), "Translate it to natural English."]];
	const ICON = {
		up: '<path d="M12 19V5M5 12l7-7 7 7"/>', down: '<path d="M12 5v14M5 12l7 7 7-7"/>', copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>',
		spark: '<path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
		save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v6h8V4M8 20v-6h8v6"/>',
	};
	const icon = (name, size) => `<svg width="${size || 14}" height="${size || 14}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">${ICON[name]}</svg>`;
	const MANAGER_ROLES = ["Reckon Sales Agent Admin", "Reckon Sales Agent Manager", "Reckon Vendor Superuser", "System Manager"];
	const can_manage = () => frappe.session.user === "Administrator" || MANAGER_ROLES.some((r) => frappe.user.has_role(r));
	const text_of = (t) => String(t.subject || t.body || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

	class Templates {
		constructor(page) {
			this.page = page;
			this.$root = $(`<div class="tb"></div>`).appendTo(page.main);
			this.filter = { channel: "All", status: "All", search: "" };
			this.open_name = null;
			this.seq = 0;
		}

		// Routing ---------------------------------------------------------------

		show() {
			const wanted = (frappe.get_route() || [])[1] || "";
			return this.load().then(() => {
				if (wanted) {
					if (wanted !== this.open_name) return this.open_builder(wanted);
					return;
				}
				if (this.open_name && this.dirty) this.save(true);
				this.open_name = null;
				this.render_library();
			});
		}

		load() {
			return frappe.xcall(API + "library").then((lib) => { this.lib = lib; });
		}

		// Library ----------------------------------------------------------------

		render_library() {
			const lib = this.lib;
			const f = this.filter;
			const rows = lib.templates.filter((t) => (f.channel === "All" || t.channel === f.channel)
				&& (f.status === "All" || t.status === f.status)
				&& (!f.search || `${t.template_name} ${text_of(t)}`.toLowerCase().includes(f.search.toLowerCase())));
			this.$root.html(`
				<div class="tb-head"><div><h3>${__("Message templates")}</h3>
					<div class="tb-muted">${__("Build email, SMS, WhatsApp and LinkedIn messages once, approve them, and use them in any campaign.")}</div></div>
					${lib.can_manage ? `<button class="tb-btn primary tb-new">${__("New template")}</button>` : ""}</div>
				<div class="tb-filters">
					${["All", ...CHANNELS].map((c) => `<button class="tb-chipbtn tb-fch ${f.channel === c ? "on" : ""}" data-c="${c}">${c === "All" ? __("All") : c}</button>`).join("")}
					<span style="flex:1"></span>
					${["All", "Draft", "Approved"].map((s) => `<button class="tb-chipbtn tb-fst ${f.status === s ? "on" : ""}" data-s="${s}">${s === "All" ? __("Any status") : __(s)}</button>`).join("")}
					<input class="form-control tb-search" style="max-width:220px;height:30px" placeholder="${__("Search")}" value="${e(f.search)}">
				</div>
				<div class="tb-cards">${rows.map((t) => this.card(t)).join("") || `<div class="tb-empty">${__("No templates match.")}</div>`}</div>`);
			this.$root.find(".tb-new").on("click", () => this.new_dialog());
			this.$root.find(".tb-fch").on("click", (ev) => { f.channel = ev.currentTarget.dataset.c; this.render_library(); });
			this.$root.find(".tb-fst").on("click", (ev) => { f.status = ev.currentTarget.dataset.s; this.render_library(); });
			this.$root.find(".tb-search").on("input", (ev) => {
				f.search = ev.currentTarget.value;
				clearTimeout(this.t_search);
				this.t_search = setTimeout(() => { this.render_library(); this.$root.find(".tb-search").focus().get(0).setSelectionRange(f.search.length, f.search.length); }, 250);
			});
			const name = (ev) => $(ev.currentTarget).closest(".tb-tcard").data("name");
			this.$root.find(".tb-tcard").on("click", (ev) => { if (!$(ev.target).closest("button").length) frappe.set_route("sales-templates", name(ev)); });
			this.$root.find(".tb-open").on("click", (ev) => frappe.set_route("sales-templates", name(ev)));
			this.$root.find(".tb-dup").on("click", (ev) => frappe.xcall(API + "duplicate", { template: name(ev) }).then((n) => frappe.set_route("sales-templates", n)));
			this.$root.find(".tb-appr").on("click", (ev) => this.approve(name(ev)));
			this.$root.find(".tb-use").on("click", (ev) => this.use_in_campaign(name(ev)));
			this.$root.find(".tb-ret").on("click", (ev) => frappe.confirm(__("Retire this template? Campaigns that already use it keep working."), () =>
				frappe.xcall(API + "retire", { template: name(ev) }).then(() => this.load().then(() => this.render_library()))));
		}

		card(t) {
			const manage = this.lib.can_manage;
			const status = t.status === "Approved" ? `<span class="tb-pill ok">${__("Approved")}</span>`
				: t.content_status === "Needs review" ? `<span class="tb-pill warn">${__("Needs review")}</span>` : `<span class="tb-pill">${__("Draft")}</span>`;
			return `<div class="tb-card tb-tcard" data-name="${e(t.name)}">
				<div class="tb-row" style="justify-content:space-between"><span class="tb-pill dark">${e(t.channel)}</span>${status}</div>
				<div><div class="subj">${e(t.template_name)}</div>${t.subject ? `<div class="tb-muted">${e(t.subject)}</div>` : ""}</div>
				<div class="snip">${e(text_of({ body: t.body }))}</div>
				<div class="tb-row" style="justify-content:space-between"><span class="tb-muted">${frappe.datetime.prettyDate(t.modified)}</span>
					<span class="tb-row" style="gap:6px"><button class="tb-btn sm tb-open">${manage ? __("Edit") : __("Open")}</button>
						${manage ? `<button class="tb-btn sm tb-dup">${__("Duplicate")}</button>` : ""}
						${manage && t.status !== "Approved" ? `<button class="tb-btn sm primary tb-appr">${__("Approve")}</button>` : ""}
						${t.status === "Approved" ? `<button class="tb-btn sm primary tb-use">${__("Use in campaign")}</button>` : ""}
						${manage ? `<button class="tb-btn sm ghost tb-ret">${__("Retire")}</button>` : ""}</span></div></div>`;
		}

		new_dialog() {
			const starters = this.lib.starters;
			let dialog = null;
			const fill = () => {
				const channel = dialog.get_value("channel");
				const options = [{ value: "", label: __("A blank template") }, ...starters.filter((s) => s.channels.includes(channel)).map((s) => ({ value: s.id, label: `${s.name} (${s.meta})` }))];
				dialog.set_df_property("starter", "options", options);
				dialog.set_value("starter", "");
			};
			dialog = new frappe.ui.Dialog({
				title: __("New template"),
				fields: [
					{ fieldname: "template_name", fieldtype: "Data", label: __("Name"), reqd: 1 },
					{ fieldname: "channel", fieldtype: "Select", label: __("Channel"), options: CHANNELS.join("\n"), default: "Email", reqd: 1, onchange: () => dialog && fill() },
					{ fieldname: "language", fieldtype: "Select", label: __("Language"), options: "English\nBangla", default: "English" },
					{ fieldname: "starter", fieldtype: "Select", label: __("Start from"), options: "" },
				],
				primary_action_label: __("Create and open"),
				primary_action: (v) => frappe.xcall(API + "start", { channel: v.channel, template_name: v.template_name, starter: v.starter || null, language: v.language })
					.then((n) => { dialog.hide(); frappe.set_route("sales-templates", n); }),
			});
			fill();
			dialog.show();
		}

		approve(name, then) {
			return frappe.xcall("frappe.client.get_value", { doctype: "Sales Message Template", filters: { name }, fieldname: ["content_status", "content_issues", "channel"] }).then((r) => {
				const v = r || {};
				const go = (ack) => frappe.xcall(API + "approve", { template: name, acknowledge_issues: ack ? 1 : 0 }).then(() => {
					frappe.show_alert({ message: v.channel === "WhatsApp" ? __("Approved. It is submitted to Meta for review.") : __("Approved"), indicator: "green" });
					return then ? then() : this.load().then(() => (this.open_name ? this.open_builder(this.open_name) : this.render_library()));
				});
				if (v.content_status === "Needs review") {
					return frappe.confirm(`${__("The content check found issues. Approve anyway?")}<br><br>${e(v.content_issues || "").replace(/\n/g, "<br>")}`, () => go(true));
				}
				return go(false);
			});
		}

		use_in_campaign(name) {
			try { localStorage.setItem("cst_use_template", name); localStorage.setItem("cst_tab", "campaigns"); } catch (err) { /* private window */ }
			frappe.set_route("campaign-studio");
		}

		// Builder -----------------------------------------------------------------

		open_builder(name) {
			return frappe.xcall(API + "get", { template: name }).then((d) => {
				this.open_name = name;
				this.tpl = d;
				this.c = d.content;
				this.res = d.result;
				this.left = d.channel === "Email" ? "blocks" : "fields";
				this.device = "desktop";
				this.sel = null;
				this.suggest = [];
				this.undo = null;
				this.dirty = false;
				this.saving = false;
				this.saved_at = null;
				this.render_builder();
			});
		}

		get manage() { return this.lib.can_manage; }

		render_builder() {
			this.$root.html(`<div class="tb-builder"><header class="tb-bar"></header><div class="tb-sub"></div>
				<div class="tb-work"><aside class="tb-left"></aside><main class="tb-main"></main><aside class="tb-right"></aside></div></div>`);
			this.$bar = this.$root.find(".tb-bar");
			this.$sub = this.$root.find(".tb-sub");
			this.$left = this.$root.find(".tb-left");
			this.$main = this.$root.find(".tb-main");
			this.$right = this.$root.find(".tb-right");
			this.$root.off("focusin.tb").on("focusin.tb", ".tb-main .form-control, .tb-right textarea", (ev) => { this.last_input = ev.currentTarget; });
			this.paint_bar();
			this.paint_sub();
			this.paint_left();
			this.paint_main();
			this.paint_right();
		}

		status_pill() {
			const t = this.tpl;
			if (this.saving) return `<span class="tb-pill dark">${__("Saving…")}</span>`;
			if (this.dirty) return `<span class="tb-pill dark">${__("Unsaved changes")}</span>`;
			if (t.status === "Approved") return `<span class="tb-pill ok">${__("APPROVED")}</span>`;
			return `<span class="tb-pill dark">${__("DRAFT")} · ${this.saved_at ? __("saved {0}", [this.saved_at]) : __("saved")}</span>`;
		}

		paint_bar() {
			const t = this.tpl;
			const issues = (this.res.issues || []).length;
			this.$bar.html(`<div class="logo">R</div>
				<nav class="crumb"><a class="tb-back">${__("Message templates")}</a><span aria-hidden="true">/</span>
					<input class="tb-name" aria-label="${__("Template name")}" value="${e(t.template_name)}" ${this.manage ? "" : "disabled"}>
					<span class="tb-status">${this.status_pill()}</span>${issues ? `<span class="tb-pill warn">${issues} ${__("to fix")}</span>` : ""}</nav>
				<div class="actions">
					<button class="tb-btn tb-preview">${__("Preview")}</button>
					${this.manage && t.channel === "Email" ? `<button class="tb-btn tb-test">${__("Send test")}</button>` : ""}
					${this.manage ? `<button class="tb-btn solid tb-save">${__("Save template")}</button>` : ""}
					${this.manage && t.status !== "Approved" ? `<button class="tb-btn primary tb-approve">${__("Approve")}</button>` : ""}
					${t.status === "Approved" ? `<button class="tb-btn primary tb-use">${__("Use in campaign")}</button>` : ""}
				</div>`);
			this.$bar.find(".tb-back").on("click", () => frappe.set_route("sales-templates"));
			this.$bar.find(".tb-name").on("input", (ev) => { this.tpl.template_name = ev.currentTarget.value; this.touch(); });
			this.$bar.find(".tb-preview").on("click", () => this.preview_dialog());
			this.$bar.find(".tb-test").on("click", () => this.send_test());
			this.$bar.find(".tb-save").on("click", () => this.save(true).then(() => frappe.show_alert({ message: __("Saved"), indicator: "green" })));
			this.$bar.find(".tb-approve").on("click", () => this.save(true).then(() => this.approve(this.tpl.name, () => this.open_builder(this.tpl.name))));
			this.$bar.find(".tb-use").on("click", () => this.use_in_campaign(this.tpl.name));
		}

		paint_status() {
			this.$bar.find(".tb-status").html(this.status_pill());
		}

		paint_sub() {
			const t = this.tpl;
			this.$sub.html(`<div class="tb-row"><span class="tb-pill dark">${e(t.channel)}</span>
				<span class="tb-muted">${t.channel === "WhatsApp" ? __("Needs Meta approval before it can be sent outside a conversation.")
					: t.channel === "LinkedIn" ? __("Used as a step in a campaign: a person sends it from LinkedIn.") : ""}</span></div>
				<div class="tb-row">
					${this.manage ? `<label class="tb-muted">${__("Language")}
						<select class="form-control tb-lang" style="display:inline-block;width:auto;height:28px;padding:0 8px"><option ${t.language === "English" ? "selected" : ""}>English</option><option ${t.language === "Bangla" ? "selected" : ""}>Bangla</option></select></label>` : ""}
					${t.channel === "Email" ? `<span class="tb-muted">${__("Preview as")}</span><div class="tb-seg">
						${["desktop", "mobile"].map((d) => `<button class="tb-dev ${this.device === d ? "on" : ""}" data-d="${d}">${d === "desktop" ? __("Desktop") : __("Mobile")}</button>`).join("")}</div>` : ""}</div>`);
			this.$sub.find(".tb-lang").on("change", (ev) => { this.tpl.language = ev.currentTarget.value; this.touch(); });
			this.$sub.find(".tb-dev").on("click", (ev) => { this.device = ev.currentTarget.dataset.d; this.paint_sub(); this.paint_main(); });
		}

		// Change handling: check quickly for the preview, save a little later ---------

		touch() {
			this.dirty = true;
			this.paint_status();
			clearTimeout(this.t_check);
			this.t_check = setTimeout(() => this.check(), 350);
			clearTimeout(this.t_save);
			this.t_save = setTimeout(() => this.save(false), 4000);
		}

		check() {
			const seq = ++this.seq;
			return frappe.xcall(API + "check", { channel: this.tpl.channel, content: JSON.stringify(this.c) }).then((r) => {
				if (seq !== this.seq) return; // an older answer
				this.res = r;
				this.paint_after_check();
			});
		}

		save(force) {
			clearTimeout(this.t_save);
			if (!this.manage || (!this.dirty && !force)) return Promise.resolve();
			this.saving = true;
			this.paint_status();
			return frappe.xcall(API + "save", { template: this.tpl.name, content: JSON.stringify(this.c), template_name: this.tpl.template_name, language: this.tpl.language })
				.then((r) => {
					this.saving = false;
					this.dirty = false;
					this.tpl.status = r.status;
					this.tpl.content_status = r.content_status;
					this.tpl.content_issues = r.content_issues;
					this.saved_at = frappe.datetime.now_time().slice(0, 5);
					if (r.back_to_draft) frappe.show_alert({ message: __("Changed after approval: approve it again before it is used."), indicator: "orange" });
					this.res = r.result;
					this.paint_bar();
					this.paint_after_check();
				}).catch(() => { this.saving = false; this.paint_status(); });
		}

		paint_after_check() {
			const ch = this.tpl.channel;
			this.paint_bar_issues();
			this.paint_right_checks();
			if (ch === "Email") this.paint_email_previews();
			else if (ch === "SMS") this.paint_sms();
			else if (ch === "WhatsApp") this.paint_wa();
			else this.paint_li();
			this.paint_issues_box();
		}

		paint_bar_issues() {
			const issues = (this.res.issues || []).length;
			this.$bar.find(".crumb .tb-pill.warn").remove();
			if (issues) this.$bar.find(".crumb").append(`<span class="tb-pill warn">${issues} ${__("to fix")}</span>`);
		}

		paint_issues_box() {
			const issues = this.res.issues || [];
			this.$main.find(".tb-issues").remove();
			if (issues.length) this.$main.prepend(`<div class="tb-issues"><b>${__("To fix before this can be approved")}</b>${issues.map((i) => `<span>${e(i)}</span>`).join("")}</div>`);
		}

		// Left panel: blocks, fields, templates --------------------------------

		paint_left() {
			const ch = this.tpl.channel;
			const tabs = ch === "Email" ? [["blocks", __("Blocks")], ["fields", __("Fields")], ["starters", __("Templates")]] : [["fields", __("Fields")], ["starters", __("Templates")]];
			if (!tabs.some(([k]) => k === this.left)) this.left = tabs[0][0];
			this.$left.html(`<div class="tb-tabs">${tabs.map(([k, l]) => `<button class="tb-ltab ${this.left === k ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}</div>
				<div class="tb-lbody">${this.left === "blocks" ? this.blocks_html() : this.left === "fields" ? this.fields_html() : this.starters_html()}</div>`);
			this.$left.find(".tb-ltab").on("click", (ev) => { this.left = ev.currentTarget.dataset.k; this.paint_left(); });
			this.$left.find(".tb-pal").on("click", (ev) => this.add_block(ev.currentTarget.dataset.type));
			this.$left.find(".tb-pal").on("dragstart", (ev) => ev.originalEvent.dataTransfer.setData("text/plain", `rsa-block:${ev.currentTarget.dataset.type}`));
			this.$left.find(".tb-sec").on("click", (ev) => this.add_section(ev.currentTarget.dataset.i));
			this.$left.find(".tb-secdel").on("click", (ev) => { ev.stopPropagation(); this.delete_section(ev.currentTarget.dataset.i); });
			this.$left.find(".tb-field").on("click", (ev) => this.insert_field(ev.currentTarget.dataset.key, ev.currentTarget.dataset.fb));
			this.$left.find(".tb-fsearch").on("input", (ev) => this.filter_fields(ev.currentTarget.value));
			this.$left.find(".tb-start").on("click", (ev) => this.apply_starter(ev.currentTarget.dataset.id));
		}

		blocks_html() {
			const sections = this.lib.sections;
			return `<div class="tb-cap">${__("Drag onto the message, or click")}</div>
				<div class="tb-palette">${this.lib.palette.map((k) => `<button class="tb-pal" draggable="true" data-type="${k}"><span class="g">${GLYPH[k]}</span>${LABEL[k]}</button>`).join("")}</div>
				<div class="tb-cap" style="margin-top:6px">${__("Saved sections")}</div>
				<div class="tb-list">${sections.map((s, i) => `<div class="tb-row" style="flex-wrap:nowrap"><button class="tb-listbtn tb-sec" style="flex:1" data-i="${i}">${e(s.name)}</button>
					${s.builtin || !this.manage ? "" : `<button class="tb-btn sm ghost tb-secdel" data-i="${i}" aria-label="${__("Delete section")}">${icon("trash", 12)}</button>`}</div>`).join("")}</div>
				<div class="tb-muted">${__("Select a block, then choose Save as section on it to keep it for other emails.")}</div>`;
		}

		fields_html() {
			const groups = {};
			this.lib.fields.forEach((f) => { (groups[f.group] = groups[f.group] || []).push(f); });
			return `<label class="tb-cap" for="tbfs">${__("Personalization fields")}</label>
				<input id="tbfs" class="form-control tb-fsearch" placeholder="${__("Search fields")}">
				${Object.entries(groups).map(([g, fs]) => `<div class="tb-fgroup"><div class="tb-lbl" style="margin-top:8px">${e(__(g))}</div><div class="tb-list">
					${fs.map((f) => `<button class="tb-fieldbtn tb-field" data-key="${e(f.key)}" data-fb="${e(f.fallback)}" title="${e(f.label)}: ${e(f.sample)}">{{${e(f.key)}${f.fallback ? "|" + e(f.fallback) : ""}}}</button>`).join("")}</div></div>`).join("")}
				<p class="tb-muted">${__("Click a field to put it where your cursor is. The word after the bar is the fallback, used when a person has no value, so nobody gets a blank greeting.")}</p>`;
		}

		starters_html() {
			const list = this.lib.starters.filter((s) => s.channels.includes(this.tpl.channel));
			return `<div class="tb-cap">${__("Start from a template")}</div><div class="tb-list">${list.map((s) => `<button class="tb-listbtn tb-start" data-id="${e(s.id)}"
				style="display:flex;flex-direction:column;gap:2px"><b>${e(s.name)}</b><span class="tb-muted">${e(s.meta)}</span></button>`).join("")
				|| `<div class="tb-muted">${__("No starters for this channel yet.")}</div>`}</div>`;
		}

		filter_fields(q) {
			const term = (q || "").toLowerCase();
			this.$left.find(".tb-field").each((_, el) => $(el).toggle(!term || el.textContent.toLowerCase().includes(term) || (el.title || "").toLowerCase().includes(term)));
		}

		insert_field(key, fallback) {
			const token = fallback ? `{{${key}|${fallback}}}` : `{{${key}}}`;
			const el = this.last_input && document.body.contains(this.last_input) && this.last_input.tagName ? this.last_input : null;
			if (!el || !/^(INPUT|TEXTAREA)$/.test(el.tagName) || el.type === "number") {
				return frappe.show_alert({ message: __("Click into the text first, then choose a field."), indicator: "orange" });
			}
			el.focus();
			el.setRangeText(token, el.selectionStart ?? el.value.length, el.selectionEnd ?? el.value.length, "end");
			el.dispatchEvent(new Event("input", { bubbles: true }));
		}

		apply_starter(id) {
			frappe.confirm(__("Replace what you have with this starter?"), () => {
				frappe.xcall(API + "starter", { starter_id: id, channel: this.tpl.channel }).then((r) => {
					if (!r) return frappe.show_alert({ message: __("That starter has no {0} version.", [this.tpl.channel]), indicator: "orange" });
					this.undo = clone(this.c);
					this.c = r.content;
					this.res = r.result;
					this.sel = null;
					this.touch();
					this.paint_main();
					this.paint_right();
				});
			});
		}

		// Email --------------------------------------------------------------------

		add_block(type, at) {
			if (!this.manage) return;
			const blocks = this.c.blocks;
			const index = at == null ? (this.sel == null ? blocks.length : this.sel + 1) : at;
			blocks.splice(index, 0, clone(this.lib.new_blocks[type]));
			this.sel = index;
			this.touch();
			this.paint_main();
			this.check();
		}

		add_section(i) {
			const s = this.lib.sections[Number(i)];
			if (!s || !this.manage) return;
			const index = this.sel == null ? this.c.blocks.length : this.sel + 1;
			this.c.blocks.splice(index, 0, ...clone(s.blocks));
			this.sel = index;
			this.touch();
			this.paint_main();
			this.check();
		}

		delete_section(i) {
			const s = this.lib.sections[Number(i)];
			if (!s || s.builtin) return;
			frappe.confirm(__("Delete the section “{0}”?", [s.name]), () => frappe.xcall(API + "delete_section", { section: s.id }).then(() => this.load().then(() => this.paint_left())));
		}

		save_section(i) {
			frappe.prompt([{ fieldname: "name", fieldtype: "Data", label: __("Section name"), reqd: 1 }], (v) =>
				frappe.xcall(API + "save_section", { section_name: v.name, blocks: JSON.stringify([this.c.blocks[i]]) }).then(() => {
					frappe.show_alert({ message: __("Saved. Find it under Saved sections."), indicator: "green" });
					return this.load().then(() => this.paint_left());
				}), __("Save as section"), __("Save"));
		}

		move_block(i, d) {
			const j = i + d;
			if (j < 0 || j >= this.c.blocks.length) return;
			[this.c.blocks[i], this.c.blocks[j]] = [this.c.blocks[j], this.c.blocks[i]];
			this.sel = j;
			this.touch();
			this.paint_main();
			this.check();
		}

		rewrite_block(i) {
			const block = this.c.blocks[i];
			if (!this.lib.ai) return frappe.msgprint(__("Turn on AI in Sales Agent Settings to rewrite with AI."));
			frappe.prompt([{ fieldname: "how", fieldtype: "Select", label: __("How"), reqd: 1, options: AI_EDITS.map(([l]) => l).join("\n"), default: AI_EDITS[0][0] }], (v) => {
				const instruction = AI_EDITS.find(([l]) => l === v.how)[1];
				frappe.xcall(API + "ai_edit", { channel: "Email", text: block.text, instruction, language: this.tpl.language }).then((text) => {
					block.text = text;
					this.touch();
					this.paint_main();
					this.check();
				});
			}, __("Rewrite with AI"), __("Rewrite"));
		}

		paint_main() {
			const ch = this.tpl.channel;
			if (ch === "Email") this.paint_email();
			else if (ch === "SMS") this.paint_sms_form();
			else if (ch === "WhatsApp") this.paint_wa_form();
			else this.paint_li_form();
			this.paint_issues_box();
		}

		paint_email() {
			const c = this.c;
			const manage = this.manage;
			const previews = this.res.previews || [];
			const blocks = c.blocks.map((b, i) => `<div class="tb-drop" data-at="${i}"></div>
				<div class="tb-blockwrap ${this.sel === i ? "sel" : ""} ${b.type === "dynamic" ? "dyn" : ""}" data-i="${i}">
					<span class="tb-kind">${e(LABEL[b.type] || b.type)}</span>
					${manage ? `<div class="tb-tools">
						<button data-a="up" aria-label="${__("Move up")}" ${i === 0 ? "disabled" : ""}>${icon("up")}</button>
						<button data-a="down" aria-label="${__("Move down")}" ${i === c.blocks.length - 1 ? "disabled" : ""}>${icon("down")}</button>
						<button data-a="dup" aria-label="${__("Duplicate block")}">${icon("copy")}</button>
						${["heading", "text"].includes(b.type) ? `<button data-a="ai" aria-label="${__("Rewrite with AI")}">${icon("spark")}</button>` : ""}
						<button data-a="sec" aria-label="${__("Save as section")}">${icon("save")}</button>
						<button data-a="del" aria-label="${__("Delete block")}">${icon("trash")}</button></div>` : ""}
					<div class="tb-blockview" role="button" tabindex="0" aria-label="${e(LABEL[b.type] || b.type)}">${previews[i] || `<div class="tb-muted">…</div>`}</div>
					${this.sel === i && manage ? this.block_editor(i, b) : ""}</div>`).join("");
			this.$main.html(`<section class="tb-card" aria-label="${__("Envelope")}"><div class="tb-grid2">
					<div style="grid-column: span 2"><label class="tb-lbl" for="tbsubj">${__("Subject line")} <span class="tb-muted tb-subjlen">· ${(c.subject || "").length} ${__("characters")}</span></label>
						<input id="tbsubj" class="form-control tb-env" data-k="subject" value="${e(c.subject)}" ${manage ? "" : "disabled"}></div>
					<div><label class="tb-lbl" for="tbpre">${__("Preheader")}</label>
						<input id="tbpre" class="form-control tb-env" data-k="preheader" value="${e(c.preheader)}" placeholder="${__("Shown after the subject in the inbox")}" ${manage ? "" : "disabled"}></div>
					<div><label class="tb-lbl">${__("From")}</label><div class="tb-muted" style="padding-top:8px">${__("Your company sender, set in Integrations")}</div></div></div></section>
				<div class="tb-stage"><article class="tb-mail ${this.device === "mobile" ? "mobile" : ""}" aria-label="${__("Email preview")}">
					${blocks}<div class="tb-drop" data-at="${c.blocks.length}"></div>
					${manage ? `<div class="tb-dropend" data-at="${c.blocks.length}">${__("Drag a block here, or click one on the left")}</div>` : ""}
					<div class="tb-footnote">${__("Added automatically when it is sent: your business name and address, and an unsubscribe link.")}</div></article></div>`);
			this.bind_email();
		}

		bind_email() {
			const $m = this.$main;
			$m.find(".tb-env").on("input", (ev) => { this.c[ev.currentTarget.dataset.k] = ev.currentTarget.value; $m.find(".tb-subjlen").text(`· ${(this.c.subject || "").length} ${__("characters")}`); this.touch(); })
				.on("change", () => this.paint_subjects());
			$m.find(".tb-blockview").on("click", (ev) => { this.sel = Number($(ev.currentTarget).closest(".tb-blockwrap").data("i")); this.paint_main(); });
			$m.find(".tb-tools button").on("click", (ev) => {
				ev.stopPropagation();
				const i = Number($(ev.currentTarget).closest(".tb-blockwrap").data("i"));
				const a = ev.currentTarget.dataset.a;
				if (a === "up") this.move_block(i, -1);
				else if (a === "down") this.move_block(i, 1);
				else if (a === "dup") { this.c.blocks.splice(i + 1, 0, clone(this.c.blocks[i])); this.sel = i + 1; this.touch(); this.paint_main(); this.check(); }
				else if (a === "ai") this.rewrite_block(i);
				else if (a === "sec") this.save_section(i);
				else if (a === "del") { this.c.blocks.splice(i, 1); this.sel = null; this.touch(); this.paint_main(); this.check(); }
			});
			$m.find(".tb-drop, .tb-dropend").on("dragover", (ev) => { ev.preventDefault(); $(ev.currentTarget).addClass("over"); })
				.on("dragleave", (ev) => $(ev.currentTarget).removeClass("over"))
				.on("drop", (ev) => {
					ev.preventDefault();
					$(ev.currentTarget).removeClass("over");
					const data = ev.originalEvent.dataTransfer.getData("text/plain") || "";
					if (data.startsWith("rsa-block:")) this.add_block(data.slice(10), Number(ev.currentTarget.dataset.at));
				});
			this.bind_block_editor();
		}

		block_editor(i, b) {
			const input = (key, label, value, area) => `<div><label class="tb-lbl">${e(label)}</label>${area
				? `<textarea class="form-control tb-in" data-bi="${i}" data-bf="${key}" rows="3">${e(value)}</textarea>`
				: `<input class="form-control tb-in" data-bi="${i}" data-bf="${key}" value="${e(value)}">`}</div>`;
			const forms = {
				heading: () => input("text", __("Heading"), b.text) + `<div><label class="tb-lbl">${__("Size")}</label><select class="form-control tb-in" data-bi="${i}" data-bf="level">
					<option value="1" ${String(b.level) === "1" ? "selected" : ""}>${__("Large")}</option><option value="2" ${String(b.level) !== "1" ? "selected" : ""}>${__("Medium")}</option></select></div>`,
				text: () => input("text", __("Paragraphs (a blank line starts a new one)"), b.text, true),
				image: () => input("src", __("Image address (https://)"), b.src) + input("alt", __("Alt text: describe the image"), b.alt) + input("url", __("Link when clicked (optional)"), b.url),
				button: () => input("label", __("Button label"), b.label) + input("url", __("Link (https://)"), b.url),
				columns: () => `<div class="tb-grid2">${input("left", __("Left column"), b.left, true)}${input("right", __("Right column"), b.right, true)}</div>`,
				divider: () => `<div class="tb-muted">${__("A thin line between sections.")}</div>`,
				spacer: () => input("height", __("Height in pixels"), b.height),
				product: () => input("title", __("Product name"), b.title) + input("text", __("Short description"), b.text, true) + `<div class="tb-grid2">${input("price", __("Price"), b.price)}${input("label", __("Button label"), b.label)}</div>`
					+ input("url", __("Button link (https://)"), b.url) + input("image", __("Image address (https://)"), b.image) + input("alt", __("Image alt text"), b.alt),
				signature: () => `<div class="tb-grid2">${input("closing", __("Closing line"), b.closing)}${input("name", __("Name"), b.name)}${input("title", __("Title"), b.title)}${input("company", __("Company"), b.company)}${input("phone", __("Phone"), b.phone)}${input("email", __("Email"), b.email)}</div>`,
				dynamic: () => `<div class="tb-note">${__("Different content for different people. The first rule that matches is shown; everyone else sees the fallback.")}</div>`
					+ (b.rules || []).map((r, j) => `<div class="tb-card" style="padding:10px"><div class="tb-rule">
						<select class="form-control tb-in" data-bi="${i}" data-bj="${j}" data-bk="field">${this.lib.fields.map((f) => `<option value="${e(f.key)}" ${f.key === r.field ? "selected" : ""}>${e(f.label)}</option>`).join("")}</select>
						<select class="form-control tb-in" data-bi="${i}" data-bj="${j}" data-bk="op">${OPS.map(([v, l]) => `<option value="${v}" ${v === r.op ? "selected" : ""}>${l}</option>`).join("")}</select>
						<input class="form-control tb-in" data-bi="${i}" data-bj="${j}" data-bk="value" value="${e(r.value)}" placeholder="${__("value")}" ${["not_empty", "empty"].includes(r.op) ? "disabled" : ""}>
						<button class="tb-btn sm ghost tb-rdel" data-bi="${i}" data-bj="${j}" aria-label="${__("Remove rule")}">${icon("trash", 12)}</button></div>
						<textarea class="form-control tb-in" style="margin-top:6px" rows="2" data-bi="${i}" data-bj="${j}" data-bk="text" placeholder="${__("What these people see")}">${e(r.text)}</textarea></div>`).join("")
					+ `<button class="tb-btn sm tb-radd" data-bi="${i}" style="align-self:flex-start">${__("Add rule")}</button>` + input("fallback", __("Everyone else sees (fallback)"), b.fallback, true),
				social: () => (b.links || []).map((l, j) => `<div class="tb-row" style="flex-wrap:nowrap"><input class="form-control tb-in" data-bi="${i}" data-bj="${j}" data-bk="label" value="${e(l.label)}" placeholder="${__("Name")}" style="max-width:130px">
					<input class="form-control tb-in" data-bi="${i}" data-bj="${j}" data-bk="url" value="${e(l.url)}" placeholder="https://"><button class="tb-btn sm ghost tb-ldel" data-bi="${i}" data-bj="${j}" aria-label="${__("Remove link")}">${icon("trash", 12)}</button></div>`).join("")
					+ `<button class="tb-btn sm tb-ladd" data-bi="${i}" style="align-self:flex-start">${__("Add link")}</button>`,
			};
			return `<div class="tb-blockeditor" role="group" aria-label="${e(LABEL[b.type] || b.type)}">${(forms[b.type] || (() => ""))()}</div>`;
		}

		bind_block_editor() {
			const $m = this.$main;
			$m.find(".tb-in").on("input change", (ev) => {
				const el = ev.currentTarget;
				const block = this.c.blocks[Number(el.dataset.bi)];
				if (!block) return;
				const value = el.value;
				if (el.dataset.bj !== undefined) {
					const list = block.rules || block.links;
					list[Number(el.dataset.bj)][el.dataset.bk] = value;
					if (el.dataset.bk === "op" && ev.type === "change") this.paint_main();
				} else block[el.dataset.bf] = el.dataset.bf === "level" ? Number(value) : value;
				this.touch();
			});
			$m.find(".tb-radd").on("click", (ev) => { const b = this.c.blocks[Number(ev.currentTarget.dataset.bi)]; (b.rules = b.rules || []).push({ field: "industry", op: "contains", value: "", text: "" }); this.touch(); this.paint_main(); });
			$m.find(".tb-rdel").on("click", (ev) => { this.c.blocks[Number(ev.currentTarget.dataset.bi)].rules.splice(Number(ev.currentTarget.dataset.bj), 1); this.touch(); this.paint_main(); this.check(); });
			$m.find(".tb-ladd").on("click", (ev) => { const b = this.c.blocks[Number(ev.currentTarget.dataset.bi)]; (b.links = b.links || []).push({ label: "", url: "https://" }); this.touch(); this.paint_main(); });
			$m.find(".tb-ldel").on("click", (ev) => { this.c.blocks[Number(ev.currentTarget.dataset.bi)].links.splice(Number(ev.currentTarget.dataset.bj), 1); this.touch(); this.paint_main(); this.check(); });
		}

		paint_email_previews() {
			const previews = this.res.previews || [];
			this.$main.find(".tb-blockwrap").each((_, el) => {
				const i = Number(el.dataset.i);
				if (previews[i] != null) $(el).find(".tb-blockview").html(previews[i]);
			});
		}

		// SMS -----------------------------------------------------------------------

		paint_sms_form() {
			const c = this.c;
			const manage = this.manage;
			this.$main.html(`<div class="tb-split"><section class="tb-card" aria-label="${__("SMS content")}">
				<div class="tb-row" style="justify-content:space-between"><b>${__("SMS template")}</b><span class="tb-pill ok tb-smsstate"></span></div>
				<div class="tb-grid2"><div><label class="tb-lbl" for="tbsmsk">${__("Opt-out keyword")}</label><input id="tbsmsk" class="form-control tb-sms" data-k="keyword" value="${e(c.keyword)}" ${manage ? "" : "disabled"}></div>
					<div><label class="tb-lbl" for="tbsmsw">${__("Sending hours")}</label><input id="tbsmsw" class="form-control tb-sms" data-k="window" value="${e(c.window)}" placeholder="09:00-21:00" ${manage ? "" : "disabled"}></div></div>
				<label class="tb-lbl" for="tbsmst">${__("Message")}</label>
				<textarea id="tbsmst" class="form-control tb-sms" data-k="text" rows="6" ${manage ? "" : "disabled"}>${e(c.text)}</textarea>
				<div class="tb-counter tb-smscount"></div>
				<div class="tb-row"><button class="tb-btn sm tb-gofields">+ ${__("Field")}</button>
					${manage ? `<button class="tb-btn sm ai tb-aishort">${__("AI: make it shorter")}</button><button class="tb-btn sm ai tb-aibn">${__("AI: translate to Bangla")}</button>` : ""}</div>
				<div class="tb-muted">${__("Links are shortened and tracked automatically when the message is sent. The sender ID comes from your SMS provider in Integrations. Replies land in Conversations.")}</div></section>
				<div class="tb-phone sms" aria-label="${__("Phone preview")}"><span class="who">${__("Your sender ID")}</span><div class="tb-bubble tb-smsbubble"></div></div></div>`);
			this.$main.find(".tb-sms").on("input", (ev) => { this.c[ev.currentTarget.dataset.k] = ev.currentTarget.value; this.touch(); });
			this.$main.find(".tb-gofields").on("click", () => { this.left = "fields"; this.paint_left(); });
			this.$main.find(".tb-aishort").on("click", () => this.ai_text("text", "Make it shorter, keeping the opt-out line.", "SMS"));
			this.$main.find(".tb-aibn").on("click", () => this.ai_text("text", "Translate it to natural Bangla, keeping the opt-out line and merge fields.", "SMS"));
			this.paint_sms();
		}

		paint_sms() {
			const r = this.res;
			const parts = r.parts || 0;
			this.$main.find(".tb-smscount").html(`<span><b class="${parts > 3 ? "bad" : ""}">${r.chars || 0}</b> ${__("characters")} · ${parts} ${__("part(s)")} · ${e(r.encoding || "")}</span>
				<span>${__("{0} per message ({1} when split)", r.encoding === "UCS-2" ? ["70", "67"] : ["160", "153"])}</span>`);
			this.$main.find(".tb-smsstate").text(parts <= 2 && (r.issues || []).length === 0 ? __("Ready to send") : __("Needs attention")).toggleClass("ok", parts <= 2 && (r.issues || []).length === 0).toggleClass("warn", !(parts <= 2 && (r.issues || []).length === 0));
			this.$main.find(".tb-smsbubble").text(r.sample || "");
		}

		ai_text(key, instruction, channel) {
			if (!this.lib.ai) return frappe.msgprint(__("Turn on AI in Sales Agent Settings to use AI."));
			frappe.xcall(API + "ai_edit", { channel, text: this.c[key], instruction, language: this.tpl.language }).then((text) => {
				this.undo = clone(this.c);
				this.c[key] = text;
				this.touch();
				this.paint_main();
				this.check();
				this.paint_right();
			});
		}

		// WhatsApp ------------------------------------------------------------------

		paint_wa_form() {
			const c = this.c;
			const manage = this.manage;
			const dis = manage ? "" : "disabled";
			const btn = (b, i) => `<div class="tb-card" style="padding:8px"><div class="tb-row" style="flex-wrap:nowrap">
				<select class="form-control tb-wab" data-i="${i}" data-k="kind" style="max-width:130px" ${dis}><option value="quick" ${b.kind === "quick" ? "selected" : ""}>${__("Quick reply")}</option><option value="url" ${b.kind === "url" ? "selected" : ""}>${__("Link")}</option><option value="phone" ${b.kind === "phone" ? "selected" : ""}>${__("Phone")}</option></select>
				<input class="form-control tb-wab" data-i="${i}" data-k="label" value="${e(b.label)}" placeholder="${__("Button label")}" ${dis}>
				${b.kind === "url" ? `<input class="form-control tb-wab" data-i="${i}" data-k="url" value="${e(b.url)}" placeholder="https://" ${dis}>` : ""}
				${b.kind === "phone" ? `<input class="form-control tb-wab" data-i="${i}" data-k="phone" value="${e(b.phone)}" placeholder="+8801…" ${dis}>` : ""}
				${manage ? `<button class="tb-btn sm ghost tb-wadel" data-i="${i}" aria-label="${__("Remove button")}">${icon("trash", 12)}</button>` : ""}</div></div>`;
			this.$main.html(`<div class="tb-split"><section class="tb-card" aria-label="${__("WhatsApp template")}">
				<div class="tb-row" style="justify-content:space-between"><b>${__("WhatsApp Business template")}</b><span class="tb-pill warn">${this.tpl.whatsapp_template ? __("Submitted to Meta") : __("Needs Meta approval")}</span></div>
				<div class="tb-grid2"><div><label class="tb-lbl" for="tbwacat">${__("Category")}</label><select id="tbwacat" class="form-control tb-wa" data-k="category" ${dis}>
					${["Marketing", "Utility"].map((o) => `<option ${c.category === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>
					<div><label class="tb-lbl">${__("Template name")}</label><div class="tb-muted" style="padding-top:8px">${e(this.tpl.template_name)}</div></div></div>
				<div><span class="tb-lbl">${__("Header")}</span><div class="tb-seg">${["None", "Text", "Image", "Document"].map((h) => `<button class="tb-wah ${c.header_type === h ? "on" : ""}" data-h="${h}" ${dis}>${__(h)}</button>`).join("")}</div>
					${c.header_type !== "None" ? `<input class="form-control tb-wa" style="margin-top:6px" data-k="header" value="${e(c.header)}" placeholder="${c.header_type === "Text" ? __("Header text (no merge fields)") : __("https:// address of a sample for Meta to review")}" ${dis}>` : ""}</div>
				<div><label class="tb-lbl" for="tbwabody">${__("Body")}</label><textarea id="tbwabody" class="form-control tb-wa" data-k="body" rows="5" ${dis}>${e(c.body)}</textarea>
					<div class="tb-counter"><span class="tb-wacount"></span><span>${__("Merge fields become Meta variables {{1}}, {{2}}")}</span></div></div>
				<div class="tb-wasamples"></div>
				<div><label class="tb-lbl" for="tbwaft">${__("Footer")}</label><input id="tbwaft" class="form-control tb-wa" data-k="footer" value="${e(c.footer)}" ${dis}></div>
				<div><div class="tb-row" style="justify-content:space-between"><span class="tb-lbl">${__("Buttons")}</span>
					${manage && c.buttons.length < this.lib.limits.wa_buttons ? `<button class="tb-btn sm tb-waadd">+ ${__("Add button")}</button>` : ""}</div>
					<div class="tb-list">${c.buttons.map(btn).join("") || `<div class="tb-muted">${__("No buttons.")}</div>`}</div></div>
				<div class="tb-row"><button class="tb-btn sm tb-gofields">+ ${__("Field")}</button>
					${manage ? `<button class="tb-btn sm ai tb-aishort">${__("AI: make it shorter")}</button><button class="tb-btn sm ai tb-aibn">${__("AI: translate to Bangla")}</button>` : ""}</div>
				<div class="tb-muted">${__("When someone taps a button, the reply lands in Conversations, where the AI drafts an answer for you to approve.")}</div></section>
				<div class="tb-phone wa" aria-label="${__("WhatsApp preview")}"><div class="tb-wabubble"></div></div></div>`);
			const $m = this.$main;
			$m.find(".tb-wa").on("input change", (ev) => { c[ev.currentTarget.dataset.k] = ev.currentTarget.value; this.touch(); });
			$m.find(".tb-wah").on("click", (ev) => { c.header_type = ev.currentTarget.dataset.h; if (c.header_type === "None") c.header = ""; this.touch(); this.paint_main(); this.check(); });
			$m.find(".tb-waadd").on("click", () => { c.buttons.push({ kind: "quick", label: "", url: "", phone: "" }); this.touch(); this.paint_main(); });
			$m.find(".tb-wadel").on("click", (ev) => { c.buttons.splice(Number(ev.currentTarget.dataset.i), 1); this.touch(); this.paint_main(); this.check(); });
			$m.find(".tb-wab").on("input change", (ev) => {
				const i = Number(ev.currentTarget.dataset.i);
				c.buttons[i][ev.currentTarget.dataset.k] = ev.currentTarget.value;
				if (ev.currentTarget.dataset.k === "kind" && ev.type === "change") this.paint_main();
				this.touch();
			});
			$m.find(".tb-gofields").on("click", () => { this.left = "fields"; this.paint_left(); });
			$m.find(".tb-aishort").on("click", () => this.ai_text("body", "Make it shorter, keeping the merge fields and the meaning.", "WhatsApp"));
			$m.find(".tb-aibn").on("click", () => this.ai_text("body", "Translate it to natural Bangla, keeping the merge fields.", "WhatsApp"));
			this.wa_params_key = null;
			this.paint_wa();
		}

		paint_wa() {
			const r = this.res;
			const c = this.c;
			const params = r.params || [];
			this.$main.find(".tb-wacount").text(`${(c.body || "").length} / ${this.lib.limits.wa_body}`);
			const key = params.join(",");
			if (key !== this.wa_params_key) {
				this.wa_params_key = key;
				const sample = (p) => (c.samples || {})[p] ?? (this.lib.fields.find((f) => f.key === p) || {}).sample ?? "";
				this.$main.find(".tb-wasamples").html(params.length ? `<div class="tb-card" style="background:var(--tb-bg)"><span class="tb-lbl">${__("Sample values: Meta reviews these")}</span>
					<div class="tb-grid2">${params.map((p, i) => `<div><label class="tb-muted">{{${i + 1}}} → ${e(p)}</label><input class="form-control tb-wasam" data-p="${e(p)}" value="${e(sample(p))}" ${this.manage ? "" : "disabled"}></div>`).join("")}</div></div>` : "");
				this.$main.find(".tb-wasam").on("input", (ev) => { (c.samples = c.samples || {})[ev.currentTarget.dataset.p] = ev.currentTarget.value; this.touch(); });
			}
			const header = c.header_type === "Text" ? `<div style="font-weight:700;margin-bottom:6px">${e(r.sample_header || "")}</div>`
				: c.header_type === "None" ? "" : `<div class="hdr">${c.header_type === "Image" ? __("[HEADER IMAGE]") : __("[DOCUMENT]")}</div>`;
			this.$main.find(".tb-wabubble").replaceWith(`<div class="tb-wabubble" style="display:flex;flex-direction:column;gap:6px"><div class="tb-bubble">${header}${e(r.sample || "")}${c.footer ? `<div class="ft">${e(c.footer)}</div>` : ""}</div>
				${c.buttons.map((b) => `<span class="tb-wabtn">${e(b.label || "…")}</span>`).join("")}</div>`);
		}

		// LinkedIn ------------------------------------------------------------------

		paint_li_form() {
			const c = this.c;
			const dis = this.manage ? "" : "disabled";
			this.$main.html(`<section class="tb-card" style="max-width:680px;display:flex;flex-direction:column;gap:10px" aria-label="${__("LinkedIn message")}">
				<b>${__("LinkedIn message")}</b>
				<div class="tb-note">${__("The agent does not send LinkedIn messages. As a campaign step it creates a task for a person, with this message ready to paste.")}</div>
				<label class="tb-lbl" for="tblis">${__("Subject")}</label><input id="tblis" class="form-control tb-li" data-k="subject" value="${e(c.subject)}" ${dis}>
				<label class="tb-lbl" for="tblit">${__("Message")}</label><textarea id="tblit" class="form-control tb-li" data-k="text" rows="8" ${dis}>${e(c.text)}</textarea>
				<div class="tb-counter"><span class="tb-licount"></span></div>
				<div class="tb-row"><button class="tb-btn sm tb-gofields">+ ${__("Field")}</button>${this.manage ? `<button class="tb-btn sm ai tb-aishort">${__("AI: make it shorter")}</button>` : ""}</div></section>`);
			this.$main.find(".tb-li").on("input", (ev) => { this.c[ev.currentTarget.dataset.k] = ev.currentTarget.value; this.touch(); });
			this.$main.find(".tb-gofields").on("click", () => { this.left = "fields"; this.paint_left(); });
			this.$main.find(".tb-aishort").on("click", () => this.ai_text("text", "Make it shorter and more personal.", "LinkedIn"));
			this.paint_li();
		}

		paint_li() {
			this.$main.find(".tb-licount").text(`${(this.c.text || "").length} / 1900`);
		}

		// Right panel: the AI, what the agent does, and the checks ---------------

		paint_right() {
			const c = this.c;
			const ai = c.ai || (c.ai = { brief: "", goal: "", tone: "Friendly" });
			const manage = this.manage;
			const actions = [
				["personalize", __("Personalize each message from CRM data"), true, ""],
				["handoff", __("Hand off hot replies to the record owner"), false, __("Always on: an interested reply creates a task for the owner.")],
				["besttime", __("Send at each contact’s best time"), false, __("Not available yet. Use the sending window in Campaign Studio.")],
				["followup", __("Follow up automatically if no reply"), false, __("Add a later step to the campaign, with the days to wait.")],
			];
			this.$right.html(`<div class="tb-ai"><div class="badge">${icon("spark", 18)}</div><div><b style="font-size:15px">${__("AI drafting")}</b><div class="tb-muted">${__("Writes from your approved facts only")}</div></div></div>
				<div><label class="tb-lbl" for="tbbrief">${__("What should this message achieve?")}</label>
					<textarea id="tbbrief" class="form-control tb-brief" rows="3" ${manage ? "" : "disabled"}>${e(ai.brief)}</textarea></div>
				<div class="tb-grid2"><div><label class="tb-lbl" for="tbgoal">${__("Goal")}</label><select id="tbgoal" class="form-control tb-goal" ${manage ? "" : "disabled"}>
					<option value=""></option>${GOALS.map((g) => `<option ${ai.goal === g ? "selected" : ""}>${g}</option>`).join("")}</select></div>
					<div><label class="tb-lbl">${__("Language")}</label><div class="tb-muted" style="padding-top:8px">${e(this.tpl.language)}</div></div></div>
				<div><span class="tb-lbl">${__("Tone")}</span><div class="tb-tones">${TONES.map((t) => `<button class="tb-tone ${ai.tone === t ? "on" : ""}" data-t="${t}" ${manage ? "" : "disabled"}>${__(t)}</button>`).join("")}</div></div>
				<button class="tb-btn ai tb-draft" ${manage && this.lib.ai ? "" : "disabled"} style="height:42px;display:flex;align-items:center;justify-content:center;gap:8px">${icon("spark", 16)}${this.draft_label || __("Draft with AI")}</button>
				${this.lib.ai ? "" : `<div class="tb-muted">${__("Turn on AI in Sales Agent Settings to draft with AI.")}</div>`}
				${this.undo ? `<button class="tb-btn sm ghost tb-undo">${__("Undo the last AI change")}</button>` : ""}
				<div class="tb-subjects"></div>
				<div><div class="tb-cap" style="margin-bottom:6px">${__("Agent actions on send")}</div>${actions.map(([k, label, avail, note]) => `<div class="tb-switch"><span>${label}${note ? `<div class="tb-muted">${note}</div>` : ""}</span>
					${avail ? `<button class="track tb-act ${c.actions[k] !== false ? "on" : ""}" data-k="${k}" aria-pressed="${c.actions[k] !== false}" aria-label="${label}" ${manage ? "" : "disabled"}><i></i></button>`
						: `<button class="track ${k === "handoff" ? "on" : ""}" disabled aria-label="${label}"><i></i></button>`}</div>`).join("")}</div>
				<div><div class="tb-cap" style="margin-bottom:6px">${__("Pre-send checks")}</div><div class="tb-checks tb-list"></div></div>`);
			this.paint_subjects();
			this.paint_right_checks();
			const $r = this.$right;
			$r.find(".tb-brief").on("input", (ev) => { ai.brief = ev.currentTarget.value; this.touch(); });
			$r.find(".tb-goal").on("change", (ev) => { ai.goal = ev.currentTarget.value; this.touch(); });
			$r.find(".tb-tone").on("click", (ev) => { ai.tone = ev.currentTarget.dataset.t; this.touch(); this.paint_right(); });
			$r.find(".tb-act").on("click", (ev) => { const k = ev.currentTarget.dataset.k; c.actions[k] = !(c.actions[k] !== false); this.touch(); this.paint_right(); });
			$r.find(".tb-draft").on("click", () => this.ai_draft());
			$r.find(".tb-undo").on("click", () => { this.c = this.undo; this.undo = null; this.sel = null; this.touch(); this.paint_main(); this.paint_right(); this.check(); });
		}

		paint_right_checks() {
			const checks = this.res.checks || [];
			this.$right.find(".tb-checks").html(checks.map((k) => `<div class="tb-check ${k.ok ? "" : "bad"}"><i>${k.ok ? "✓" : "!"}</i><span>${e(k.label)}</span></div>`).join(""));
		}

		paint_subjects() {
			const box = this.$right.find(".tb-subjects");
			if (this.tpl.channel !== "Email") return box.empty();
			const c = this.c;
			const limit = this.lib.limits.variants;
			const suggestions = this.suggest.filter((s) => s !== c.subject && !c.variants.includes(s));
			box.html(`<div class="tb-variants"><b style="font-size:12px;color:#9A3412">${__("Subject lines · A/B test")}</b>
				<div class="vrow"><span class="vtag">A</span><span class="t">${e(c.subject || __("(no subject yet)"))}</span><span class="tb-pill">${__("Main")}</span></div>
				${c.variants.map((v, i) => `<div class="vrow"><span class="vtag">${"BC"[i]}</span><input class="form-control tb-vin" data-i="${i}" value="${e(v)}" style="height:28px" ${this.manage ? "" : "disabled"}>
					${this.manage ? `<button class="tb-btn sm ghost tb-vdel" data-i="${i}" aria-label="${__("Remove variant")}">${icon("trash", 12)}</button>` : ""}</div>`).join("")}
				${this.manage && c.variants.length < limit ? `<button class="tb-btn sm tb-vadd" style="align-self:flex-start">+ ${__("Add a variant")}</button>` : ""}
				${suggestions.length ? `<b style="font-size:12px;color:#9A3412;margin-top:4px">${__("Suggestions")}</b>${suggestions.map((s, i) => `<div class="vrow"><span class="t">${e(s)}</span>
					<button class="tb-btn sm tb-vuse" data-i="${i}">${__("Use")}</button>${c.variants.length < limit ? `<button class="tb-btn sm tb-vtest" data-i="${i}">${__("Test")}</button>` : ""}</div>`).join("")}` : ""}
				<span class="tb-muted">${__("With a variant, the campaign splits the audience between the subject lines and shows which one opens more.")}</span></div>`);
			box.find(".tb-vin").on("input", (ev) => { c.variants[Number(ev.currentTarget.dataset.i)] = ev.currentTarget.value; this.touch(); });
			box.find(".tb-vdel").on("click", (ev) => { c.variants.splice(Number(ev.currentTarget.dataset.i), 1); this.touch(); this.paint_subjects(); this.check(); });
			box.find(".tb-vadd").on("click", () => { c.variants.push(""); this.touch(); this.paint_subjects(); });
			box.find(".tb-vuse").on("click", (ev) => { c.subject = suggestions[Number(ev.currentTarget.dataset.i)]; this.touch(); this.paint_main(); this.paint_subjects(); });
			box.find(".tb-vtest").on("click", (ev) => { c.variants.push(suggestions[Number(ev.currentTarget.dataset.i)]); this.touch(); this.paint_subjects(); this.check(); });
		}

		ai_draft() {
			const c = this.c;
			const ai = c.ai;
			if (!ai.brief.trim()) return frappe.msgprint(__("Say what the message should achieve, then draft."));
			this.draft_label = __("Drafting…");
			this.paint_right();
			frappe.xcall(API + "ai_draft", { channel: this.tpl.channel, brief: ai.brief, goal: ai.goal, tone: ai.tone || "Friendly", language: this.tpl.language, keyword: c.keyword || "STOP" })
				.then((r) => {
					this.undo = clone(c);
					const next = r.content;
					next.ai = clone(ai);
					next.actions = c.actions;
					this.suggest = [...(next.variants || [])];
					next.variants = [];
					this.c = next;
					this.res = r.result;
					this.sel = null;
					this.draft_label = null;
					this.touch();
					this.paint_main();
					this.paint_right();
				}).catch(() => { this.draft_label = null; this.paint_right(); });
		}

		// Preview, test send -----------------------------------------------------------

		preview_dialog() {
			const t = this.tpl;
			const r = this.res;
			const dialog = new frappe.ui.Dialog({ title: __("Preview: {0}", [t.template_name]), size: "large", fields: [{ fieldname: "body", fieldtype: "HTML" }] });
			const $w = dialog.fields_dict.body.$wrapper;
			if (t.channel === "Email") {
				const doc = `<!doctype html><meta charset="utf-8"><body style="margin:0;background:#f3f4f6">${r.sample_html || ""}<p style="max-width:600px;margin:0 auto;padding:0 24px 24px;color:#888;font:12px Arial">${e(__("Your business name and address, and an unsubscribe link, are added here when it is sent."))}</p></body>`;
				$w.html(`<div class="tb"><div class="tb-row" style="justify-content:space-between;margin-bottom:8px"><span><b>${__("Subject")}:</b> ${e(r.sample_subject || "")}</span>
					<div class="tb-seg"><button class="on" data-w="100%">${__("Desktop")}</button><button data-w="375px">${__("Mobile")}</button></div></div>
					<div style="display:flex;justify-content:center;background:#e3e7ef;padding:12px;border-radius:8px"><iframe sandbox="" title="${__("Email preview")}" style="width:100%;max-width:100%;height:60vh;border:0;background:#fff" srcdoc="${e(doc)}"></iframe></div>
					<div class="tb-muted" style="margin-top:6px">${__("Sample values are used for the merge fields.")}</div></div>`);
				$w.find(".tb-seg button").on("click", (ev) => { $w.find(".tb-seg button").removeClass("on"); $(ev.currentTarget).addClass("on"); $w.find("iframe").css("width", ev.currentTarget.dataset.w); });
			} else {
				const text = t.channel === "LinkedIn" ? `${r.sample_subject ? r.sample_subject + "\n\n" : ""}${r.sample || ""}` : (r.sample || "");
				$w.html(`<div class="tb"><div class="tb-phone ${t.channel === "WhatsApp" ? "wa" : "sms"}" style="margin:0 auto"><div class="tb-bubble">${e(text)}</div>
					${t.channel === "WhatsApp" ? this.c.buttons.map((b) => `<span class="tb-wabtn">${e(b.label)}</span>`).join("") : ""}</div></div>`);
			}
			dialog.show();
		}

		send_test() {
			frappe.confirm(__("Send a test of this email to your own address, with sample values? Nobody else receives it."), () =>
				this.save(true).then(() => frappe.xcall(API + "send_test", { template: this.tpl.name })).then((r) =>
					frappe.show_alert({ message: __("Test sent to {0}", [r.sent_to]), indicator: "green" })));
		}
	}
})();
