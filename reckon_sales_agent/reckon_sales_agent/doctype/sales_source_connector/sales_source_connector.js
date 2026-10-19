frappe.ui.form.on("Sales Source Connector", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Check Connector"), () =>
			frappe.call("reckon_sales_agent.api.check_connector", { connector: frm.doc.name }).then((r) => {
				const result = r.message || {};
				frappe.msgprint({
					title: __(result.status || ""),
					message: frappe.utils.escape_html(result.error || __("The connector is ready to run.")),
					indicator: result.error ? "orange" : "green",
				});
				frm.reload_doc();
			})
		);
		if (frm.doc.connector_type === "manual_import") {
			frm.set_intro(__("Attach a CSV file with columns business_name, website, email, phone, industry, address, city, country."), "blue");
		}
		if (frm.doc.connector_type === "google_places_api") {
			frm.set_intro(__("Uses the official Google Places API with the platform's key. Google content is kept only for the platform's retention window unless the company's own website confirms it."), "blue");
		}
	},
});
