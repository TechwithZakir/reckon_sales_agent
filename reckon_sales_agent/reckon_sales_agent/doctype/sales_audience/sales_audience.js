frappe.ui.form.on("Sales Audience", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Count people"), () => frappe.xcall("reckon_sales_agent.api_campaign_studio.refresh_audience",
			{ name: frm.doc.name }).then((s) => {
			frappe.show_alert({ message: __("{0} people: {1} with an email, {2} with a phone", [s.total, s.with_email, s.with_phone]), indicator: "green" });
			frm.reload_doc();
		}));
		frm.add_custom_button(__("Campaign Studio"), () => frappe.set_route("campaign-studio"));
	},
});
