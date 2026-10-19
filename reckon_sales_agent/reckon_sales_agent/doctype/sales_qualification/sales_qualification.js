frappe.ui.form.on("Sales Qualification", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Override Result"), () =>
			frappe.prompt(
				[
					{ fieldname: "result", label: __("Result"), fieldtype: "Select",
					  options: "\nQualified\nNot Qualified", description: __("Leave empty to remove the override.") },
					{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text" },
				],
				(v) =>
					frappe
						.call("reckon_sales_agent.api.override_qualification", {
							qualification: frm.doc.name, result: v.result || "", reason: v.reason || "",
						})
						.then(() => frm.reload_doc()),
				__("Human override")
			)
		);
		frm.add_custom_button(__("Prospect"), () => frappe.set_route("Form", "Sales Prospect", frm.doc.prospect));
	},
});
