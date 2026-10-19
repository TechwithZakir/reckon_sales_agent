frappe.ui.form.on("Sales Outreach Message", {
	refresh(frm) {
		frm.set_read_only(frm.doc.status !== "Draft");
		if (frm.doc.status === "Draft" && !frm.is_dirty()) {
			frm.add_custom_button(__("Approve"), () =>
				frappe
					.call("reckon_sales_agent.api.approve_messages", { messages: [frm.doc.name] })
					.then(() => frm.reload_doc())
			).addClass("btn-primary");
		}
		if (frm.doc.ai_generated) {
			frm.dashboard.add_comment(__("The opening line was written by AI from evidence on the prospect's website. Check it before approving."), "blue", true);
		}
	},
});
