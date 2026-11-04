// Message Templates: AI-written email and WhatsApp templates, approval, and broadcasts. Email health lives in Integrations.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-templates"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Message Templates"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.templates = new Templates(page);
	};
	frappe.pages["sales-templates"].on_page_show = (wrapper) => wrapper.templates && wrapper.templates.load();

	const API = "reckon_sales_agent.api_templates.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	class Templates {
		constructor(page) {
			this.page = page;
			this.$root = $(`<div class="stp"><div class="stp-builder"></div><div class="stp-main"></div></div>`).appendTo(page.main);
				this.draft = null;  // the template open in the builder: { name, channel, content, issues, preview }
		}

		load() {
			return frappe.xcall(API + "library").then((d) => { this.d = d; this.render(); this.renderBuilder(); });
		}

		render() {
			const d = this.d;
			const el = this.$root.find(".stp-main");
			el.html(`${d.can_manage ? `<div class="stp-card stp-write"><h3>${__("Write a template with AI")}</h3>
					<div class="stp-muted">${__("From your approved sales facts only. You approve it before it is used.")}</div>
					<div class="stp-row"><select class="form-control stp-ch"><option>Email</option><option>WhatsApp</option></select>
						<select class="form-control stp-lang"><option>English</option><option>Bangla</option></select></div>
					<input class="form-control stp-purpose" placeholder="${__("What is it for? e.g. first email to pharma distributors about van sales")}">
					<div class="stp-actions"><button class="btn btn-primary btn-sm stp-go">${__("Write it")}</button></div></div>` : ""}
				${d.templates.map((t) => `<div class="stp-card" data-t="${e(t.name)}">
					<div class="stp-head"><div><b>${e(t.template_name)}</b> <span class="stp-badge">${e(t.channel)}</span>
						<span class="stp-badge">${e(t.language)}</span>
						<span class="stp-badge ${t.status === "Approved" ? "ok" : ""}">${e(__(t.status))}</span>
						${t.ai_generated ? `<span class="stp-badge">${__("AI")}</span>` : ""}</div>
						<a class="btn btn-xs btn-default" href="/desk/sales-message-template/${encodeURIComponent(t.name)}">${__("Edit")}</a></div>
					${t.subject ? `<div class="stp-subject">${e(t.subject)}</div>` : ""}<pre>${e(t.body)}</pre>
					${t.channel === "WhatsApp" && t.whatsapp_params ? `<div class="stp-muted">${__("Variables")}: ${e(t.whatsapp_params)}</div>` : ""}
					${t.content_status === "Needs review" ? `<div class="stp-warn">${e(t.content_issues)}</div>` : t.content_status === "Passed" ? `<div class="stp-ok">${__("Content check passed")}</div>` : ""}
					${t.status === "Approved" ? `<div class="stp-muted">${t.channel === "Email" ? (t.email_template ? __("In the CRM email composer as “{0}”", [e(t.email_template)]) : "")
						: t.whatsapp_template ? __("Submitted to Meta as {0}", [e(t.whatsapp_template)]) : (d.whatsapp_app ? "" : __("Install frappe_whatsapp to submit it to Meta."))}</div>` : ""}
					<div class="stp-actions">${d.can_manage ? `<button class="btn btn-xs btn-default stp-open">${__("Edit in builder")}</button>` : ""}${t.status === "Draft" && d.can_manage ? `<button class="btn btn-xs btn-primary stp-approve">${__("Approve")}</button>` : ""}
						${t.status === "Approved" && d.can_manage ? `<button class="btn btn-xs btn-primary stp-cast">${__("Send to a segment")}</button>` : ""}
						${d.can_manage ? `<button class="btn btn-xs btn-default stp-retire">${__("Retire")}</button>` : ""}</div></div>`).join("")
				|| `<div class="stp-card stp-muted">${__("No templates yet.")}</div>`}`);
			el.find(".stp-go").on("click", (ev) => {
				const purpose = el.find(".stp-purpose").val().trim();
				if (!purpose) return frappe.msgprint(__("Say what the template is for."));
				$(ev.currentTarget).prop("disabled", true);
				frappe.call({ method: API + "write", args: { channel: el.find(".stp-ch").val(), language: el.find(".stp-lang").val(), purpose },
					freeze: true, freeze_message: __("Writing from your approved facts…") }).then(() => this.load())
					.always(() => $(ev.currentTarget).prop("disabled", false));
			});
			const name = (ev) => $(ev.currentTarget).closest(".stp-card").data("t");
			const tpl = (n) => d.templates.find((t) => t.name === n);
			el.find(".stp-approve").on("click", (ev) => {
				const t = tpl(name(ev));
				const go = (ack) => frappe.xcall(API + "approve", { template: t.name, acknowledge_issues: ack ? 1 : 0 }).then(() => this.load());
				if (t.content_status === "Needs review") frappe.confirm(__("The content check found issues. Approve anyway?"), () => go(true));
				else go(false);
			});
			el.find(".stp-open").on("click", (ev) => this.open_draft(name(ev)));
			el.find(".stp-retire").on("click", (ev) => frappe.xcall(API + "retire", { template: name(ev) }).then(() => this.load()));
			el.find(".stp-cast").on("click", (ev) => {
				const t = tpl(name(ev));
				frappe.prompt([{ fieldname: "segment", fieldtype: "Select", label: __("Segment"),
					options: [{ value: "", label: __("Every approved lead") }, ...d.segments.map((s) => ({ value: s.name, label: s.campaign_name }))],
					description: t.channel === "WhatsApp" ? __("Only leads who opted in to WhatsApp are reached.") : __("Only leads with an email are reached.") }],
				(v) => frappe.xcall(API + "broadcast", { template: t.name, segment: v.segment }).then((c) => {
					frappe.msgprint({ title: __("Ready for approval"), indicator: "green",
						message: __("Campaign {0} is waiting for your approval in the Agent Studio before anything is sent.", [e(c)]) });
				}), __("Send {0} to a segment", [t.channel]), __("Create the campaign"));
			});
		}
		// Template builder: one editor per channel. The server compiles and checks each change (nothing is saved until
		// Save), and the preview shows what would be sent.
		renderBuilder() {
			const el = this.$root.find(".stp-builder");
			if (!this.d.can_manage) return el.empty();
			if (!this.draft) {
				el.html(`<div class="stp-card stp-write"><h3>${__("Build a template")}</h3>
					<div class="stp-muted">${__("Email, SMS and WhatsApp each have their own builder. Drafts need approval before use.")}</div>
					<div class="stp-row"><select class="form-control stp-b-ch"><option>Email</option><option>SMS</option><option>WhatsApp</option></select>
						<input class="form-control stp-b-name" placeholder="${__("Template name")}"></div>
					<div class="stp-actions"><button class="btn btn-primary btn-sm stp-b-start">${__("Start")}</button></div></div>`);
				el.find(".stp-b-start").on("click", () => {
					const name = el.find(".stp-b-name").val().trim();
					if (!name) return frappe.msgprint(__("Give the template a name."));
					frappe.xcall(API + "start", { channel: el.find(".stp-b-ch").val(), template_name: name })
						.then((t) => this.open_draft(t));
				});
				return;
			}
			const d = this.draft;
			const blocks = d.content.blocks || [];
			const blockRow = (b, i) => {
				const field = (k, label, value, multi) => multi
					? `<textarea class="form-control stp-b-f" data-i="${i}" data-k="${k}" rows="3" placeholder="${e(label)}">${e(value || "")}</textarea>`
					: `<input class="form-control stp-b-f" data-i="${i}" data-k="${k}" placeholder="${e(label)}" value="${e(value || "")}">`;
				const body = {
					heading: () => field("text", __("Heading"), b.text),
					text: () => field("text", __("Paragraph (blank line starts a new one)"), b.text, true),
					button: () => field("label", __("Button label"), b.label) + field("url", "https://", b.url),
					image: () => field("src", "https://", b.src) + field("alt", __("Alt text"), b.alt),
					divider: () => `<div class="stp-muted">${__("Divider")}</div>`,
					spacer: () => field("height", __("Height (px)"), b.height),
				}[b.type];
				return `<div class="stp-block"><div class="stp-head"><span class="stp-badge">${e(b.type)}</span>
					<button class="btn btn-xs btn-default stp-b-del" data-i="${i}">${__("Remove")}</button></div>${body ? body() : ""}</div>`;
			};
			const ch = d.channel;
			let fields = "";
			if (ch === "Email") {
				fields = `<input class="form-control stp-b-f" data-k="subject" placeholder="${__("Subject")}" value="${e(d.content.subject || "")}">
					<div class="stp-blocks">${blocks.map(blockRow).join("")}</div>
					<div class="stp-row"><select class="form-control stp-b-type">${["heading", "text", "button", "image", "divider", "spacer"]
						.map((t) => `<option value="${t}">${t}</option>`).join("")}</select>
						<button class="btn btn-xs btn-default stp-b-add">${__("Add block")}</button></div>`;
			} else if (ch === "SMS") {
				fields = `<textarea class="form-control stp-b-f" data-k="text" rows="4" placeholder="${__("Message. Merge tags: {{business_name}}, {{offer}}")}">${e(d.content.text || "")}</textarea>`;
			} else {
				const buttons = (d.content.buttons || []).map((b, i) => `<div class="stp-row"><select class="form-control stp-b-f" data-i="${i}" data-k="kind">
					<option value="quick"${b.kind !== "url" ? " selected" : ""}>${__("Quick reply")}</option><option value="url"${b.kind === "url" ? " selected" : ""}>${__("Link")}</option></select>
					<input class="form-control stp-b-f" data-i="${i}" data-k="label" placeholder="${__("Button label")}" value="${e(b.label || "")}">
					<input class="form-control stp-b-f" data-i="${i}" data-k="url" placeholder="https://" value="${e(b.url || "")}">
					<button class="btn btn-xs btn-default stp-b-del" data-i="${i}">${__("Remove")}</button></div>`).join("");
				fields = `<input class="form-control stp-b-f" data-k="header" placeholder="${__("Header (optional, no merge tags)")}" value="${e(d.content.header || "")}">
					<textarea class="form-control stp-b-f" data-k="body" rows="4" placeholder="${__("Body. Merge tags become Meta variables.")}">${e(d.content.body || "")}</textarea>
					<input class="form-control stp-b-f" data-k="footer" placeholder="${__("Footer (optional)")}" value="${e(d.content.footer || "")}">
					${buttons}<div class="stp-actions"><button class="btn btn-xs btn-default stp-b-addbtn">${__("Add button")}</button></div>`;
			}
			el.html(`<div class="stp-card stp-write"><div class="stp-head"><div><b>${e(d.name)}</b> <span class="stp-badge">${e(ch)}</span></div>
				<button class="btn btn-xs btn-default stp-b-close">${__("Close")}</button></div>
				${fields}
				<div class="stp-preview">${d.preview || ""}</div>
				${(d.issues || []).map((x) => `<div class="stp-warn">${e(x)}</div>`).join("")}
				<div class="stp-actions"><button class="btn btn-primary btn-sm stp-b-save">${__("Save draft")}</button></div></div>`);
			this.bind_builder(el);
		}

		bind_builder(el) {
			el.find(".stp-b-f").on("input change", () => { this.collect(el); this.preview_later(); });
			el.find(".stp-b-add").on("click", () => {
				this.collect(el);
				this.draft.content.blocks = (this.draft.content.blocks || []).concat([{ type: el.find(".stp-b-type").val() }]);
				this.renderBuilder();
				this.preview_later();
			});
			el.find(".stp-b-addbtn").on("click", () => {
				this.collect(el);
				this.draft.content.buttons = (this.draft.content.buttons || []).concat([{ kind: "quick", label: "" }]);
				this.renderBuilder();
				this.preview_later();
			});
			el.find(".stp-b-del").on("click", (ev) => {
				this.collect(el);
				const i = Number(ev.currentTarget.dataset.i);
				if (this.draft.channel === "WhatsApp") this.draft.content.buttons.splice(i, 1);
				else this.draft.content.blocks.splice(i, 1);
				this.renderBuilder();
				this.preview_later();
			});
			el.find(".stp-b-save").on("click", () => {
				this.collect(el);
				frappe.xcall(API + "save", { template: this.draft.name, content: JSON.stringify(this.draft.content) })
					.then((r) => {
						frappe.show_alert({ message: r.issues.length ? __("Saved, with issues to fix") : __("Saved"),
							indicator: r.issues.length ? "orange" : "green" });
						return this.load();
					});
			});
			el.find(".stp-b-close").on("click", () => { this.draft = null; this.renderBuilder(); });
		}

		// Copy the editor's fields into the draft content; blocks and buttons are rebuilt from their rows.
		collect(el) {
			const c = this.draft.content;
			el.find(".stp-b-f").each((_, node) => {
				const k = node.dataset.k;
				const i = node.dataset.i;
				if (i === undefined) { c[k] = node.value; return; }
				const list = this.draft.channel === "WhatsApp" ? (c.buttons = c.buttons || []) : (c.blocks = c.blocks || []);
				list[Number(i)] = Object.assign({}, list[Number(i)], { [k]: node.value });
			});
		}

		preview_later() {
			clearTimeout(this.timer);
			this.timer = setTimeout(() => this.preview(), 400);
		}

		preview() {
			if (!this.draft) return;
			frappe.xcall(API + "check", { channel: this.draft.channel, content: JSON.stringify(this.draft.content) }).then((r) => {
				this.draft.issues = r.issues;
				if (this.draft.channel === "Email") this.draft.preview = r.body;
				else if (this.draft.channel === "SMS") {
					this.draft.preview = `<div class="stp-muted">${e(String(r.chars))} ${__("characters")} · ${e(String(r.parts))} ${__("part(s)")} · ${e(r.encoding)}</div>`;
				} else {
					this.draft.preview = `<div class="stp-muted">${__("Sent to Meta as")}: <code>${e(r.components.body.text)}</code>`
						+ (r.params.length ? ` · ${__("variables")}: ${e(r.params.join(", "))}` : "") + "</div>";
				}
				this.renderBuilder();
			});
		}

		open_draft(name) {
			const t = (this.d.templates || []).find((x) => x.name === name);
			let content = {};
			try { content = JSON.parse((t && t.builder_content) || "{}"); } catch (err) { content = {}; }
			this.draft = { name, channel: t ? t.channel : "Email", content, issues: [], preview: "" };
			this.load().then(() => this.preview());
		}
	}
})();
