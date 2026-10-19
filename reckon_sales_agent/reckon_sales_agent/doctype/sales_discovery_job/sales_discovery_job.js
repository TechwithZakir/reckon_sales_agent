frappe.ui.form.on("Sales Discovery Job", {
	refresh(frm) {
		if (["Queued", "Running"].includes(frm.doc.status) && !frm.doc.cancel_requested) {
			frm.add_custom_button(__("Cancel Job"), () =>
				frappe.confirm(__("Stop this job after the current search?"), () =>
					frappe
						.call("reckon_sales_agent.api.cancel_job", { job: frm.doc.name })
						.then(() => frm.reload_doc())
				)
			);
		}
		if (frm.doc.status === "Running") {
			// Refresh progress while the background job runs.
			setTimeout(() => frm.doc.status === "Running" && frm.reload_doc(), 5000);
		}
		if (frm.doc.discovery_campaign) {
			frm.add_custom_button(__("Campaign"), () =>
				frappe.set_route("Form", "Sales Discovery Campaign", frm.doc.discovery_campaign)
			);
		}
	},
});
