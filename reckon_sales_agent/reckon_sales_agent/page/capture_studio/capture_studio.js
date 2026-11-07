// Capture Studio: signup forms (embedded, popup, hosted), saved segments and CSV import.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["capture-studio"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Capture Studio"), single_column: true });
		page.add_inner_button(__("Campaign Studio"), () => frappe.set_route("campaign-studio"));
		page.add_inner_button(__("Automation Studio"), () => frappe.set_route("automation-studio"));
		wrapper.cap = new Capture(page);
	};
	frappe.pages["capture-studio"].on_page_show = (wrapper) => wrapper.cap && wrapper.cap.show();

	const F = "reckon_sales_agent.api_capture.";
	const S = "reckon_sales_agent.api_segments.";
	const V = "reckon_sales_agent.api_verify.";
	const D = "reckon_sales_agent.api_developer.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v) => Number(v || 0).toLocaleString();
	const MANAGER_ROLES = ["Reckon Sales Agent Admin", "Reckon Sales Agent Manager", "Reckon Vendor Superuser", "System Manager"];
	// The server decides who may change anything; this only hides buttons that would be refused.
	const can_manage = () => frappe.session.user === "Administrator" || MANAGER_ROLES.some((role) => frappe.user.has_role(role));
	const TABS = [["forms", __("Forms")], ["segments", __("Segments")], ["import", __("Import")], ["clean", __("Clean list")], ["developers", __("Developers")]];
	const store = {
		get(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (err) { return fallback; } },
		set(key, value) { try { localStorage.setItem(key, value); } catch (err) { /* private window */ } },
	};
	const FIELD_CATALOG = [["email", __("Email")], ["first_name", __("First name")], ["last_name", __("Last name")],
		["phone", __("Phone")], ["business_name", __("Company")], ["city", __("City")], ["industry", __("Industry")]];
	const NEW_FORM = () => ({
		form_name: "", status: "Draft", form_type: "Hosted page", headline: __("Stay in the loop"), description: "", button_label: __("Subscribe"),
		fields: [{ key: "email", label: __("Email"), required: true }, { key: "first_name", label: __("First name"), required: false }],
		consent_text: __("Yes, send me emails. I can unsubscribe at any time."), require_consent: 1, ask_sms: 0, ask_whatsapp: 0,
		double_opt_in: 1, tags: "", thank_you_message: __("Thank you! Please check your email to confirm."), redirect_url: "",
		accent_color: "#4f46e5", allowed_origins: "", popup_trigger: "Delay", popup_delay: 8,
	});
	const copy = (text) => { navigator.clipboard.writeText(text).then(() => frappe.show_alert({ message: __("Copied"), indicator: "green" })); };
	const when = (v) => (v ? frappe.datetime.prettyDate(v) : "");

	class Capture {
		constructor(page) {
			this.page = page;
			this.tab = store.get("cap_tab", "forms");
			this.$root = $(`<div class="cap"><nav class="cap-tabs">${TABS.map(([key, label]) => `<button class="cap-tab" data-tab="${key}">${label}</button>`).join("")}</nav><div class="cap-body"></div></div>`).appendTo(page.main);
			this.$body = this.$root.find(".cap-body");
			this.$root.find(".cap-tab").on("click", (ev) => this.open(ev.currentTarget.dataset.tab));
			this.catalog = null;
		}

		show() { this.open(this.tab); }

		open(tab) {
			this.tab = TABS.some(([key]) => key === tab) ? tab : "forms";
			store.set("cap_tab", this.tab);
			clearTimeout(this.poll);
			this.$body.off();
			this.$root.find(".cap-tab").each((_, node) => $(node).toggleClass("on", node.dataset.tab === this.tab));
			this.$body.html(`<div class="cap-empty">${__("Loading…")}</div>`);
			return this[`tab_${this.tab}`]().catch(() => this.$body.html(`<div class="cap-empty">${__("This could not be loaded.")}</div>`));
		}

		// Forms ---------------------------------------------------------------

		tab_forms() {
			return frappe.xcall(F + "forms").then((rows) => {
				const cards = rows.map((r) => `<div class="cap-card"><div class="cap-bar"><b>${e(r.form_name)}</b><span class="cap-badge ${e(r.status)}">${e(r.status)}</span></div>
					<div class="cap-muted">${e(r.form_type)}${r.double_opt_in ? " · " + __("double opt-in") : ""}</div>
					<div class="cap-num"><div><b>${num(r.submissions)}</b><span>${__("signups")}</span></div><div><b>${num(r.confirmed)}</b><span>${__("confirmed")}</span></div></div>
					<div class="cap-muted">${r.last_submission ? __("Last signup {0}", [when(r.last_submission)]) : __("No signups yet")}</div>
					<div style="margin-top:8px"><button class="btn btn-default btn-xs cap-edit-form" data-name="${e(r.name)}">${can_manage() ? __("Open") : __("View")}</button></div></div>`).join("");
				this.$body.html(`<div class="cap-bar"><span class="cap-muted">${__("Forms collect signups from your website or a page of their own. Each signup is recorded with how they agreed.")}</span>
					${can_manage() ? `<button class="btn btn-primary btn-sm cap-new-form">${__("New form")}</button>` : ""}</div>
					${rows.length ? `<div class="cap-grid">${cards}</div>` : `<div class="cap-card cap-empty">${__("No forms yet. Make one, publish it, and put it on your website or share its page.")}</div>`}`);
				this.$body.find(".cap-new-form").on("click", () => this.form_editor(null));
				this.$body.find(".cap-edit-form").on("click", (ev) => this.form_editor(ev.currentTarget.dataset.name));
			});
		}

		form_editor(name) {
			const load = name ? frappe.xcall(F + "form", { name }) : Promise.resolve(NEW_FORM());
			load.then((data) => {
				const st = { ...NEW_FORM(), ...data };
				this.paint_form(st, name);
			});
		}

		paint_form(st, name) {
			this.$body.off(); // handlers of the form or tab shown before
			const dis = can_manage() ? "" : "disabled";
			const text = (k, label, type = "text") => `<label>${label}<input class="form-control" type="${type}" data-k="${k}" value="${e(st[k])}" ${dis}></label>`;
			const area = (k, label, help) => `<label>${label}<textarea class="form-control" rows="2" data-k="${k}" ${dis}>${e(st[k])}</textarea>${help ? `<span class="cap-muted">${help}</span>` : ""}</label>`;
			const check = (k, label) => `<label class="cap-check"><input type="checkbox" data-k="${k}" ${st[k] ? "checked" : ""} ${dis}>${label}</label>`;
			const opts = (list, cur) => list.map((o) => `<option ${o === cur ? "selected" : ""}>${e(o)}</option>`).join("");
			const rows = FIELD_CATALOG.map(([key, label]) => {
				const f = (st.fields || []).find((x) => x.key === key);
				return `<div data-key="${key}"><input type="checkbox" class="cap-f-on" ${f || key === "email" ? "checked" : ""} ${key === "email" ? "disabled" : dis}>
					<span>${label}</span><input class="form-control input-xs cap-f-label" value="${e(f ? f.label : label)}" ${dis}>
					<label class="cap-check"><input type="checkbox" class="cap-f-req" ${(f && f.required) || key === "email" ? "checked" : ""} ${key === "email" ? "disabled" : dis}>${__("Required")}</label></div>`;
			}).join("");
			const saved = name && st.slug;
			const origin = window.location.origin;
			const script = `<script src="${origin}/assets/reckon_sales_agent/js/rsa_form.js" data-form="${st.slug}"${st.form_type === "Popup" ? ' data-mode="popup"' : ""} defer><\/script>`;
			this.$body.html(`<div class="cap-bar"><button class="btn btn-default btn-sm cap-back">&larr; ${__("All forms")}</button>
				<span>${can_manage() ? `<button class="btn btn-primary btn-sm cap-save">${__("Save")}</button>${name ? `<button class="btn btn-default btn-sm cap-del">${__("Delete")}</button>` : ""}` : ""}</span></div>
				<div class="cap-split"><div class="cap-card cap-form">
					<div class="cap-two">${text("form_name", __("Form name"))}<label>${__("Status")}<select class="form-control" data-k="status" ${dis}>${opts(["Draft", "Published"], st.status)}</select><span class="cap-muted">${__("Only a published form accepts signups.")}</span></label></div>
					<div class="cap-two"><label>${__("Shown as")}<select class="form-control" data-k="form_type" ${dis}>${opts(["Hosted page", "Embedded", "Popup"], st.form_type)}</select></label>${text("accent_color", __("Accent colour"), "color")}</div>
					${text("headline", __("Headline"))}${area("description", __("Short text under the headline"))}${text("button_label", __("Button"))}
					<h4>${__("Fields")}</h4><div class="cap-fields">${rows}</div>
					<h4>${__("Agreement")}</h4>${check("require_consent", __("Visitors must tick the agreement"))}${area("consent_text", __("Agreement text"))}
					${check("ask_sms", __("Also offer an SMS opt-in (adds a phone field)"))}${check("ask_whatsapp", __("Also offer a WhatsApp opt-in (adds a phone field)"))}
					<h4>${__("After they sign up")}</h4>${check("double_opt_in", __("Ask them to confirm by email (recommended). They are not emailed by any campaign until they do."))}
					${text("tags", __("Tags to add"))}<span class="cap-muted">${__("Comma separated. Automations and segments can start from a tag.")}</span>
					${area("thank_you_message", __("Thank-you message"))}${text("redirect_url", __("Go to this address instead (https)"))}
					<div class="cap-two" ${st.form_type === "Popup" ? "" : 'style="display:none"'}><label>${__("Popup opens")}<select class="form-control" data-k="popup_trigger" ${dis}>${opts(["Delay", "Scroll", "Exit intent"], st.popup_trigger)}</select></label>${text("popup_delay", __("Delay (seconds)"), "number")}</div>
					${area("allowed_origins", __("Websites that may show this form"), __("One address per line, e.g. https://www.example.com. Empty means any website."))}
				</div><div><div class="cap-preview"><h4>${__("Preview")}</h4><div class="cap-pf"></div></div>
				${saved ? `<div class="cap-card"><h3>${__("Share it")}</h3>
					<div class="cap-muted">${__("Page of its own")}</div><div class="cap-code"><code>${e(origin)}/f/${e(st.slug)}</code><button class="btn btn-default btn-xs cap-copy" data-text="${e(origin)}/f/${e(st.slug)}">${__("Copy")}</button></div>
					<div class="cap-muted">${__("Put it on your website (paste before the closing body tag)")}</div><div class="cap-code"><code>${e(script)}</code><button class="btn btn-default btn-xs cap-copy" data-text="${e(script)}">${__("Copy")}</button></div>
					<div class="cap-muted">${st.status === "Published" ? "" : __("Publish the form before sharing it.")}</div></div>
					<div class="cap-card"><h3>${__("Recent signups")}</h3>${(st.recent || []).length ? `<table class="cap-table">${st.recent.map((r) => `<tr><td>${e(r.email)}<div class="cap-muted">${e(r.person)}</div></td><td><span class="cap-badge ${r.status === "Unconfirmed" ? "Draft" : "ok"}">${e(r.status)}</span></td><td class="cap-muted">${when(r.at)}</td></tr>`).join("")}</table>` : `<div class="cap-muted">${__("None yet.")}</div>`}</div>` : ""}
				</div></div>`);
			const $b = this.$body;
			const pull = () => {
				$b.find("[data-k]").each((_, el) => {
					const k = el.dataset.k;
					st[k] = el.type === "checkbox" ? (el.checked ? 1 : 0) : (el.type === "number" ? Number(el.value || 0) : el.value);
				});
				st.fields = FIELD_CATALOG.map(([key]) => {
					const $r = $b.find(`.cap-fields [data-key="${key}"]`);
					return $r.find(".cap-f-on").prop("checked") || key === "email" ? { key, label: $r.find(".cap-f-label").val() || key, required: key === "email" || $r.find(".cap-f-req").prop("checked") } : null;
				}).filter(Boolean);
			};
			const preview = () => {
				pull();
				$b.find(".cap-pf").html(`<h3>${e(st.headline)}</h3><p class="cap-muted">${e(st.description)}</p>${st.fields.map((f) => `<label>${e(f.label)}${f.required ? " *" : ""}<input type="text" disabled></label>`).join("")}
					${st.require_consent || st.consent_text ? `<label class="cap-check"><input type="checkbox" disabled>${e(st.consent_text)}</label>` : ""}
					${st.ask_sms ? `<label class="cap-check"><input type="checkbox" disabled>${__("Text me updates (SMS)")}</label>` : ""}${st.ask_whatsapp ? `<label class="cap-check"><input type="checkbox" disabled>${__("Message me on WhatsApp")}</label>` : ""}
					<button type="button" style="background:${e(st.accent_color)}">${e(st.button_label)}</button>`);
				$b.find(".cap-two").has('[data-k="popup_trigger"]').toggle(st.form_type === "Popup");
			};
			$b.on("input change", "[data-k], .cap-fields input", preview);
			preview();
			$b.find(".cap-back").on("click", () => this.open("forms"));
			$b.find(".cap-copy").on("click", (ev) => copy(ev.currentTarget.dataset.text));
			$b.find(".cap-save").on("click", () => { pull(); frappe.xcall(F + "save_form", { data: { ...st, name: name || undefined } }).then((r) => { frappe.show_alert({ message: __("Saved"), indicator: "green" }); this.form_editor(r.name); }); });
			$b.find(".cap-del").on("click", () => frappe.confirm(__("Delete this form? People who signed up stay on your list."), () => frappe.xcall(F + "delete_form", { name }).then(() => this.open("forms"))));
		}

		// Segments ------------------------------------------------------------

		with_catalog() { return this.catalog ? Promise.resolve(this.catalog) : frappe.xcall(S + "catalog").then((c) => (this.catalog = c)); }

		tab_segments() {
			return frappe.xcall(S + "segment_list").then((rows) => {
				const list = rows.map((r) => `<div class="cap-card"><div class="cap-bar"><b>${e(r.segment_name)}</b><span class="cap-badge">${num(r.size)} ${__("people")}</span></div>
					<div class="cap-muted">${e(r.summary)}</div><div class="cap-muted">${r.last_refreshed ? __("Counted {0}", [when(r.last_refreshed)]) : ""}${r.audiences ? " · " + __("used by {0} audience(s)", [r.audiences]) : ""}</div>
					<div style="margin-top:8px"><button class="btn btn-default btn-xs cap-seg-edit" data-name="${e(r.name)}">${can_manage() ? __("Open") : __("View")}</button>
					<button class="btn btn-default btn-xs cap-seg-refresh" data-name="${e(r.name)}">${__("Count again")}</button></div></div>`).join("");
				this.$body.html(`<div class="cap-bar"><span class="cap-muted">${__("A segment is a saved set of rules. It is checked every time it is used, so it is always current. Use it as a campaign audience or to start an automation.")}</span>
					${can_manage() ? `<button class="btn btn-primary btn-sm cap-seg-new">${__("New segment")}</button>` : ""}</div>
					${rows.length ? `<div class="cap-grid">${list}</div>` : `<div class="cap-card cap-empty">${__("No segments yet. Try “opened an email in the last 30 days”.")}</div>`}`);
				this.$body.find(".cap-seg-new").on("click", () => this.segment_editor(null));
				this.$body.find(".cap-seg-edit").on("click", (ev) => this.segment_editor(ev.currentTarget.dataset.name));
				this.$body.find(".cap-seg-refresh").on("click", (ev) => frappe.xcall(S + "refresh_segment", { name: ev.currentTarget.dataset.name }).then(() => this.open("segments")));
			});
		}

		segment_editor(name) {
			Promise.all([this.with_catalog(), name ? frappe.xcall(S + "segment", { name }) : Promise.resolve({ segment_name: "", description: "", match_mode: "All", rules: [{ field: "opened", op: "within", value: 30 }] })])
				.then(([cat, seg]) => this.paint_segment(cat, seg, name));
		}

		paint_segment(cat, seg, name) {
			this.$body.off();
			const dis = can_manage() ? "" : "disabled";
			const by = Object.fromEntries(cat.conditions.map((c) => [c.key, c]));
			const rule_html = (r, i) => {
				const c = by[r.field] || cat.conditions[0];
				const ops = c.ops.map((o) => `<option value="${e(o.op)}" ${o.op === r.op ? "selected" : ""}>${e(o.label)}</option>`).join("");
				const fields = cat.conditions.map((x) => `<option value="${e(x.key)}" ${x.key === r.field ? "selected" : ""}>${e(x.label)}</option>`).join("");
				let value = "";
				if (c.kind === "days") value = r.op === "never" ? "" : `<input class="form-control cap-r-val" type="number" min="0" value="${e(r.value)}" placeholder="${__("days")}" ${dis}>`;
				else if (c.kind === "number") value = `<input class="form-control cap-r-val" type="number" min="0" max="100" value="${e(r.value)}" ${dis}>`;
				else if (c.kind === "choice") value = `<select class="form-control cap-r-val" ${dis}>${c.choices.map((x) => `<option ${x === r.value ? "selected" : ""}>${e(x)}</option>`).join("")}</select>`;
				else if (c.kind === "text") value = `<input class="form-control cap-r-val" list="cap-tags" value="${e(r.value)}" ${dis}>`;
				return `<div class="cap-rule" data-i="${i}"><select class="form-control cap-r-field" ${dis}>${fields}</select><select class="form-control cap-r-op" ${dis}>${ops}</select><div>${value}</div>
					${can_manage() ? `<button class="btn btn-default btn-xs cap-r-del" title="${__("Remove")}">&times;</button>` : ""}</div>`;
			};
			this.$body.html(`<div class="cap-bar"><button class="btn btn-default btn-sm cap-back">&larr; ${__("All segments")}</button><span>${can_manage() ? `<button class="btn btn-primary btn-sm cap-save">${__("Save")}</button>
				${name ? `<button class="btn btn-default btn-sm cap-tag">${__("Tag everyone in it")}</button><button class="btn btn-default btn-sm cap-del">${__("Delete")}</button>` : ""}` : ""}</span></div>
				<div class="cap-split"><div class="cap-card cap-form"><label>${__("Segment name")}<input class="form-control cap-name" value="${e(seg.segment_name)}" ${dis}></label>
				<label>${__("Description")}<input class="form-control cap-desc" value="${e(seg.description || "")}" ${dis}></label>
				<label>${__("People who meet")}<select class="form-control cap-mode" ${dis}>${cat.modes.map((m) => `<option ${m === seg.match_mode ? "selected" : ""}>${m}</option>`).join("")}</select></label>
				<h4>${__("Rules")}</h4><datalist id="cap-tags">${cat.tags.map((t) => `<option value="${e(t.tag)}">`).join("")}</datalist><div class="cap-rules"></div>
				${can_manage() ? `<button class="btn btn-default btn-sm cap-r-add">+ ${__("Add a rule")}</button>` : ""}</div>
				<div class="cap-card"><h3>${__("Who matches now")}</h3><div class="cap-prev cap-muted">${__("Counting…")}</div></div></div>`);
			const $b = this.$body;
			let rules = JSON.parse(JSON.stringify(seg.rules || []));
			const paint_rules = () => $b.find(".cap-rules").html(rules.map(rule_html).join("") || `<div class="cap-muted">${__("Add at least one rule.")}</div>`);
			let timer = null;
			const count = () => {
				clearTimeout(timer);
				timer = setTimeout(() => frappe.xcall(S + "preview", { rules, match_mode: $b.find(".cap-mode").val() }).then((r) => {
					$b.find(".cap-prev").html(r.problems && r.problems.length ? r.problems.map((p) => `<div>${e(p)}</div>`).join("")
						: `<div style="font-size:22px;font-weight:650;color:inherit">${num(r.total)} ${__("people")}</div>${r.sample.map((p) => `<div class="cap-sample">${e(p.label || p.email || p.phone)}${p.email ? " · " + e(p.email) : ""}</div>`).join("")}`);
				}), 450);
			};
			const read = () => {
				rules = $b.find(".cap-rule").map((_, el) => {
					const $r = $(el);
					const rule = { field: $r.find(".cap-r-field").val(), op: $r.find(".cap-r-op").val(), value: $r.find(".cap-r-val").val() };
					return rule;
				}).get();
			};
			paint_rules(); count();
			$b.on("change", ".cap-r-field", (ev) => { read(); const i = $(ev.currentTarget).closest(".cap-rule").data("i"); const c = by[rules[i].field]; rules[i] = { field: rules[i].field, op: c.ops[0].op, value: c.kind === "choice" ? c.choices[0] : (c.kind === "days" ? 30 : "") }; paint_rules(); count(); });
			$b.on("change", ".cap-r-op", (ev) => { read(); paint_rules(); count(); });
			$b.on("input change", ".cap-r-val, .cap-mode", () => { read(); count(); });
			$b.find(".cap-r-add").on("click", () => { read(); rules.push({ field: "opened", op: "within", value: 30 }); paint_rules(); count(); });
			$b.on("click", ".cap-r-del", (ev) => { read(); rules.splice($(ev.currentTarget).closest(".cap-rule").data("i"), 1); paint_rules(); count(); });
			$b.find(".cap-back").on("click", () => this.open("segments"));
			$b.find(".cap-save").on("click", () => { read(); frappe.xcall(S + "save_segment", { data: { name: name || undefined, segment_name: $b.find(".cap-name").val(), description: $b.find(".cap-desc").val(), match_mode: $b.find(".cap-mode").val(), rules } })
				.then((r) => { frappe.show_alert({ message: __("Saved: {0} people", [r.size]), indicator: "green" }); this.open("segments"); }); });
			$b.find(".cap-del").on("click", () => frappe.confirm(__("Delete this segment?"), () => frappe.xcall(S + "delete_segment", { name }).then(() => this.open("segments"))));
			$b.find(".cap-tag").on("click", () => frappe.prompt([{ fieldname: "tags", fieldtype: "Data", label: __("Tags to add (comma separated)"), reqd: 1 }], (v) =>
				frappe.xcall(S + "tag_segment", { name, tags: v.tags }).then((r) => frappe.show_alert({ message: __("{0} of {1} people tagged", [r.changed, r.people]), indicator: "green" })), __("Tag everyone in this segment")));
		}

		// Clean list ----------------------------------------------------------

		tab_clean() {
			return frappe.xcall(V + "summary").then((d) => {
				const c = d.counts, pc = d.percent || {};
				const colors = { Valid: "#0ca30c", Risky: "#d97706", Invalid: "#d03b3b", Unchecked: "#94a3b8" };
				const bar = ["Valid", "Risky", "Invalid", "Unchecked"].map((k) => `<i style="display:block;height:100%;width:${pc[k] || 0}%;background:${colors[k]}" title="${k}: ${pc[k] || 0}%"></i>`).join("");
				const tiles = ["Valid", "Risky", "Invalid", "Unchecked"].map((k) => `<div class="cap-card" style="margin:0"><b style="font-size:22px;color:${colors[k]}">${num(c[k])}</b><div class="cap-muted">${k === "Unchecked" ? __("not checked yet") : __(k.toLowerCase())}</div></div>`).join("");
				const list = (rows, title) => rows.length ? `<div class="cap-card"><h3>${title}</h3><table class="cap-table">${rows.map((r) => `<tr><td>${e(r.email)}<div class="cap-muted">${e(r.person || "")}</div></td><td class="cap-muted">${e(r.note)}</td></tr>`).join("")}</table></div>` : "";
				this.$body.html(`<div class="cap-bar"><span class="cap-muted">${__("Every address is checked before it is emailed: its form, a rule list (disposable, shared mailbox, typo) and whether its domain has a mail server. An invalid address is never emailed by a campaign.")}</span>
					${can_manage() ? `<span><button class="btn btn-primary btn-sm cap-check" data-scope="unchecked">${__("Check new addresses")}</button> <button class="btn btn-default btn-sm cap-check" data-scope="all">${__("Check everyone again")}</button></span>` : ""}</div>
					<div class="cap-card"><div class="cap-bar"><b>${d.total - (c.Unchecked || 0) ? __("{0}% of checked addresses can be delivered", [d.deliverable]) : (d.total ? __("No address has been checked yet") : __("Nothing to check yet"))}</b><span class="cap-muted">${num(d.total)} ${__("addresses")} · ${e(d.provider)}${d.provider_ready ? "" : " (" + __("add the key in Integrations → Email") + ")"}</span></div>
					<div style="display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--cap-soft)">${bar}</div></div>
					<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:12px">${tiles}</div>
					<div class="cap-card cap-form"><h3>${__("Try an address")}</h3><div style="display:flex;gap:8px"><input class="form-control cap-try" placeholder="name@company.com"><button class="btn btn-default btn-sm cap-try-go">${__("Check")}</button></div><div class="cap-try-out cap-muted" style="margin-top:8px"></div></div>
					${list(d.invalid, __("Invalid: never emailed"))}${list(d.risky, __("Risky: emailed, but may not reach a person"))}`);
				this.$body.find(".cap-check").on("click", (ev) => frappe.xcall(V + "check_all", { scope: ev.currentTarget.dataset.scope }).then((n) => frappe.show_alert({ message: n ? __("Checking {0} addresses in the background", [n]) : __("Everything is checked"), indicator: "green" })));
				this.$body.find(".cap-try-go").on("click", () => frappe.xcall(V + "check_one", { email: this.$body.find(".cap-try").val() }).then((r) => this.$body.find(".cap-try-out").html(`<b style="color:${colors[r.status] || "inherit"}">${e(r.status || __("Could not be decided"))}</b> ${e(r.reason)}${r.suggestion ? " · " + __("did you mean {0}?", [e(r.suggestion)]) : ""}`)));
			});
		}

		// Developers ----------------------------------------------------------

		tab_developers() {
			return Promise.all([frappe.xcall(D + "overview"), frappe.xcall(D + "webhooks")]).then(([o, hooks]) => {
				const origin = window.location.origin;
				const code = (text) => `<div class="cap-code"><code>${e(text)}</code><button class="btn btn-default btn-xs cap-copy" data-text="${e(text)}">${__("Copy")}</button></div>`;
				const calls = o.calls.map(([m, path, text]) => `<tr><td><b>${m}</b></td><td><code>${e(path)}</code></td><td class="cap-muted">${e(text)}</td></tr>`).join("");
				const subs = hooks.map((h) => `<tr><td>${e(h.description)}<div class="cap-muted">${e(h.url)}</div></td><td class="cap-muted">${h.events.map(e).join(", ")}</td>
					<td><span class="cap-badge ${h.active ? "Published" : "Failed"}">${h.active ? __("On") : __("Off")}</span><div class="cap-muted">${e(h.last_status || "")}${h.failures ? " · " + h.failures + " " + __("failed") : ""}</div></td>
					<td>${can_manage() ? `<button class="btn btn-default btn-xs cap-wh-test" data-name="${e(h.name)}">${__("Test")}</button> <button class="btn btn-default btn-xs cap-wh-edit" data-name="${e(h.name)}">${__("Edit")}</button> <button class="btn btn-default btn-xs cap-wh-secret" data-name="${e(h.name)}">${__("New secret")}</button> <button class="btn btn-default btn-xs cap-wh-del" data-name="${e(h.name)}">&times;</button>` : ""}</td></tr>`).join("");
				this.hooks = hooks; this.events = o.events;
				this.$body.html(`<div class="cap-card"><h3>${__("API")}</h3><div class="cap-muted">${__("For your own systems. Create an API key and secret for a manager (User → API Access → Generate Keys) and send it as a header. Every call is limited to your Company. Nothing here sends a message: sending stays with the campaigns and automations a person approved.")}</div>
					<h4>${__("Header")}</h4>${code("Authorization: token API_KEY:API_SECRET")}<h4>${__("Example")}</h4>${code(`curl -X POST "${origin}${o.base}api_public.person_upsert" -H "Authorization: token API_KEY:API_SECRET" -d "email=name@company.com" -d "name=Rahim" -d "tags=website" -d "consent_statement=Asked for our price list on the website"`)}
					<h4>${__("Calls")}</h4><table class="cap-table">${calls}</table><div class="cap-muted">${__("Each path starts with")} <code>${e(origin)}${e(o.base)}</code></div></div>
					<div class="cap-card"><div class="cap-bar"><h3 style="margin:0">${__("Webhooks")}</h3>${can_manage() ? `<button class="btn btn-primary btn-sm cap-wh-new">${__("New webhook")}</button>` : ""}</div>
					<div class="cap-muted">${__("We call your address when something happens (a signup, an open, an unsubscribe ...). Each call is signed so you can check it came from us (header X-Reckon-Signature: hex HMAC-SHA256 of the body with your secret). Addresses must be public https addresses; after 10 failures in a row a webhook switches itself off.")}</div>
					${hooks.length ? `<table class="cap-table"><tr><th>${__("Webhook")}</th><th>${__("Events")}</th><th>${__("Status")}</th><th></th></tr>${subs}</table>` : `<div class="cap-empty">${__("No webhooks yet.")}</div>`}</div>
					<div class="cap-card"><h3>${__("AI assistants (MCP)")}</h3><div class="cap-muted">${__("Claude, ChatGPT, Cursor and other assistants can look at your segments, forms, automations and results, count who a segment matches, draft a segment and tag people. They cannot send, approve, switch an automation on or delete: those stay with a person.")}</div>
					<h4>${__("Server address")}</h4>${code(origin + o.mcp)}<div class="cap-muted">${__("In Claude: Settings → Connectors → Add custom connector, paste the address, and send an API key as the header Authorization: token API_KEY:API_SECRET.")}</div></div>`);
				const $b = this.$body;
				$b.find(".cap-copy").on("click", (ev) => copy(ev.currentTarget.dataset.text));
				$b.find(".cap-wh-new").on("click", () => this.webhook_dialog(null));
				$b.find(".cap-wh-edit").on("click", (ev) => this.webhook_dialog(this.hooks.find((h) => h.name === ev.currentTarget.dataset.name)));
				$b.find(".cap-wh-test").on("click", (ev) => frappe.xcall(D + "test_webhook", { name: ev.currentTarget.dataset.name }).then((r) => { frappe.show_alert({ message: __("Test call: {0}", [r]), indicator: /^2/.test(r) ? "green" : "red" }); this.open("developers"); }));
				$b.find(".cap-wh-secret").on("click", (ev) => frappe.confirm(__("Make a new signing secret? The old one stops working."), () => frappe.xcall(D + "new_secret", { name: ev.currentTarget.dataset.name }).then((sec) => this.show_secret(sec))));
				$b.find(".cap-wh-del").on("click", (ev) => frappe.confirm(__("Delete this webhook?"), () => frappe.xcall(D + "delete_webhook", { name: ev.currentTarget.dataset.name }).then(() => this.open("developers"))));
			});
		}

		show_secret(secret) {
			frappe.msgprint({ title: __("Signing secret"), message: `<p>${__("Copy it now. It is not shown again.")}</p><div class="cap-code"><code>${e(secret)}</code></div>` });
		}

		webhook_dialog(existing) {
			const d = new frappe.ui.Dialog({
				title: existing ? __("Edit webhook") : __("New webhook"),
				fields: [{ fieldname: "description", fieldtype: "Data", label: __("Name"), reqd: 1, default: existing && existing.description },
					{ fieldname: "url", fieldtype: "Data", label: __("Address (https)"), reqd: 1, default: existing && existing.url },
					{ fieldname: "active", fieldtype: "Check", label: __("Active"), default: existing ? existing.active : 1 },
					{ fieldname: "evs", fieldtype: "MultiCheck", label: __("Events"), options: Object.entries(this.events).map(([value, label]) => ({ value, label, checked: existing ? existing.events.includes(value) : value === "signup" })), columns: 2 }],
				primary_action_label: __("Save"),
				primary_action: (v) => {
					const picked = (d.get_value("evs") || []);
					frappe.xcall(D + "save_webhook", { data: { name: existing && existing.name, description: v.description, url: v.url, active: v.active, events: picked } }).then((r) => {
						d.hide(); if (r.secret) this.show_secret(r.secret); this.open("developers");
					});
				},
			});
			d.show();
		}

		// Import --------------------------------------------------------------

		tab_import() {
			return frappe.xcall(S + "imports").then((jobs) => {
				this.$body.html(`<div class="cap-card cap-form"><h3>${__("Import people from a CSV file")}</h3>
					<div class="cap-muted">${__("The first row holds the column names. You say how these people agreed to hear from you; that statement is saved with each person. People who opted out before are left out.")}</div>
					${can_manage() ? `<div style="margin-top:10px"><input type="file" class="cap-file" accept=".csv,.txt,text/csv"></div>` : `<div class="cap-muted">${__("Ask a manager to import people.")}</div>`}
					<div class="cap-import"></div></div>
					<div class="cap-card"><h3>${__("Recent imports")}</h3>${jobs.length ? `<table class="cap-table"><tr><th>${__("Name")}</th><th>${__("Status")}</th><th>${__("New")}</th><th>${__("Known")}</th><th>${__("Skipped")}</th><th>${__("Opted out")}</th></tr>${jobs.map((j) => `<tr><td>${e(j.label)}<div class="cap-muted">${when(j.started_on)}</div></td><td><span class="cap-badge ${e(j.status)}">${e(j.status)}</span></td><td>${num(j.created)}</td><td>${num(j.updated)}</td><td>${num(j.skipped)}</td><td>${num(j.suppressed)}</td></tr>`).join("")}</table>` : `<div class="cap-muted">${__("No imports yet.")}</div>`}</div>`);
				this.$body.find(".cap-file").on("change", (ev) => this.read_file(ev.target.files[0]));
			});
		}

		read_file(file) {
			if (!file) return;
			if (file.size > 6000000) { frappe.msgprint(__("That file is too large. Split it into parts of 20,000 rows or fewer.")); return; }
			const reader = new FileReader();
			reader.onload = () => frappe.xcall(S + "import_preview", { csv_text: reader.result }).then((p) => this.paint_mapping(p, reader.result, file.name));
			reader.readAsText(file);
		}

		paint_mapping(p, text, file_name) {
			const field_label = { email: __("Email"), phone: __("Phone"), contact_name: __("Full name"), first_name: __("First name"), last_name: __("Last name"), business_name: __("Company"), city: __("City"), industry: __("Industry"), tags: __("Tags") };
			const opts = (cur) => `<option value="">${__("— leave out —")}</option>${p.fields.map((f) => `<option value="${f}" ${f === cur ? "selected" : ""}>${field_label[f] || f}</option>`).join("")}`;
			const rows = p.headers.map((h, i) => `<div class="cap-map"><b>${e(h)}</b><select class="form-control cap-m" data-i="${i}">${opts(p.mapping[i])}</select><span class="cap-muted">${p.sample.slice(0, 3).map((r) => e(r[i] || "")).filter(Boolean).join(" · ")}</span></div>`).join("");
			this.$body.find(".cap-import").html(`<h4>${__("{0} rows found in {1}", [num(p.total), e(file_name)])}</h4><div>${rows}</div>
				<div class="cap-two" style="margin-top:12px"><label>${__("Name this import")}<input class="form-control cap-label" value="${e(file_name.replace(/\.\w+$/, ""))}"></label>
				<label>${__("Where do these people come from?")}<input class="form-control cap-source" placeholder="${__("e.g. trade fair 2026")}"></label></div>
				<label>${__("Tags to add to everyone")}<input class="form-control cap-tags" placeholder="newsletter, trade-fair"></label>
				<label>${__("How did these people agree to hear from you? (required)")}<textarea class="form-control cap-consent" rows="2" placeholder="${__("e.g. Customers who asked for our newsletter at checkout")}"></textarea></label>
				<button class="btn btn-primary btn-sm cap-go">${__("Import")}</button><div class="cap-result" style="margin-top:12px"></div>`);
			this.$body.find(".cap-go").on("click", (ev) => {
				const mapping = this.$body.find(".cap-m").map((_, el) => el.value).get();
				$(ev.currentTarget).prop("disabled", true);
				frappe.xcall(S + "import_start", { csv_text: text, mapping, label: this.$body.find(".cap-label").val(), tags: this.$body.find(".cap-tags").val(), source_label: this.$body.find(".cap-source").val(),
					consent_statement: this.$body.find(".cap-consent").val(), file_name }).then((job) => this.watch(job)).catch(() => $(ev.currentTarget).prop("disabled", false));
			});
		}

		watch(job) {
			const tick = () => frappe.xcall(S + "import_status", { job }).then((s) => {
				const pct = s.total ? Math.min(100, Math.round(100 * (s.processed + s.skipped + s.repeats) / s.total)) : 0;
				this.$body.find(".cap-result").html(`<div class="cap-bar-progress"><i style="width:${s.status === "Done" ? 100 : pct}%"></i></div>
					<div class="cap-num"><div><b>${num(s.created)}</b><span>${__("new people")}</span></div><div><b>${num(s.updated)}</b><span>${__("already known")}</span></div><div><b>${num(s.skipped)}</b><span>${__("skipped")}</span></div>
					<div><b>${num(s.repeats)}</b><span>${__("repeats in the file")}</span></div><div><b>${num(s.suppressed)}</b><span>${__("left out (opted out)")}</span></div></div>
					<div><span class="cap-badge ${e(s.status)}">${e(s.status)}</span></div>
					${s.problems.length ? `<h4>${__("Skipped rows")}</h4>${s.problems.slice(0, 12).map((p) => `<div class="cap-sample">${__("Row {0}", [p.row])}: ${e(p.reason)}</div>`).join("")}` : ""}`);
				if (["Queued", "Running"].includes(s.status)) this.poll = setTimeout(tick, 2000);
			});
			tick();
		}
	}
})();
