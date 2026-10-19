frappe.listview_settings["Sales Outreach Message"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { Draft: "orange", Approved: "blue", Sent: "green", "Dry Run": "gray", Failed: "red", Cancelled: "darkgrey" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		listview.page.add_action_item(__("Approve"), () => {
			const messages = listview.get_checked_items(true);
			if (!messages.length) return;
			frappe
				.call("reckon_sales_agent.api.approve_messages", { messages })
				.then(() => listview.refresh());
		});
	},
};
