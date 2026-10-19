frappe.ui.form.on("Sales Prospect", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args, message) =>
			frappe.call({ method: `reckon_sales_agent.api.${method}`, args, freeze: true }).then(() => {
				if (message) frappe.show_alert({ message, indicator: "green" });
				frm.reload_doc();
			});
		const review = (action) =>
			call("review_prospects", { prospects: [frm.doc.name], action }, __("Prospect updated"));

		if (frm.doc.review_status !== "Approved") {
			frm.add_custom_button(__("Approve"), () => review("approve"), __("Review"));
		}
		frm.add_custom_button(__("Defer"), () => review("defer"), __("Review"));
		frm.add_custom_button(__("Reject"), () => review("reject"), __("Review"));
		frm.add_custom_button(
			__("Merge Into..."),
			() =>
				frappe.prompt(
					[{ fieldname: "target", label: __("Keep this prospect"), fieldtype: "Link",
					   options: "Sales Prospect", reqd: 1, default: frm.doc.possible_duplicate_of }],
					(v) =>
						call("review_prospects",
							{ prospects: [frm.doc.name], action: "merge", merge_into: v.target },
							__("Merged")),
					__("Merge duplicate")
				),
			__("Review")
		);

		if (frm.doc.website) {
			frm.add_custom_button(__("Research Website"), () =>
				call("research", { prospects: [frm.doc.name] }, __("Research queued"))
			);
		}
		frm.add_custom_button(__("Score Again"), () => call("qualify", { prospect: frm.doc.name }, __("Scored")));

		if (frm.doc.review_status === "Approved" && !frm.doc.crm_lead) {
			frm.add_custom_button(__("Create CRM Lead"), () =>
				call("sync_prospect", { prospect: frm.doc.name }, __("Synced to CRM"))
			).addClass("btn-primary");
		}
		if (frm.doc.crm_lead) {
			frm.add_custom_button(__("Open in CRM"), () =>
				window.open(`/crm/leads/${encodeURIComponent(frm.doc.crm_lead)}`, "_blank", "noopener")
			);
		}
		if (frm.doc.retention_until) {
			frm.dashboard.add_comment(
				__("Some fields came from a source that only allows keeping them until {0}. Research the website to confirm them.",
					[frappe.datetime.str_to_user(frm.doc.retention_until)]),
				"yellow",
				true
			);
		}
		if (frm.doc.possible_duplicate_of) {
			frm.dashboard.add_comment(
				__("Possible duplicate of {0}.", [frappe.utils.escape_html(frm.doc.possible_duplicate_of)]),
				"orange",
				true
			);
		}
	},
});
