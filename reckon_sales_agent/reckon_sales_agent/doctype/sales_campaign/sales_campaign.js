frappe.ui.form.on("Sales Campaign", {
	onload(frm) {
		if (frm.is_new() && !(frm.doc.steps || []).length) {
			frm.add_child("steps", {
				step_no: 1,
				delay_days: 0,
				subject_template: __("A quick idea for {{business_name}}"),
				body_template: __(
					"Dear {{business_name}} team,\n\n{{personal_line}}\n\n{{offer}}\n\nWould a short call next week be useful?\n\nBest regards,\n{{sender_name}}"
				),
			});
			frm.add_child("steps", {
				step_no: 2,
				delay_days: 4,
				subject_template: __("Following up: {{business_name}}"),
				body_template: __("Hello again,\n\nJust following up on my earlier note about {{offer}}.\n\nBest regards,\n{{sender_name}}"),
			});
			frm.refresh_field("steps");
		}
	},

	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, message, extra) =>
			frappe
				.call({ method: `reckon_sales_agent.api.${method}`, args: { campaign: frm.doc.name, ...(extra || {}) }, freeze: true })
				.then((r) => {
					frappe.show_alert({ message: message(r.message), indicator: "green" });
					frm.reload_doc();
				});

		if (["Draft", "Paused"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Submit for Approval"), () => call("submit_campaign", () => __("Submitted")));
		}
		if (frm.doc.status === "Pending Approval") {
			frm.add_custom_button(__("Approve and Start"), () =>
				frappe.confirm(__("Approve this campaign? Members are added from approved, qualified prospects."), () =>
					call("approve_campaign", (n) => __("{0} members added", [n]))
				)
			).addClass("btn-primary");
		}
		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Pause"), () => call("pause_campaign", () => __("Paused")));
			frm.add_custom_button(__("Add New Members"), () => call("refresh_members", (n) => __("{0} members added", [n])), __("Actions"));
			frm.add_custom_button(__("Draft Due Messages"), () => call("draft_now", (n) => __("{0} drafts created", [n])), __("Actions"));
			frm.add_custom_button(__("Send Approved Now"), () =>
				frappe.call("reckon_sales_agent.api.send_approved").then((r) => {
					frappe.show_alert({ message: __("{0} messages processed", [r.message || 0]), indicator: "green" });
					frm.reload_doc();
				}),
				__("Actions")
			);
		}
		frm.add_custom_button(__("Messages to Approve"), () =>
			frappe.set_route("List", "Sales Outreach Message", { campaign: frm.doc.name, status: "Draft" }), __("View"));
		frm.add_custom_button(__("Members"), () =>
			frappe.set_route("List", "Sales Campaign Member", { campaign: frm.doc.name }), __("View"));
		frm.add_custom_button(__("Events"), () =>
			frappe.set_route("List", "Sales Communication Event", { campaign: frm.doc.name }), __("View"));
		frm.add_custom_button(__("Analytics"), () => frappe.set_route("sales-analytics"), __("View"));
		frm.add_custom_button(__("Analyze with AI"), () =>
			frappe
				.call({ method: "reckon_sales_agent.api.analyze_campaign", args: { campaign: frm.doc.name }, freeze: true })
				.then(() => frm.reload_doc())
		);
		if (frm.doc.latest_insight) {
			frappe.db.get_value("Sales Campaign Insight", frm.doc.latest_insight, ["summary", "recommendations"]).then((r) => {
				const v = r.message || {};
				if (v.summary) {
					frm.dashboard.add_comment(
						`<b>${__("AI insight")}:</b> ${frappe.utils.escape_html(v.summary)}<br>${frappe.utils.escape_html(v.recommendations || "").replace(/\n/g, "<br>")}`,
						"blue",
						true
					);
				}
			});
		}
	},
});

frappe.ui.form.on("Sales Campaign Step", {
	channel(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (["SMS", "WhatsApp"].includes(row.channel)) {
			frappe.show_alert({
				message: __("{0} is sent only to prospects with recorded consent; keep it short and plain text.", [__(row.channel)]),
				indicator: "orange",
			});
		}
	},
});
