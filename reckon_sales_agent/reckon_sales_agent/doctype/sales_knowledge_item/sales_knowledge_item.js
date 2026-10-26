frappe.ui.form.on("Sales Knowledge Item", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.status === "Approved") {
			frm.set_intro(__("Approved: agents may use this wording. Editing it sends it back for approval."), "green");
			return;
		}
		frm.set_intro(__("Agents only use approved items. Pricing and Offer items are the only source of prices, discounts and offers in messages."), "blue");
		frm.add_custom_button(__("Approve"), () =>
			frappe.call({ method: "reckon_sales_agent.api.approve_knowledge", args: { items: [frm.doc.name] } }).then(() => frm.reload_doc())
		).addClass("btn-primary");
	},
});
