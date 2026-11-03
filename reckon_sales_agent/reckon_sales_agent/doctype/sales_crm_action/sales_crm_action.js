frappe.ui.form.on("Sales CRM Action", {
	refresh(frm) {
		if (frm.doc.status !== "Pending") return;
		const decide = (approve) => frappe.call({
			method: "reckon_sales_agent.api_crm.decide",
			args: { name: frm.doc.name, approve: approve ? 1 : 0 }, freeze: true,
		}).then(() => frm.reload_doc());
		frm.add_custom_button(__("Approve"), () => decide(true)).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () => decide(false));
	},
});
