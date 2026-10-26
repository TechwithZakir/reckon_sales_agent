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
			frm.add_custom_button(__("Approve and Start"), () => {
				const issues = frm.doc.content_status === "Needs review";
				const text = issues
					? __("The content check found issues (see Content Check). Approve anyway? You confirm you have reviewed them.")
					: __("Approve this campaign? Members are added from approved, qualified prospects.");
				frappe.confirm(text, () =>
					call("approve_campaign", (n) => __("{0} members added", [n]), { acknowledge_issues: issues ? 1 : 0 })
				);
			}).addClass("btn-primary");
		}
		if (["Draft", "Paused", "Pending Approval"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Write with AI"), () => {
				const d = new frappe.ui.Dialog({
					title: __("Write the sequence with AI"),
					fields: [
						{ fieldname: "steps", fieldtype: "Int", label: __("Messages"), default: 3 },
						{ fieldname: "email", fieldtype: "Check", label: __("Email"), default: 1 },
						{ fieldname: "whatsapp", fieldtype: "Check", label: __("WhatsApp"), default: 1 },
						{ fieldname: "sms", fieldtype: "Check", label: __("SMS"), default: 0 },
						{ fieldname: "note", fieldtype: "HTML", options: `<div class="text-muted small">${__("Uses only your approved Knowledge Library and the campaign's segment and language. The current steps are replaced; the campaign needs approval before sending.")}</div>` },
					],
					primary_action_label: __("Write"),
					primary_action(values) {
						const channels = [values.email && "Email", values.whatsapp && "WhatsApp", values.sms && "SMS"].filter(Boolean);
						d.hide();
						call("write_campaign_with_ai", (n) => __("{0} messages written; review them, then submit for approval", [n]),
							{ steps: values.steps || 3, channels: channels.join(",") });
					},
				});
				d.show();
			});
		}
		if ((frm.doc.steps || []).length) {
			frm.add_custom_button(__("Check Content"), () =>
				call("check_campaign_content", (r) => (r.status === "Passed" ? __("No issues found") : __("{0} issue(s) to review", [r.issues.length]))));
		}
		if (frm.doc.content_status === "Needs review" && frm.doc.content_issues) {
			frm.dashboard.add_comment(`<b>${__("Content check")}:</b><br>${frappe.utils.escape_html(frm.doc.content_issues).replace(/\n/g, "<br>")}`, "orange", true);
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
