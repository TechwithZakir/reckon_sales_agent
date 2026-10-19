frappe.ui.form.on("Sales Discovery Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args, message) =>
			frappe.call({ method: `reckon_sales_agent.api.${method}`, args, freeze: true }).then((r) => {
				if (message) frappe.show_alert({ message, indicator: "green" });
				frm.reload_doc();
				return r.message;
			});

		if (frm.doc.status !== "Running") {
			frm.add_custom_button(__("Preview Plan"), () =>
				call("preview_plan", { campaign: frm.doc.name }, __("Searches planned"))
			);
		}
		if (frm.doc.status === "Planned" && (frm.doc.planned_queries || []).length) {
			frm.add_custom_button(
				__("Start Discovery"),
				() =>
					frappe.confirm(
						__("Run {0} searches now?", [frm.doc.planned_queries.length]),
						() => call("start_discovery", { campaign: frm.doc.name }, __("Discovery started"))
					),
				null
			).addClass("btn-primary");
		}
		if (frm.doc.last_job) {
			frm.add_custom_button(__("Job"), () => frappe.set_route("Form", "Sales Discovery Job", frm.doc.last_job), __("View"));
		}
		frm.add_custom_button(
			__("Prospects"),
			() => frappe.set_route("List", "Sales Prospect", { discovery_campaign: frm.doc.name }),
			__("View")
		);
		frm.add_custom_button(__("Review Queue"), () => frappe.set_route("sales-review"), __("View"));
	},
});
