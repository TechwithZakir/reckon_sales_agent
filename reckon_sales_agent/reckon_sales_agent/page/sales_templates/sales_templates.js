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
			this.$root = $(`<div class="stp"><div class="stp-main"></div></div>`).appendTo(page.main);
		}

		load() {
			return frappe.xcall(API + "library").then((d) => { this.d = d; this.render(); });
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
					<div class="stp-actions">${t.status === "Draft" && d.can_manage ? `<button class="btn btn-xs btn-primary stp-approve">${__("Approve")}</button>` : ""}
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
	}
})();
