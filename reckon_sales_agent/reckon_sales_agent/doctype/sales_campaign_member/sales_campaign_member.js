frappe.ui.form.on("Sales Campaign Member", {
	refresh(frm) {
		if (["Active", "Eligible"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Stop Sequence"), () =>
				frappe.prompt(
					[{ fieldname: "reason", label: __("Reason"), fieldtype: "Data", default: __("Replied outside the CRM"), reqd: 1 }],
					(v) =>
						frappe
							.call("reckon_sales_agent.api.stop_member", { member: frm.doc.name, reason: v.reason })
							.then(() => frm.reload_doc()),
					__("Stop follow-up")
				)
			);
		}
	},
});
